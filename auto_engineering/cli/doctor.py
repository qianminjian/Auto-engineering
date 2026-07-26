"""CLI doctor 命令 — 环境预检 (v5.0 §PE.6).

检查项 (多行 ✓/✗ 输出, IL-AC-01 init-manifest 集成):
    1. Python ≥ 3.12
    2. uv ≥ 0.5 (包管理工具)
    3. git ≥ 2.40
    4. sqlite3 ≥ 3.42 (用于 SQLiteCheckpointStore)
    5. N/A (SDK 自动从 env 读 key, Plugin 模式无需设置)
    6. .ae-state/ 可读写 (项目状态目录)
    7. init-manifest.json 存在 (IL-AC-01)

Exit codes:
    0 = 全部 ✓
    1 = 存在 ✗
"""

from __future__ import annotations

import shutil
import sqlite3
import subprocess
import sys
from pathlib import Path

import click

from auto_engineering.utils import parse_version as _parse_version

# 最低版本要求
PYTHON_MIN = (3, 12)
UV_MIN = (0, 5, 0)
GIT_MIN = (2, 40, 0)
SQLITE_MIN = (3, 42, 0)


def _check_python() -> tuple[bool, str]:
    """检查 Python 版本 ≥ 3.12."""
    v = sys.version_info
    current = (v.major, v.minor)
    ok = current >= PYTHON_MIN
    version_str = f"{v.major}.{v.minor}.{v.micro}"
    if ok:
        return True, f"Python {version_str}     (required: >={PYTHON_MIN[0]}.{PYTHON_MIN[1]})"
    return False, f"Python {version_str}     (required: >={PYTHON_MIN[0]}.{PYTHON_MIN[1]}) — 当前版本过低"


def _check_uv() -> tuple[bool, str]:
    """检查 uv ≥ 0.5 (包管理工具)."""
    uv_path = shutil.which("uv")
    if not uv_path:
        return False, "uv 未安装 (required: >=0.5.0) — 请运行 `brew install uv` 或 `pip install uv`"
    try:
        result = subprocess.run(["uv", "--version"], capture_output=True, text=True, timeout=5)
        # 输出形如: "uv 0.11.12 (Homebrew ...)"
        line = result.stdout.strip()
        # 提取版本号
        parts = line.split()
        ver_str = parts[1] if len(parts) >= 2 else "0.0.0"
        current = _parse_version(ver_str)
        if current >= UV_MIN:
            return True, f"uv {ver_str}          (required: >={UV_MIN[0]}.{UV_MIN[1]})"
        return False, f"uv {ver_str}          (required: >={UV_MIN[0]}.{UV_MIN[1]}) — 版本过低"
    except (OSError, subprocess.CalledProcessError, ValueError) as e:
        return False, f"uv 检查失败: {e}"


def _check_git() -> tuple[bool, str]:
    """检查 git ≥ 2.40."""
    git_path = shutil.which("git")
    if not git_path:
        return False, "git 未安装 (required: >=2.40)"
    try:
        result = subprocess.run(["git", "--version"], capture_output=True, text=True, timeout=5)
        # "git version 2.50.1 (Apple Git-155)"
        line = result.stdout.strip()
        # 找第一个看起来像版本号的 token
        ver_str = "0.0.0"
        for token in line.split():
            if token and token[0].isdigit():
                ver_str = token
                break
        current = _parse_version(ver_str)
        if current >= GIT_MIN:
            return True, f"git {ver_str}        (required: >={GIT_MIN[0]}.{GIT_MIN[1]})"
        return False, f"git {ver_str}        (required: >={GIT_MIN[0]}.{GIT_MIN[1]}) — 版本过低"
    except (OSError, subprocess.CalledProcessError, ValueError) as e:
        return False, f"git 检查失败: {e}"


