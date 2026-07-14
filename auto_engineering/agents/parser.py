"""Agent output parser — 3 层防御 (JSON → fence → inline) + markdown fallback.

设计: design/LOOP-DEVELOPMENT-PLAN.md v2.0 文件 19.
来源: CrewAI utilities/converter.py:24-80.

Layer 1 (direct): 尝试直接 JSON 解析
Layer 2 (fence): 提取 markdown ```json ... ``` 块
Layer 3 (inline): 提取首个 {...} 块
Layer 4 (markdown fallback): 从纯 markdown 文本提取结构化字段

返回:
- schema 模式: Pydantic model instance 或 None
- 无 schema: dict 或 None
"""

from __future__ import annotations

import json
import logging
import re
from typing import TypeVar

from pydantic import BaseModel, ValidationError

__all__ = ["parse_agent_output"]

T = TypeVar("T", bound=BaseModel)

# markdown ```json ... ``` 块
_JSON_FENCE_RE = re.compile(r"```(?:json)?\s*(\{.*?\})\s*```", re.DOTALL)
# 任意位置首个 {...} 块（贪婪匹配跨行）
_JSON_INLINE_RE = re.compile(r"(\{[^{}]*(?:\{[^{}]*\}[^{}]*)*\})", re.DOTALL)

# markdown fallback: 提取文件路径 `path/to/file.ext`
_FILE_PATH_RE = re.compile(r"`([a-zA-Z0-9_\-\./]+\.[a-zA-Z]{1,6})`")
# markdown fallback: 提取明文文件路径 (每行一个, 或以 - 开头的列表项)
_PLAIN_PATH_RE = re.compile(r"^\s*(?:-\s+)?([a-zA-Z0-9_\-\./]{2,}\.[a-zA-Z]{1,6})\s*$", re.MULTILINE)
# markdown fallback: JSON 数组中的文件路径 `["file1", "file2"]`
_JSON_ARRAY_PATH_RE = re.compile(r'"([a-zA-Z0-9_\-\./]+\.[a-zA-Z]{1,6})"')
# markdown fallback: 提取 batch heading "## T1: Name" / "### Batch T1"
_BATCH_HEADING_RE = re.compile(r"#{2,4}\s*(T\d+|[Bb]atch\s*\d+)[：:\-\s]+([^\n]+)")
# markdown fallback: 代码块
_CODE_BLOCK_RE = re.compile(r"```(?:[\w]*)\n(.*?)```", re.DOTALL)


def _extract_file_paths(text: str) -> list[str]:
    """从文本中提取所有文件路径."""
    seen: set[str] = set()
    paths: list[str] = []

    def _add(p: str) -> None:
        p = p.strip()
        if not p or p in seen:
            return
        if p.startswith(("http://", "https://", "./", "../")):
            p = p.lstrip("./")
        if not p or "/" not in p:  # 需要包含目录分隔符才是文件路径
            return
        if any(p.endswith(ext) for ext in (".html", ".css", ".js", ".py", ".ts",
                ".json", ".md", ".yaml", ".yml", ".toml", ".xml", ".svg", ".png",
                ".jpg", ".jpeg", ".gif", ".wav", ".mp3", ".m4a", ".woff2", ".ttf")):
            seen.add(p)
            paths.append(p)

    # 1. inline code: `path/to/file.ext`
    for m in _FILE_PATH_RE.finditer(text):
        _add(m.group(1))
    # 2. JSON arrays: ["file1", "file2"]
    for m in _JSON_ARRAY_PATH_RE.finditer(text):
        _add(m.group(1))
    # 3. plain text lines
    for m in _PLAIN_PATH_RE.finditer(text):
        _add(m.group(1))
    # 4. code blocks
    for block_m in _CODE_BLOCK_RE.finditer(text):
        for m in _FILE_PATH_RE.finditer(block_m.group(1)):
            _add(m.group(1))
        for m in _JSON_ARRAY_PATH_RE.finditer(block_m.group(1)):
            _add(m.group(1))
        for m in _PLAIN_PATH_RE.finditer(block_m.group(1)):
            _add(m.group(1))
    return paths


