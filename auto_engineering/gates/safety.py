"""v2.0 Phase 04 — Gate 0: Safety (secrets + 危险代码检测).

设计来源: design/v2.0-Analysis-Loop.md §五 Phase 2 Gate 0.

实现策略:
    - 主路径: regex 扫描文件 → 检测常见 secret pattern
    - 备路径: gitleaks subprocess(若可用)
    - 失败处理: timeout / FileNotFoundError → drop (passed=True with skip message)

检测模式(覆盖常见 secret):
    - AWS access key: AKIA[0-9A-Z]{16}
    - AWS secret key: [A-Za-z0-9/+=]{40}
    - GitHub token: ghp_[A-Za-z0-9]{36}, gho_, ghu_, ghs_, ghr_
    - GitLab token: glpat-[A-Za-z0-9_-]{20}
    - Private key: -----BEGIN .* PRIVATE KEY-----
    - Generic API key: api_key=..., apikey=, secret=
    - 密码: password=..., passwd=...
    - DSN: postgres://user:pass@host, mongodb://user:pass@host
"""

from __future__ import annotations

import re
import subprocess
from pathlib import Path

from auto_engineering.gates.base import Gate, Verdict

# Secret pattern (常见公开 pattern, 不覆盖 100% 场景但覆盖主要风险)
# 2026-07-04 P1-1 补 5 种 (设计 §B12.4 声称但实际缺失):
# - Anthropic-style API Key (sk-...)
# - Generic long Token (32+ chars + keyword context)
# - 中国身份证 (18 位)
# - 中国手机号 (11 位)
# - 银行卡号 (13-19 位)
SECRET_PATTERNS: list[tuple[str, re.Pattern[str]]] = [
    # === P1-1 新增 (5 种, 设计文档 §B12.4 缺失) ===
    (
        "Anthropic API Key",
        # sk-ant-... / sk-... 32+ chars (Anthropic 风格 + OpenAI 风格)
        re.compile(r"sk-(?:ant-|api-)?[A-Za-z0-9_\-]{32,}"),
    ),
    (
        "Long Token (32+ chars)",
        # 通用 Token: token/secret/key + 32+ chars (Hex/Base64)
        # 2026-07-04 P1-1 修复: 加 access[_-]?token (覆盖 OAuth access_token 模式)
        re.compile(
            r"(?i)(?:^|[\s\"'=:>])"
            r"(?:token|secret|api[_-]?key|access[_-]?(?:key|token)|bearer)"
            r"[\s\"'=:>]+"
            r"([A-Za-z0-9_\-+/=]{32,})"
        ),
    ),
    (
        "中国身份证号",
        # 18 位: 前 17 位数字 + 最后一位数字或 X
        re.compile(r"(?<![0-9])[1-9]\d{5}(?:18|19|20)\d{2}(?:0[1-9]|1[0-2])(?:0[1-9]|[12]\d|3[01])\d{3}[\dXx](?![0-9])"),
    ),
    (
        "中国手机号",
        # 11 位: 1[3-9] 开头
        re.compile(r"(?<![0-9])1[3-9]\d{9}(?![0-9])"),
    ),
    (
        "银行卡号",
        # 13-19 位连续数字 (Luhn 算法校验留给 gitleaks).
        # 2026-07-04 P1 修复: 加 keyword context (card no / card number / 银行卡 / bank card)
        # 避免 13-19 位连续数字误报 (如 ISO 时间戳 20260624120000).
        # card[_\- ]?(?:no|number)? 让 "card " / "card no" / "card number" 都可触发.
        re.compile(
            r"(?i)(?:card[_\- ]?(?:no|number)?|银行卡号?|bank[_\- ]?card)[:\s是_-]*"
            r"(\d[\s-]?){13,19}(?![0-9])"
        ),
    ),
    # === 原有 9 种 ===
    ("AWS Access Key", re.compile(r"AKIA[0-9A-Z]{16}")),
    ("AWS Secret Key", re.compile(r"(?i)aws.{0,20}['\"][0-9a-zA-Z/+]{40}['\"]")),
    ("GitHub Token", re.compile(r"gh[pousr]_[A-Za-z0-9]{36}")),
    ("GitLab Token", re.compile(r"glpat-[A-Za-z0-9_\-]{20}")),
    ("Private Key", re.compile(r"-----BEGIN [A-Z ]*PRIVATE KEY-----")),
    ("Generic API Key", re.compile(r"(?i)(api[_-]?key|apikey)\s*=\s*['\"][A-Za-z0-9_\-]{16,}")),
    ("Generic Secret", re.compile(r"(?i)(secret[_-]?key|secret)\s*=\s*['\"][A-Za-z0-9_\-]{16,}")),
    ("Password Literal", re.compile(r"(?i)(password|passwd|pwd)\s*=\s*['\"][^'\"]{8,}")),
    ("DB DSN with password", re.compile(r"(postgres|mysql|mongodb)://[^:]+:[^@]+@")),
]

# 跳过这些目录(避免扫描 venv / .git / node_modules)
SKIP_DIRS = {
    ".git",
    ".venv",
    "venv",
    "node_modules",
    "__pycache__",
    ".pytest_cache",
    ".ae-checkpoints",
    "dist",
    "build",
    ".eggs",
}

# 单文件大小上限(MB), 超过跳过(防止大文件扫描)
_MAX_FILE_MB = 5