def _check_sqlite3() -> tuple[bool, str]:
    """检查 sqlite3 ≥ 3.42 (Python 内置)."""
    ver_str = sqlite3.sqlite_version
    current = _parse_version(ver_str)
    if current >= SQLITE_MIN:
        return True, f"sqlite3 {ver_str}    (required: >={SQLITE_MIN[0]}.{SQLITE_MIN[1]})"
    return False, f"sqlite3 {ver_str}    (required: >={SQLITE_MIN[0]}.{SQLITE_MIN[1]}) — 版本过低"


def _check_api_key() -> tuple[bool, str]:
    """检查 LLM 凭据 (ANTHROPIC_API_KEY 或 ANTHROPIC_AUTH_TOKEN).

    2026-07-04 修复 (prismscan 真实 bug): 用 4 级 fallback detect_plugin_mode
    而非 2 级, 支持 CLAUDE_CODE_ENTRYPOINT + ANTHROPIC_AUTH_TOKEN (prismscan 实际 env).
    Plugin mode 用户零配置, 由 Claude Code OAuth 自动注入 ANTHROPIC_AUTH_TOKEN.
    """
    from auto_engineering.utils.plugin_mode import detect_plugin_mode, has_llm_credentials
    if detect_plugin_mode():
        return True, "LLM 凭据 (Plugin mode 零配置, Claude Code OAuth 自动注入 ANTHROPIC_AUTH_TOKEN)"
    if has_llm_credentials():
        return True, "LLM 凭据已设置 (ANTHROPIC_API_KEY 或 ANTHROPIC_AUTH_TOKEN)"
    return False, "LLM 凭据未设置 — 请 export ANTHROPIC_API_KEY=sk-... 或在 .env 中设置"


def _check_openai_api_key() -> tuple[bool, str]:
    """检查 OpenAI API key (v8.0 多平台 Provider 抽象需要)."""
    from auto_engineering.config.runtime_config import get_default_config
    key = get_default_config().openai_api_key
    if key and key.startswith("sk-"):
        return True, "OPENAI_API_KEY 已设置 (OpenAI Provider 可用)"
    if key:
        return False, "OPENAI_API_KEY 格式异常 (应以 sk- 开头)"
    return False, "OPENAI_API_KEY 未设置 — OpenAI Provider 不可用 (Anthropic 仍可用)"


def _check_ae_state(project_root: Path) -> tuple[bool, str]:
    """检查 .ae-state/ 可读写 (诊断命令, 不自动创建目录)."""
    ae_state = project_root / ".ae-state"
    if not ae_state.exists():
        return False, ".ae-state/ 目录不存在 — 运行 ae dev-loop 初始化项目"
    # 测读写
    test_file = ae_state / ".doctor_write_test"
    try:
        test_file.write_text("ok")
        test_file.unlink()
        return True, ".ae-state/         可读写"
    except (PermissionError, OSError) as e:
        return False, f".ae-state/ 不可写: {e}"


def _check_plugin_mode() -> tuple[bool, str]:
    """检查 Plugin mode 是否启用 (Bug 4 修复, 2026-07-04).

    2026-07-04 深度设计 (用户洞察): Plugin mode 用户**零配置**原则.
    Plugin 在 Claude Code agent 内运行时, ANTHROPIC_AUTH_TOKEN 由 Claude Code
    通过 OAuth 自动注入, 用户不需要自己 export ANTHROPIC_API_KEY.
    """
    from auto_engineering.utils.plugin_mode import detect_plugin_mode_detail

    in_plugin, signal = detect_plugin_mode_detail()
    if in_plugin:
        # Plugin mode: 用户零配置, ANTHROPIC_AUTH_TOKEN 由 Claude Code OAuth 注入
        return True, (
            f"Plugin mode 已启用 (via {signal}) — 用户零配置, "
            f"ANTHROPIC_AUTH_TOKEN 由 Claude Code OAuth 自动注入"
        )
    # CLI 调试模式: 需要用户手动 export (独立跑 ae 才需要)
    return True, (
        "CLI 调试模式 (独立跑 ae) — 需手动 export ANTHROPIC_API_KEY. "
        "建议在 Claude Code agent 内运行 (Plugin 模式, 零配置)"
    )