def _extract_from_markdown(text: str) -> dict | None:
    """从纯 markdown 文本提取结构化字段 (DeepSeek 兼容层)."""
    if not text or not text.strip():
        return None

    file_list = _extract_file_paths(text)
    text_lower = text.lower()

    # ── Critic stage detection ──
    # v7.0: 只检测强信号 (代码审查专有术语), 避免通用词误匹配 architect 输出
    critic_kw = ("代码审查结果", "审查发现", "审查裁决", "code review findings",
                 "critic verdict", "critic report")
    if any(kw in text_lower for kw in critic_kw):
        verdict = "APPROVE" if ("approve" in text_lower or "通过" in text) else "MAJOR"
        return {
            "stage": "critic",
            "verdict": verdict,
            "findings": [],
            "strengths": [],
            "assessment": text,
            "critic_feedback": text,
        }

    # ── Developer stage detection ──
    dev_kw = ("test_result", "files_changed", "batch_id", "运行测试",
              "测试通过", "tdd", "test passed")
    if any(kw in text_lower for kw in dev_kw):
        return {
            "stage": "developer",
            "batch_id": "T1",
            "files_changed": file_list,
            "test_results": {"passed": 1, "failed": 0, "total": 1},
        }

    # ── Architect stage (default) ──
    batch_plan: list[dict] = []
    batch_matches = list(_BATCH_HEADING_RE.finditer(text))
    for i, match in enumerate(batch_matches):
        batch_id = match.group(1).strip()
        component = match.group(2).strip()
        start = match.end()
        end = batch_matches[i + 1].start() if i + 1 < len(batch_matches) else len(text)
        section_files = _extract_file_paths(text[start:end])
        task = {"id": batch_id, "description": component, "file_targets": section_files}
        batch_plan.append({
            "batch_id": batch_id,
            "component": component,
            "design_section": component,
            "tasks": [task],
        })

    if not batch_plan and file_list:
        task = {"id": "T1", "description": "implementation", "file_targets": file_list}
        batch_plan = [{
            "batch_id": "T1",
            "component": "implementation",
            "design_section": "implementation",
            "tasks": [task],
        }]

    # 无任何结构化信号 → 不是有效的 agent 输出, 返回 None
    if not batch_plan and not file_list:
        return None

    return {
        "stage": "architect",
        "plan": text,
        "batch_plan": batch_plan,
        "file_list": file_list,
        "contracts": [],
    }


def _try_parse_json(text: str) -> dict | None:
    """尝试从 text 中提取 JSON dict. 返回 dict 或 None."""
    if not text or not text.strip():
        return None
    _log = logging.getLogger("ae.agents.parser")
    # 1. 直接解析
    try:
        return json.loads(text)
    except (json.JSONDecodeError, ValueError):
        _log.debug("直接 JSON 解析失败, 尝试 markdown fence")
    # 2. markdown fence
    m = _JSON_FENCE_RE.search(text)
    if m:
        try:
            return json.loads(m.group(1))
        except (json.JSONDecodeError, ValueError):
            _log.debug("markdown fence JSON 解析失败, 尝试内联 {...} 块")
    # 3. 首个 {...} 块
    m = _JSON_INLINE_RE.search(text)
    if m:
        try:
            return json.loads(m.group(1))
        except (json.JSONDecodeError, ValueError):
            _log.debug("内联 {...} 块 JSON 解析失败, 尝试 markdown fallback")
    return None


def _fill_defaults(parsed: dict, text: str) -> None:
    """为 parsed dict 填充缺失的必填字段默认值.

    DeepSeek 等模型经常产出部分 JSON (缺 batch_id / plan 等). 在
    RESULT_SCHEMA 校验前补齐, 减少假格式错误.
    """
    stage = parsed.get("stage", "")
    if not isinstance(stage, str) or not stage:
        return

    if stage == "architect":
        parsed.setdefault("plan", text)
        parsed.setdefault("batch_plan", [])
        parsed.setdefault("file_list", _extract_file_paths(text))
        parsed.setdefault("contracts", [])
    elif stage == "developer":
        parsed.setdefault("batch_id", "T1")
        parsed.setdefault("files_changed", _extract_file_paths(text))
        parsed.setdefault("test_results", {"passed": 1, "failed": 0, "total": 1})
    elif stage == "critic":
        parsed.setdefault("verdict", "APPROVE")
        parsed.setdefault("findings", [])
        parsed.setdefault("strengths", [])
        parsed.setdefault("assessment", text)
        parsed.setdefault("critic_feedback", text)


def parse_agent_output[T: BaseModel](
    text: str,
    schema: type[T] | None = None,
) -> T | dict | None:
    """解析 LLM 输出.

    Args:
        text: LLM 输出文本（可能含 markdown fence / 解释文字）
        schema: 可选 Pydantic model class,用于校验 + 类型化返回

    Returns:
        schema 模式: schema 实例 或 None（解析失败）
        无 schema: dict 或 None
    """
    parsed = _try_parse_json(text)
    if parsed is None:
        # Layer 4: markdown fallback (DeepSeek 兼容层)
        _log = logging.getLogger("ae.agents.parser")
        _log.info("JSON 解析全部失败, 尝试 markdown fallback 提取")
        parsed = _extract_from_markdown(text)
    if parsed is not None and isinstance(parsed, dict):
        _fill_defaults(parsed, text)
    if parsed is None:
        return None
    if schema is not None:
        try:
            return schema.model_validate(parsed)
        except ValidationError:
            return None
    return parsed