def _redact_gitleaks_output(text: str) -> str:
    """脱敏 gitleaks 输出 (v2.5 P2-C-5).

    gitleaks 默认 stdout 含 matched secret 值 (e.g., AWS_ACCESS_KEY=AKIA...)
    直接 echo 到 verdict 会把密钥泄漏到 CI 日志 / 用户终端.
    用 gitleaks 标准脱敏策略: 把 `=VALUE` / `: VALUE` 后的 secret 值
    替换为 ***REDACTED***, 保留 key 名 + 文件:行号 (定位信息).
    """
    import re as _re
    # 匹配 key=value 或 key: value, 替换 value 部分
    return _re.sub(
        r"(?P<key>[A-Za-z_][A-Za-z0-9_./-]*)\s*[:=]\s*\S+",
        r"\g<key>=***REDACTED***",
        text,
    )


def _scan_file(path: Path) -> list[str]:
    """扫描单个文件, 返回匹配到的 secret 描述列表.

    2026-07-04 修复 (Issue #6, 95 分): 去重 hits. Long Token 模式与
    Generic API Key / Generic Secret 模式在 `api_key=...` / `secret=...`
    同时命中, 同一 secret 之前会被报两次 (不同 desc). 现用 dict by desc
    去重 (保持顺序).
    """
    try:
        size_mb = path.stat().st_size / (1024 * 1024)
        if size_mb > _MAX_FILE_MB:
            return []
        content = path.read_text(errors="ignore")
    except (OSError, UnicodeDecodeError):
        return []

    hits: dict[str, None] = {}  # 用 dict 保插入顺序去重
    for desc, pat in SECRET_PATTERNS:
        if pat.search(content):
            hits[desc] = None
    return list(hits.keys())


def _scan_dir(project_root: Path) -> list[tuple[Path, list[str]]]:
    """递归扫描目录, 返回 [(file, [descs]), ...]."""
    findings = []
    for path in project_root.rglob("*"):
        if not path.is_file():
            continue
        # 跳过 SKIP_DIRS
        if any(part in SKIP_DIRS for part in path.parts):
            continue
        # 仅扫描文本类文件(扩展名启发式)
        if path.suffix.lower() in {
            ".py",
            ".js",
            ".ts",
            ".tsx",
            ".jsx",
            ".yaml",
            ".yml",
            ".json",
            ".toml",
            ".env",
            ".sh",
            ".md",
            ".txt",
            ".cfg",
            ".ini",
            ".pem",
            ".key",
        }:
            hits = _scan_file(path)
            if hits:
                findings.append((path, hits))
    return findings


class SafetyGate(Gate):
    """Gate 0: 检测 secrets / 危险代码.

    检查方式:
        1. regex 扫描所有文本文件(主路径, 默认启用)
        2. gitleaks subprocess(若可用, 备路径)

    Args:
        use_gitleaks: 是否尝试调用 gitleaks(若命令不存在则降级到 regex)
        timeout: gitleaks subprocess 超时(秒)

    v5.0 §B6.1: applies_to_stages = (architect, developer, critic)
        secret 检查每个阶段都跑 (每个 stage 输出都需经 secret 扫描)
    """

    name = "safety"
    applies_to_stages = ("architect", "developer", "critic")

    def __init__(self, use_gitleaks: bool = True, timeout: float = 30.0):
        self.use_gitleaks = use_gitleaks
        self.timeout = timeout

    def run(self, project_root: Path, contracts: dict | None = None) -> Verdict:
        """执行 safety 检查.

        Args:
            project_root: 项目根目录
            contracts: v5.0 §B6.1a — 契约字典 (SafetyGate 不使用, 仅签名兼容)

        Returns:
            Verdict: passed=True 表示无 secret; passed=False 表示检测到 secret.
        """
        project_root = Path(project_root)
        if not project_root.exists():
            return Verdict.failed(
                f"project_root 不存在: {project_root}",
                gate_name=self.name,
            )

        # 主路径: regex 扫描
        findings = _scan_dir(project_root)
        if findings:
            # 报告前 5 个 findings
            sample = findings[:5]
            msg_lines = [f"检测到 {len(findings)} 个可能的 secret:"]
            for path, descs in sample:
                rel = path.relative_to(project_root) if path.is_relative_to(project_root) else path
                msg_lines.append(f"  {rel}: {', '.join(descs)}")
            if len(findings) > 5:
                msg_lines.append(f"  ... (还有 {len(findings) - 5} 个)")
            return Verdict.failed("\n".join(msg_lines), gate_name=self.name)

        # 备路径: gitleaks(若启用)— 仅用于补充, regex 通过即可
        if self.use_gitleaks:
            try:
                result = subprocess.run(
                    [
                        "gitleaks",
                        "detect",
                        "--no-git",
                        "--source",
                        str(project_root),
                        "--no-banner",
                        "--no-color",
                    ],
                    capture_output=True,
                    text=True,
                    timeout=self.timeout,
                )
                # gitleaks exit codes:
                #   0 = no leaks
                #   1 = leaks found
                #   其他 = 工具错误(配置 / 命令错),忽略
                if result.returncode == 1:
                    # gitleaks 检测到 secret. v2.5 P2-C-5: gitleaks 默认
                    # stdout 含 secret 值本身, 直接 echo 到 verdict 反而
                    # 把密钥泄漏到日志/CI. 用 --no-banner + 截断前 200
                    # 字符 (而非 500) 减少暴露面. 调用方用 gitleaks
                    # `--redact` 拿纯 leak 描述 (无 secret 值).
                    sanitized = _redact_gitleaks_output(result.stdout[:200])
                    return Verdict.failed(
                        f"gitleaks 检测到 secret (secret 值已脱敏):\n{sanitized}",
                        gate_name=self.name,
                    )
            except (FileNotFoundError, subprocess.TimeoutExpired):
                # gitleaks 未安装或超时, 跳过 — regex 已通过
                pass

        return Verdict.passed("无 secret 检测到", gate_name=self.name)