def _check_init_manifest(project_root: Path) -> tuple[bool, str]:
    """检查 init-manifest.json (IL-AC-01~05, v5.0 §IL.4).

    校验流程:
        1. 文件不存在 → ✗ + 提示运行 Init (IL-AC-01)
        2. 调 init_contract.load_init_manifest 读取
        3. 调 init_contract.validate_init_manifest 校验
            - schema_version < 1.0 → ✗ (IL-AC-04)
            - schema_version > 9.9 → WARN (forward-compat)
            - 必需字段缺失 → ✗ (列字段名)
            - language/project_type 不在 enum → ✗ (列支持值)
            - 未知字段 → WARN (IL-AC-03, 静默忽略)
        4. 任一 ✗ → 整体 ✗, 拼接 messages
    """
    # 惰性 import 避免循环 (init_contract → 不依赖 cli, 但保险起见)
    from auto_engineering.loop.init_contract import (
        load_init_manifest,
        validate_init_manifest,
    )

    manifest = project_root / ".ae-state" / "init-manifest.json"
    # IL-AC-01: 文件缺失
    if not manifest.exists():
        return False, (
            "init-manifest.json 不存在 — 未找到 .ae-state/init-manifest.json, "
            "请先运行 Init Engineering 项目初始化"
        )
    # 调 init_contract 读取 (load 失败 → ✗)
    data = load_init_manifest(project_root)
    if data is None:
        return False, f"init-manifest.json 读取/解析失败: {manifest}"
    # 调 init_contract 校验
    result = validate_init_manifest(data)
    if not result.ok:
        # 拼接 errors
        joined = "; ".join(result.errors)
        return False, f"init-manifest.json 校验失败: {joined}"
    # 通过, 拼接 schema_version + warnings
    schema_version = data.get("schema_version", "?")
    warn_str = " [WARN: " + "; ".join(result.warnings) + "]" if result.warnings else ""
    return True, f"init-manifest.json 存在 (schema_version {schema_version}){warn_str}"


def _check_pr_backend() -> tuple[bool, str]:
    """检查 PR 后端可用性 (advisory, 不阻断预检).

    AD1: PRBackend 模块已删除 (零生产消费者)。改为直接检测 CLI 工具。
    """
    backends = []
    for tool in ("gh", "glab"):
        try:
            subprocess.run([tool, "--version"], capture_output=True, timeout=5, check=True)
            backends.append(tool)
        except (FileNotFoundError, subprocess.CalledProcessError, subprocess.TimeoutExpired):
            pass
    if backends:
        return True, f"PR CLI 工具可用: {', '.join(backends)}"
    return True, "PR CLI 工具: 无 (gh/glab 均未安装) — loop done 时提示手动创建 PR"


def run_doctor_checks(project_root: Path) -> tuple[int, list[tuple[bool, str]]]:
    """执行全部 doctor 检查, 返回 (exit_code, [(ok, line), ...])."""
    results: list[tuple[bool, str]] = []
    results.append(_check_python())
    results.append(_check_uv())
    results.append(_check_git())
    results.append(_check_sqlite3())
    results.append(_check_plugin_mode())
    results.append(_check_api_key())
    results.append(_check_openai_api_key())
    results.append(_check_ae_state(project_root))
    results.append(_check_init_manifest(project_root))
    results.append(_check_pr_backend())
    failed = sum(1 for ok, _ in results if not ok)
    return (1 if failed > 0 else 0), results


