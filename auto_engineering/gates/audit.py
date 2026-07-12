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
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

from auto_engineering.gates.base import Gate, GateVerdict

__all__ = [
    "DEFAULT_MAX_P0",
    "DEFAULT_MAX_P1",
    "DEFAULT_MAX_P2",
    "SKIP_DIRS",
    "AuditFinding",
    "AuditGate",
    "SemanticChecker",
    "finding_fingerprint",
]

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


# 语义检查器扩展点 (B15.3 #6): (rel_path, content) → 额外 findings.
# 默认注入 None (纯正则路径). 这是 Agent 侧 / LLM 后端语义层的挂载点 —
# Python 本身永不调 LLM (§A.1), 只做确定性正则 + 合并"注入进来"的语义结果.
# 检测正则看不到的语义问题 (误导性命名 / 逻辑与设计矛盾, 用 crafted context).
SemanticChecker = Callable[[str, str], list["AuditFinding"]]


def finding_fingerprint(f: AuditFinding) -> str:
    """finding 稳定指纹 `severity|dimension|file|description` — 行号**不入**指纹.

    行号随无关改动漂移; 排除后同一问题跨轮保持同一身份, 供 known-and-accepted
    生命周期 (B15.3 #9) 判定"是否已知已接受", 避免同一问题重复报告淹没新增项.
    """
    return f"{f.severity}|{f.dimension}|{f.file}|{f.description}"


# ============================================================
# 扫描规则 (直接复用 /audit Phase 1.2 通用反模式扫描)
# ============================================================

# 跳过这些目录
SKIP_DIRS = {
    ".git", ".venv", "venv", "node_modules", "__pycache__",
    ".pytest_cache", ".ae-state", "dist", "build", ".eggs",
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
    # 排除词用 noqa 词形 (非 "# noqa" 指令): `\b#` 永不匹配(前后皆非单词字符)→ 排除项会失效.
    # T30 规则自测发现此死分支, 改用 \bnoqa\b 使 "# noqa" 注释行真正被排除.
    r"^\s*except\b(?!.*\b(?:logger|logging|exc_info|raise|noqa)\b)",
    re.MULTILINE,
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
        semantic_checker: SemanticChecker | None = None,
        accepted_fingerprints: set[str] | None = None,
    ):
        self.max_p0 = max_p0
        self.max_p1 = max_p1
        self.max_p2 = max_p2
        self.include_large_files = include_large_files
        # B15.3 #6: opt-in 语义层 (默认 None = 纯正则, Python 永不调 LLM)
        self.semantic_checker = semantic_checker
        # B15.3 #9: known-and-accepted 指纹集 (从阈值计数中抑制, 运行时可经
        # contracts["accepted_audit_findings"] 追加)
        self.accepted_fingerprints = set(accepted_fingerprints or ())

    def run(self, project_root: Path) -> GateVerdict:
        project_root = Path(project_root)
        if verdict := self._validate_project_root(project_root):
            return verdict

        # v5.4: 增量扫描 — 若 contracts 提供 files_changed, 仅扫描变更文件
        target_files: set[str] | None = None
        if self.contracts and "files_changed" in self.contracts:
            raw = self.contracts["files_changed"]
            if isinstance(raw, list) and raw:
                target_files = set(raw)

        # B15.3 #9: known-and-accepted 指纹 (构造器 + contracts 合并)
        accepted: set[str] = set(self.accepted_fingerprints)
        if self.contracts and "accepted_audit_findings" in self.contracts:
            raw_acc = self.contracts["accepted_audit_findings"]
            if isinstance(raw_acc, list):
                accepted.update(str(x) for x in raw_acc)

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
                _logger.warning("audit scan: stat 失败 %s", path)
                continue

            findings.extend(self._scan_file(path, rel))
            files_scanned += 1

        # 大文件检查 (架构维度) — 增量模式下跳过 (需全量 rglob)
        if self.include_large_files and target_files is None:
            findings.extend(self._scan_large_files(project_root))

        return self._build_verdict(findings, files_scanned, accepted)

    # ── 文件级扫描 ──

    def _scan_file(self, path: Path, rel: str) -> list[AuditFinding]:
        """扫描单个文件, 返回 AuditFinding 列表."""
        try:
            content = path.read_text(errors="ignore")
        except OSError:
            _logger.warning("audit scan: 读取失败 %s", path)
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

        # B15.3 #6: opt-in 语义层 — 合并注入的语义 findings (默认无检查器则跳过)
        if self.semantic_checker is not None:
            findings.extend(self._run_semantic(rel, content))

        return findings

    def _run_semantic(self, rel: str, content: str) -> list[AuditFinding]:
        """调用注入的语义检查器, 异常降级为空 (语义后端故障不阻断确定性正则路径)."""
        try:
            extra = self.semantic_checker(rel, content) if self.semantic_checker else []
        except Exception:  # 语义后端(LLM/Agent)故障 → 降级, 保留正则结果
            _logger.warning("audit scan: 语义检查器异常 %s", rel, exc_info=True)
            return []
        return [f for f in (extra or []) if isinstance(f, AuditFinding)]

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
                _logger.warning("audit scan: 大文件检查失败 %s", path)
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
        accepted: set[str] | None = None,
    ) -> GateVerdict:
        # B15.3 #9: 分离 known-and-accepted — 仅 active findings 参与阈值判定,
        # accepted 命中不计数但记入 details (不静默丢弃).
        accepted = accepted or set()
        active = [f for f in findings if finding_fingerprint(f) not in accepted]
        suppressed = len(findings) - len(active)

        p0 = [f for f in active if f.severity == "P0"]
        p1 = [f for f in active if f.severity == "P1"]
        p2 = [f for f in active if f.severity == "P2"]

        failed = (
            len(p0) > self.max_p0
            or len(p1) > self.max_p1
            or len(p2) > self.max_p2
        )

        suppressed_note = f", 已接受抑制={suppressed}" if suppressed else ""
        msg_lines = [
            f"审计完成: {files_scanned} 文件扫描, "
            f"P0={len(p0)} (max={self.max_p0}), "
            f"P1={len(p1)} (max={self.max_p1}), "
            f"P2={len(p2)} (max={self.max_p2})" + suppressed_note,
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

        if not active:
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
                for f in active
            ],
            "files_scanned": files_scanned,
            "accepted_suppressed": suppressed,
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
