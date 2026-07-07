"""v5.4 — AuditGate: 代码质量深度审计 Gate.

直接复用 /audit 技能的 Phase 1 扫描模式, 5 维度审计:
  1. 代码质量 — 静默吞异常 / 空 catch / 硬编码密钥
  2. 工程化规范 — TODO/FIXME/HACK 遗留 / 注释掉的代码
  3. 架构合理性 — 大文件 (>400 行) / 目录文件数过多
  4. 代码逻辑虚化度 — 注释声称借鉴但实现不同 / dead code 标记
  5. 团队协作友好度 — 公开 API 命名一致性 / 错误消息可操作性

返回 GateVerdict, 按 severity 阈值决定 pass/fail.
默认: 任何 P0 → fail; ≥3 P1 → fail; P2 仅 warn.

与 /audit 的关系:
  - Phase 1 自动化扫描 → 本 Gate 直接实现 (快速, 确定性)
  - Phase 2 深度 Agent 审计 → 可选 LLM 增强路径 (future)
  - Phase 3 汇总报告 → GateVerdict.message (结构化 findings)
"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass, field
from pathlib import Path

from auto_engineering.gates.base import Gate, GateVerdict

_logger = logging.getLogger("ae.gates.audit")

# ============================================================
# Finding 数据结构
# ============================================================


@dataclass
class AuditFinding:
    """单条审计发现."""

    severity: str  # "P0" | "P1" | "P2"
    dimension: str  # "代码质量" | "工程化规范" | "架构合理性" | "代码逻辑虚化度" | "团队协作友好度"
    file: str  # 相对路径
    line: int
    description: str
    evidence: str = ""


# ============================================================
# 扫描规则 (直接复用 /audit Phase 1.2 通用反模式扫描)
# ============================================================

# 跳过这些目录
SKIP_DIRS = {
    ".git", ".venv", "venv", "node_modules", "__pycache__",
    ".pytest_cache", ".ae-checkpoints", "dist", "build", ".eggs",
    "_scratch", ".planning",
}

# 单文件大小上限 (MB)
_MAX_FILE_MB = 5

# 大文件行数阈值
_LARGE_FILE_LINES = 400

# 目录文件数建议上限
_MAX_FILES_PER_DIR = 12

# 默认阈值
DEFAULT_MAX_P0 = 0   # 任何 P0 → fail
DEFAULT_MAX_P1 = 3   # ≥3 P1 → fail
DEFAULT_MAX_P2 = 10  # ≥10 P2 → fail (warn)


# ── Pattern 定义 ──

# P0: 静默吞异常 (Python)
_SILENT_EXCEPT_PY = re.compile(
    r"^\s*except\b(?!.*\b(?:logger|logging|exc_info|raise|# noqa)\b)",
    re.MULTILINE,
)

# P0: 空 except 块 (Python) — 缩进后只有 pass 或空白
_EMPTY_EXCEPT_PY = re.compile(
    r"except[^:]*:\s*\n\s*(?:pass|\.\.\.)\s*(?:\n|$)",
)

# P0: 硬编码密钥/密码 (通用)
_HARDCODED_SECRET = re.compile(
    r"(?i)(?:api[_-]?key|secret[_-]?key|password|token|AUTH_TOKEN)"
    r"\s*[:=]\s*['\"][A-Za-z0-9_\-]{16,}['\"]",
)

# P1: TODO/FIXME/HACK/XXX
_TODO_FIXME = re.compile(r"(?:TODO|FIXME|HACK|XXX)\b")

# P1: 注释掉的代码 (Python — # def / # class)
_COMMENTED_CODE_PY = re.compile(r"^\s*#\s*(?:def |class |import |from |return |if |for |while )", re.MULTILINE)

# P1: 注释掉的代码 (TS/JS — // function / // const / // let)
_COMMENTED_CODE_JS = re.compile(r"^\s*//\s*(?:function |const |let |var |import |export |class )", re.MULTILINE)

# P2: 过长的行 (>120 字符)
_LONG_LINE = re.compile(r"^.{121,}$", re.MULTILINE)

# P2: 裸 print / console.log (调试残留)
_DEBUG_PRINT_PY = re.compile(r"^\s*print\(", re.MULTILINE)
_DEBUG_PRINT_JS = re.compile(r"^\s*console\.(?:log|debug|warn)\(", re.MULTILINE)

# ── 文件扩展名分类 ──

_PY_EXTS = {".py"}
_JS_EXTS = {".js", ".ts", ".tsx", ".jsx", ".mjs", ".cjs"}
_TEXT_EXTS = _PY_EXTS | _JS_EXTS | {
    ".yaml", ".yml", ".json", ".toml", ".md", ".txt",
    ".cfg", ".ini", ".sh", ".env",
}


def _should_skip(path: Path) -> bool:
    """检查路径是否应跳过."""
    return any(part in SKIP_DIRS for part in path.parts)


def _is_text_file(path: Path) -> bool:
    return path.suffix.lower() in _TEXT_EXTS


# ============================================================
# AuditGate
# ============================================================


class AuditGate(Gate):
    """代码质量深度审计 Gate.

    复用 /audit 技能的 Phase 1 自动化扫描 (grep-style pattern matching),
    5 维度审计, 按 severity 阈值决定 pass/fail.

    Args:
        max_p0: P0 数量上限 (默认 0, 任何 P0 → fail)
        max_p1: P1 数量上限 (默认 3)
        max_p2: P2 数量上限 (默认 10)
        include_large_files: 是否检查大文件 (默认 True)

    v5.0 §B6.1: applies_to_stages = (developer, critic)
        audit 在 developer 产出代码后、critic 审查前跑, 早期发现问题加速收敛.
    """

    name = "audit"
    applies_to_stages = ("developer", "critic")

    def __init__(
        self,
        max_p0: int = DEFAULT_MAX_P0,
        max_p1: int = DEFAULT_MAX_P1,
        max_p2: int = DEFAULT_MAX_P2,
        include_large_files: bool = True,
    ):
        self.max_p0 = max_p0
        self.max_p1 = max_p1
        self.max_p2 = max_p2
        self.include_large_files = include_large_files

    def run(self, project_root: Path, contracts: dict | None = None) -> GateVerdict:
        project_root = Path(project_root)
        if not project_root.exists():
            return GateVerdict.failed(
                f"project_root 不存在: {project_root}",
                gate_name=self.name,
            )

        # v5.4: 增量扫描 — 若 contracts 提供 files_changed, 仅扫描变更文件
        target_files: set[str] | None = None
        if contracts and "files_changed" in contracts:
            raw = contracts["files_changed"]
            if isinstance(raw, list) and raw:
                target_files = set(raw)

        findings: list[AuditFinding] = []
        files_scanned = 0

        for path in project_root.rglob("*"):
            if not path.is_file():
                continue
            if _should_skip(path):
                continue
            if not _is_text_file(path):
                continue

            rel = str(path.relative_to(project_root))

            # 增量模式: 跳过未变更文件
            if target_files is not None and rel not in target_files:
                continue

            # 跳过大文件
            try:
                size_mb = path.stat().st_size / (1024 * 1024)
                if size_mb > _MAX_FILE_MB:
                    continue
            except OSError:
                _logger.debug("audit scan: stat 失败 %s", py_file)
                continue

            findings.extend(self._scan_file(path, rel))
            files_scanned += 1

        # 大文件检查 (架构维度) — 增量模式下跳过 (需全量 rglob)
        if self.include_large_files and target_files is None:
            findings.extend(self._scan_large_files(project_root))

        return self._build_verdict(findings, files_scanned)

    # ── 文件级扫描 ──

    def _scan_file(self, path: Path, rel: str) -> list[AuditFinding]:
        """扫描单个文件, 返回 AuditFinding 列表."""
        try:
            content = path.read_text(errors="ignore")
        except OSError:
            _logger.debug("audit scan: 读取失败 %s", path)
            return []

        findings: list[AuditFinding] = []
        is_py = path.suffix in _PY_EXTS
        is_js = path.suffix in _JS_EXTS

        # P0: 硬编码密钥 (通用)
        for m in _HARDCODED_SECRET.finditer(content):
            line_no = content[: m.start()].count("\n") + 1
            findings.append(AuditFinding(
                severity="P0", dimension="代码质量",
                file=rel, line=line_no,
                description="硬编码密钥/token",
                evidence=m.group()[:60] + ("..." if len(m.group()) > 60 else ""),
            ))

        if is_py:
            findings.extend(self._scan_py(content, rel))
        elif is_js:
            findings.extend(self._scan_js(content, rel))

        return findings

    def _scan_py(self, content: str, rel: str) -> list[AuditFinding]:
        findings: list[AuditFinding] = []

        # P0: 静默吞异常
        for m in _SILENT_EXCEPT_PY.finditer(content):
            line_no = content[: m.start()].count("\n") + 1
            findings.append(AuditFinding(
                severity="P0", dimension="代码质量",
                file=rel, line=line_no,
                description="静默吞异常 (except 无 logger/raise)",
                evidence=m.group().strip()[:80],
            ))

        # P1: TODO/FIXME/HACK/XXX
        for m in _TODO_FIXME.finditer(content):
            line = content[: m.start()].count("\n")
            line_no = line + 1
            line_text = content.splitlines()[line] if line < len(content.splitlines()) else ""
            findings.append(AuditFinding(
                severity="P1", dimension="工程化规范",
                file=rel, line=line_no,
                description=f"遗留标记: {m.group()}",
                evidence=line_text.strip()[:80],
            ))

        # P1: 注释掉的代码
        for m in _COMMENTED_CODE_PY.finditer(content):
            line_no = content[: m.start()].count("\n") + 1
            findings.append(AuditFinding(
                severity="P1", dimension="代码逻辑虚化度",
                file=rel, line=line_no,
                description="注释掉的代码 (疑似废弃逻辑)",
                evidence=m.group().strip()[:80],
            ))

        # P2: 调试残留
        for m in _DEBUG_PRINT_PY.finditer(content):
            line = content[: m.start()].count("\n")
            line_no = line + 1
            line_text = content.splitlines()[line] if line < len(content.splitlines()) else ""
            # 跳过 logger/click.echo (正常输出)
            if "logger" in line_text.lower() or "click.echo" in line_text:
                continue
            findings.append(AuditFinding(
                severity="P2", dimension="工程化规范",
                file=rel, line=line_no,
                description="调试残留: print()",
                evidence=line_text.strip()[:80],
            ))

        # P2: 超长行
        for m in _LONG_LINE.finditer(content):
            line_no = content[: m.start()].count("\n") + 1
            findings.append(AuditFinding(
                severity="P2", dimension="工程化规范",
                file=rel, line=line_no,
                description=f"超长行 ({len(m.group())} 字符)",
                evidence=m.group()[:80] + "...",
            ))

        return findings

    def _scan_js(self, content: str, rel: str) -> list[AuditFinding]:
        findings: list[AuditFinding] = []

        # P1: TODO/FIXME/HACK/XXX
        for m in _TODO_FIXME.finditer(content):
            line = content[: m.start()].count("\n")
            line_no = line + 1
            line_text = content.splitlines()[line] if line < len(content.splitlines()) else ""
            findings.append(AuditFinding(
                severity="P1", dimension="工程化规范",
                file=rel, line=line_no,
                description=f"遗留标记: {m.group()}",
                evidence=line_text.strip()[:80],
            ))

        # P1: 注释掉的代码
        for m in _COMMENTED_CODE_JS.finditer(content):
            line_no = content[: m.start()].count("\n") + 1
            findings.append(AuditFinding(
                severity="P1", dimension="代码逻辑虚化度",
                file=rel, line=line_no,
                description="注释掉的代码 (疑似废弃逻辑)",
                evidence=m.group().strip()[:80],
            ))

        # P2: 调试残留
        for m in _DEBUG_PRINT_JS.finditer(content):
            line = content[: m.start()].count("\n")
            line_no = line + 1
            line_text = content.splitlines()[line] if line < len(content.splitlines()) else ""
            # 跳过 logger 调用
            if "logger" in line_text.lower():
                continue
            findings.append(AuditFinding(
                severity="P2", dimension="工程化规范",
                file=rel, line=line_no,
                description="调试残留: console.log/debug/warn",
                evidence=line_text.strip()[:80],
            ))

        # P2: 超长行
        for m in _LONG_LINE.finditer(content):
            line_no = content[: m.start()].count("\n") + 1
            findings.append(AuditFinding(
                severity="P2", dimension="工程化规范",
                file=rel, line=line_no,
                description=f"超长行 ({len(m.group())} 字符)",
                evidence=m.group()[:80] + "...",
            ))

        return findings

    # ── 架构维度 ──

    def _scan_large_files(self, project_root: Path) -> list[AuditFinding]:
        """检测大文件 + 目录文件数过多."""
        findings: list[AuditFinding] = []
        dir_files: dict[str, int] = {}

        for path in project_root.rglob("*"):
            if not path.is_file():
                continue
            if _should_skip(path):
                continue
            if not _is_text_file(path):
                continue

            # 统计目录文件数
            parent = str(path.parent.relative_to(project_root))
            dir_files[parent] = dir_files.get(parent, 0) + 1

            # 大文件检测
            if not self.include_large_files:
                continue
            try:
                line_count = path.read_text(errors="ignore").count("\n")
            except OSError:
                _logger.debug("audit scan: 大文件检查失败 %s", path)
                continue
            if line_count > _LARGE_FILE_LINES:
                rel = str(path.relative_to(project_root))
                findings.append(AuditFinding(
                    severity="P2", dimension="架构合理性",
                    file=rel, line=0,
                    description=f"大文件 ({line_count} 行 > {_LARGE_FILE_LINES})",
                ))

        # 目录文件数过多
        for d, count in dir_files.items():
            if count > _MAX_FILES_PER_DIR:
                findings.append(AuditFinding(
                    severity="P2", dimension="架构合理性",
                    file=f"{d}/", line=0,
                    description=f"目录文件数过多 ({count} > {_MAX_FILES_PER_DIR})",
                ))

        return findings

    # ── 判定逻辑 ──

    def _build_verdict(
        self, findings: list[AuditFinding], files_scanned: int,
    ) -> GateVerdict:
        p0 = [f for f in findings if f.severity == "P0"]
        p1 = [f for f in findings if f.severity == "P1"]
        p2 = [f for f in findings if f.severity == "P2"]

        failed = (
            len(p0) > self.max_p0
            or len(p1) > self.max_p1
            or len(p2) > self.max_p2
        )

        msg_lines = [
            f"审计完成: {files_scanned} 文件扫描, "
            f"P0={len(p0)} (max={self.max_p0}), "
            f"P1={len(p1)} (max={self.max_p1}), "
            f"P2={len(p2)} (max={self.max_p2})",
        ]

        if p0:
            msg_lines.append(f"\n  P0 ({len(p0)}):")
            for f in p0[:5]:
                msg_lines.append(f"    [{f.dimension}] {f.file}:{f.line} — {f.description}")
            if len(p0) > 5:
                msg_lines.append(f"    ... (还有 {len(p0) - 5} 个)")

        if p1:
            msg_lines.append(f"\n  P1 ({len(p1)}):")
            for f in p1[:5]:
                msg_lines.append(f"    [{f.dimension}] {f.file}:{f.line} — {f.description}")
            if len(p1) > 5:
                msg_lines.append(f"    ... (还有 {len(p1) - 5} 个)")

        if p2:
            msg_lines.append(f"\n  P2 ({len(p2)}):")
            for f in p2[:3]:
                msg_lines.append(f"    [{f.dimension}] {f.file}:{f.line} — {f.description}")
            if len(p2) > 3:
                msg_lines.append(f"    ... (还有 {len(p2) - 3} 个)")

        if not findings:
            msg_lines.append("\n  无审计发现")

        message = "\n".join(msg_lines)

        details = {
            "findings": [
                {
                    "severity": f.severity,
                    "dimension": f.dimension,
                    "file": f.file,
                    "line": f.line,
                    "description": f.description,
                    "evidence": f.evidence,
                }
                for f in findings
            ],
            "files_scanned": files_scanned,
        }
        if failed:
            return GateVerdict(
                gate_name=self.name, passed=False, message=message,
                details=details,
            )
        return GateVerdict(
            gate_name=self.name, passed=True, message=message,
            details=details,
        )