def render_optional_features() -> list[tuple[bool, str]]:
    """Render optional features panel from FeatureManifest SSOT (T114 5.2)."""
    from auto_engineering.config.feature_flags import FEATURE_MANIFEST, _count_requirements, get_feature_status
    status = get_feature_status()
    lines: list[tuple[bool, str]] = []

    # Phase 44 T212: ae.toml 状态
    from pathlib import Path as _Path
    toml_path = _Path.cwd() / "ae.toml"
    if toml_path.exists():
        toml_active = sum(1 for s in status.values() if s.get("active"))
        lines.append((True, f"ae.toml 已加载 ({toml_active}/{len(FEATURE_MANIFEST)} features active)"))
    else:
        lines.append((False, "ae.toml 未创建 — 运行 ae doctor --init-config 生成配置文件"))

    # 2026-07-25 审计修复 (P1-5): T206 合并遗留 — 此处原有简单版特性列表循环
    # + 需求计数块, 与下方 T206 增强版(含 OTLP 探测)完全重复, 面板输出两遍。
    # 删除前一组, 保留下方增强版。

    # T206: OTLP 连通性实时探测 — 区分三态
    _otlp_state = _check_otlp_connectivity()
    for f in FEATURE_MANIFEST:
        s = status[f.key]
        line = f"{f.description}"
        if f.key == "AE_OTLP_ENDPOINT":
            if _otlp_state == "connected":
                lines.append((True, f"{line} — collector 已连接 ({_otlp_status_text()})"))
            elif _otlp_state == "unreachable":
                lines.append((False, f"{line} — collector 不可达 ({_otlp_status_text()})"))
                lines.append((False, "  → 运行 ae doctor --setup-observability 启动 collector"))
            elif s["active"]:
                lines.append((True, line))
            else:
                lines.append((False, f"{line} — {f.activation}"))
            continue
        _mark = "✓" if s["active"] else "✗"
        mode_note = ""
        if s["agent_mode"] != "both" and s["active"]:
            mode_note = f" (仅 {s['agent_mode'].replace('_', ' ')} 模式生效)"
        line_full = f"{line}{mode_note}"
        if not s["active"]:
            line_full += f" — {f.activation}"
        lines.append((s["active"], line_full))

    # AD3: 需求计数可见性
    if status.get("AE_METRICS", {}).get("active"):
        req_count = _count_requirements()
        if req_count is not None:
            remaining = max(0, 30 - req_count)
            if req_count >= 30:
                lines.append((True, f"贝叶斯阈值学习: ✓ 已激活 ({req_count} 个需求)"))
            else:
                lines.append((False, f"贝叶斯阈值学习: 待激活 ({req_count}/30 需求, "
                                     f"还差 {remaining}) — ThresholdLearner"))

    return lines


def _check_otlp_connectivity() -> str:
    """检测 OTLP collector 连通性。

    Returns:
        "disabled" — AE_OTLP_ENDPOINT 未设置
        "unreachable" — 已设置但端口不可达
        "connected" — collector 可达
    """
    import os as _os
    endpoint = _os.environ.get("AE_OTLP_ENDPOINT", "").strip()
    if not endpoint:
        return "disabled"
    try:
        from urllib.parse import urlparse
        parsed = urlparse(endpoint)
        host = parsed.hostname or "localhost"
        port = parsed.port or 4317
        import socket
        with socket.create_connection((host, port), timeout=2):
            return "connected"
    except (TimeoutError, OSError, ValueError):
        return "unreachable"


def _otlp_status_text() -> str:
    import os as _os
    endpoint = _os.environ.get("AE_OTLP_ENDPOINT", "").strip()
    if not endpoint:
        return "AE_OTLP_ENDPOINT 未设置"
    from urllib.parse import urlparse
    parsed = urlparse(endpoint)
    host = parsed.hostname or "localhost"
    port = parsed.port or 4317
    return f"{host}:{port}"


def _setup_observability() -> None:
    """启动 observability 栈 (Jaeger container).

    Phase 43 T204: 检测 Docker → 检查 compose 文件 → docker compose up → 等待就绪。
    Docker 不可用时降级为手动指引，不报错退出。
    """
    import shutil
    import time
    from pathlib import Path as _Path

    # 1. 检测 Docker
    if shutil.which("docker") is None:
        click.echo("✗ Docker 未安装。请先安装 Docker Desktop:")
        click.echo("  https://docs.docker.com/desktop/")
        click.echo("  安装后运行: ae doctor --setup-observability")
        return

    # 2. 检查 collector 是否已在运行
    if _check_otlp_connectivity() == "connected":
        click.echo("✓ OTLP collector 已在运行")
        click.echo(f"  endpoint: {_otlp_status_text()}")
        click.echo("  Jaeger UI: http://localhost:16686")
        return

    # 3. 定位 compose 文件
    compose_file = _Path(__file__).parent.parent.parent / "docker-compose.observability.yml"
    if not compose_file.exists():
        click.echo(f"✗ 未找到 {compose_file}")
        click.echo("  请确认项目根目录存在 docker-compose.observability.yml")
        return

    # 4. 启动
    click.echo("→ 启动 Jaeger collector...")
    try:
        result = subprocess.run(
            ["docker", "compose", "-f", str(compose_file), "up", "-d"],
            capture_output=True, text=True, timeout=60,
        )
        if result.returncode != 0:
            click.echo(f"✗ docker compose 启动失败:\n{result.stderr}")
            return
    except (subprocess.TimeoutExpired, OSError) as e:
        click.echo(f"✗ docker compose 执行失败: {e}")
        return

    # 5. 等待就绪
    click.echo("  等待 collector 就绪", nl=False)
    for _ in range(30):
        if _check_otlp_connectivity() == "connected":
            click.echo("")
            click.echo("✓ Jaeger OTLP collector 已启动")
            click.echo(f"  gRPC endpoint: {_otlp_status_text()}")
            click.echo("  Jaeger UI: http://localhost:16686")
            click.echo("")
            click.echo(f"  现在设置 export AE_OTLP_ENDPOINT=http://{_otlp_status_text()} 即可启用 tracing")
            return
        time.sleep(1)
        click.echo(".", nl=False)

    click.echo("")
    click.echo("⚠ collector 启动超时 (30s)。请手动检查:")
    click.echo("  docker ps | grep ae-jaeger")
    click.echo(f"  docker compose -f {compose_file} logs")


def _teardown_observability() -> None:
    """停止 observability 栈。

    Phase 43 T205: docker compose down → 确认停止。
    """
    from pathlib import Path as _Path

    compose_file = _Path(__file__).parent.parent.parent / "docker-compose.observability.yml"
    if not compose_file.exists():
        click.echo("✗ docker-compose.observability.yml 不存在，无需清理")
        return

    click.echo("→ 停止 Jaeger collector...")
    try:
        result = subprocess.run(
            ["docker", "compose", "-f", str(compose_file), "down"],
            capture_output=True, text=True, timeout=30,
        )
        if result.returncode == 0:
            click.echo("✓ Observability 栈已停止")
        else:
            click.echo(f"✗ 停止失败:\n{result.stderr}")
    except (subprocess.TimeoutExpired, OSError) as e:
        click.echo(f"✗ docker compose 执行失败: {e}")


def _init_config(project_root: Path) -> None:
    """Generate ae.toml template from SECTION_KEY_MAP (与读取器同源).

    Phase 44 T211: 读取 FeatureManifest → 按 category 分组 → 生成 TOML 模板。
    2026-07-26 真跑修复: 模板 key 改为 kebab-case，从 AeConfig.SECTION_KEY_MAP
    派生（此前用 f.key 即 AE_UPPER，读取器只认 kebab-case → 模板不可用、开关假启用）。
    描述/默认值仍从 FEATURE_MANIFEST 按 AE_UPPER key 关联。
    """
    from auto_engineering.config.ae_config import SECTION_KEY_MAP
    from auto_engineering.config.feature_flags import FEATURE_MANIFEST

    toml_path = project_root / "ae.toml"
    if toml_path.exists():
        click.echo(f"ae.toml 已存在: {toml_path}")
        click.echo("如需重新生成，请先删除已有文件")
        return

    # AE_UPPER → (description, default_value)，用于注释说明
    flag_info = {f.key: (f.description, f.default_value) for f in FEATURE_MANIFEST}

    lines: list[str] = [
        "# Auto-Engineering 项目配置",
        "# 生成: ae doctor --init-config",
        "# 优先级: 环境变量 > ae.toml > 内置默认值",
        "# key 为 kebab-case（与读取器 AeConfig.SECTION_KEY_MAP 同源）；括号内为对应环境变量名",
        "# 编辑此文件取消注释所需功能，然后运行 /ae:dev-loop",
        "",
    ]

    count = 0
    for section, mapping in SECTION_KEY_MAP.items():
        lines.append(f"[{section}]")
        for toml_key, ae_key in mapping.items():
            desc, default = flag_info.get(ae_key, ("", ""))
            if default:
                lines.append(f"# {toml_key} = \"{default}\"  # {desc} ({ae_key})")
            else:
                lines.append(f"# {toml_key} = \"\"  # {desc} ({ae_key}) (无默认值)")
            count += 1
        lines.append("")

    toml_path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    click.echo(f"✓ ae.toml 已生成: {toml_path}")
    click.echo(f"  共 {count} 个功能开关，默认全部注释")
    click.echo("  编辑此文件取消注释所需功能，保存后生效")


def _run_wizard(project_root: Path) -> None:
    """Interactive configuration wizard (Phase 45 T213).

    Reads current ae.toml as defaults, guides user through category-level
    feature selection, saves to ae.toml.
    """

    from auto_engineering.config.feature_flags import FEATURE_MANIFEST

    # Load current values as defaults
    current: dict[str, str] = {}
    toml_path = project_root / "ae.toml"
    if toml_path.exists():
        try:
            from auto_engineering.config.ae_config import AeConfig
            ae = AeConfig(project_root)
            for f in FEATURE_MANIFEST:
                current[f.key] = ae.get(f.key)
        except (ImportError, ValueError, OSError):
            pass

    selected: dict[str, str] = {}
    cat_order = ["observability", "debugging", "safety", "performance", "threshold"]
    cat_names = {
        "observability": "可观测性", "debugging": "调试",
        "safety": "安全", "performance": "性能", "threshold": "阈值",
    }

    click.echo("")
    click.echo("═══ Auto-Engineering 配置向导 ═══")
    if toml_path.exists():
        click.echo("检测到 ae.toml，将在此基础上修改")
    click.echo("按 Ctrl+C 随时退出，修改不会保存")
    click.echo("")

    for cat in cat_order:
        features = [(f.key, f.description, f.default_value) for f in FEATURE_MANIFEST if f.category == cat]
        if not features:
            continue

        click.echo(f"── {cat_names.get(cat, cat)} ──")
        for key, desc, default in features:
            cur = current.get(key, default)
            marker = "✓" if cur and cur != "0" and cur != "" else "✗"
            click.echo(f"  [{marker}] {desc} (当前: {cur or '未设置'})")
        click.echo("")

        choice = click.prompt(
            "  全部启用? [y=全部启用 / N=全部跳过 / e=逐项选择]",
            default="N", show_default=False,
        ).strip().lower()

        if choice == "y":
            for key, _desc, _default in features:
                selected[key] = "1"
        elif choice == "e":
            for key, desc, default in features:
                cur = current.get(key, default)
                default_yn = "y" if (cur and cur != "0" and cur != "") else "n"
                yn = click.prompt(
                    f"    启用 {desc}? [y/N]", default=default_yn, show_default=False,
                ).strip().lower()
                if yn == "y":
                    selected[key] = cur if cur else "1"
                else:
                    selected[key] = "0"
        else:
            for key, _desc, _default in features:
                selected[key] = "0"

    # Preview
    click.echo("")
    click.echo("── 配置预览 ──")
    active_count = 0
    for f in FEATURE_MANIFEST:
        val = selected.get(f.key, "0")
        active = val and val != "0" and val != ""
        if active:
            active_count += 1
            click.echo(f"  ✓ {f.description}")
    click.echo(f"  {active_count}/{len(FEATURE_MANIFEST)} features active")
    click.echo("")

    save = click.confirm("保存到 ae.toml?", default=True)
    if not save:
        click.echo("已取消，未保存")
        return

    # Write ae.toml
    cat_feature_map: dict[str, list[tuple[str, str, str]]] = {}
    for f in FEATURE_MANIFEST:
        if f.category not in cat_feature_map:
            cat_feature_map[f.category] = []
        cat_feature_map[f.category].append((f.key, f.description, selected.get(f.key, "0")))

    lines = [
        "# Auto-Engineering 项目配置",
        f"# 生成: ae doctor --wizard ({active_count}/{len(FEATURE_MANIFEST)} features active)",
        "# 优先级: 环境变量 > ae.toml > 内置默认值",
        "",
    ]
    for cat in cat_order:
        if cat not in cat_feature_map:
            continue
        lines.append(f"[{cat}]")
        for key, desc, val in cat_feature_map[cat]:
            if val and val != "0":
                lines.append(f"{key} = \"{val}\"  # {desc}")
            else:
                lines.append(f"# {key} = \"\"  # {desc} (已禁用)")
        lines.append("")

    toml_path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    click.echo(f"✓ 配置已保存 ({active_count}/{len(FEATURE_MANIFEST)} features active)")
    click.echo("  现在运行 /ae:dev-loop 即可自动加载")


def register_doctor_command(main: click.Group) -> None:
    """向 main Click Group 注册 ae doctor 子命令."""

    @main.command()
    @click.option(
        "--project-root",
        type=click.Path(exists=True),
        default=None,
        help="项目根目录 (默认 cwd)",
    )
    @click.option(
        "--wizard",
        is_flag=True,
        help="Phase 45: 交互式配置向导",
    )
    @click.option(
        "--init-config",
        is_flag=True,
        help="Phase 44: 生成 ae.toml 配置文件模板",
    )
    @click.option(
        "--setup-observability",
        is_flag=True,
        help="Phase 43: 启动 observability 栈 (Jaeger collector)",
    )
    @click.option(
        "--teardown-observability",
        is_flag=True,
        help="Phase 43: 停止 observability 栈",
    )
    def doctor(
        project_root: str, wizard: bool, init_config: bool,
        setup_observability: bool, teardown_observability: bool,
    ) -> None:
        """环境预检 — Python/uv/git/sqlite3/.ae-state + init-manifest (IL-AC-01).

        --wizard: 交互式配置向导
        --init-config: 生成 ae.toml 配置文件模板
        --setup-observability: 一键启动 OTLP collector (Jaeger)
        --teardown-observability: 停止 OTLP collector
        """
        # Phase 45: 配置向导
        if wizard:
            root = Path(project_root).resolve() if project_root else Path.cwd()
            _run_wizard(root)
            return
        # Phase 44: 配置文件生成
        if init_config:
            root = Path(project_root).resolve() if project_root else Path.cwd()
            _init_config(root)
            return
        # Phase 43: 可观测性生命周期管理
        if setup_observability:
            _setup_observability()
            return
        if teardown_observability:
            _teardown_observability()
            return

        root = Path(project_root).resolve() if project_root else Path.cwd()
        exit_code, results = run_doctor_checks(root)
        for ok, line in results:
            mark = "✓" if ok else "✗"
            click.echo(f"{mark} {line}")

        # T114 5.2: Optional features panel
        click.echo("")
        click.echo("── Optional Features ──")
        for active, line in render_optional_features():
            mark = "✓" if active else "✗"
            click.echo(f"{mark} {line}")

        if exit_code != 0:
            raise SystemExit(exit_code)
