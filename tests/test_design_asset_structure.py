"""当前设计入口、双基线与历史摘要的结构契约。"""

from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).parents[1]


def test_current_design_entrypoints_are_compact_and_traceable() -> None:
    beacon = (ROOT / "design/BEACON.md").read_text(encoding="utf-8")
    tracker = (
        ROOT / "design/IMPLEMENTATION-TRACKER.md"
    ).read_text(encoding="utf-8")
    index = (ROOT / "design/INDEX.md").read_text(encoding="utf-8")

    assert len(beacon.splitlines()) <= 80
    assert len(tracker.splitlines()) <= 180
    for entrypoint in (
        "design/v5.8-Session-Decoupling-Design.md",
        "design/v5.8-Session-Decoupling-PLAN.md",
        "design/incidents/2026-07-29-claude-146-tick-long-run.md",
        "design/IMPLEMENTATION-TRACKER.md",
        "design/HISTORY.md",
    ):
        assert entrypoint in beacon
    assert "v5.6-Design-Loop.md" in index
    assert "v5.7-Protocol-Kernel-Design.md" in index
    assert "HISTORY.md" in tracker


def test_current_design_assets_exist() -> None:
    expected = (
        ROOT / "design/BEACON.md",
        ROOT / "design/v5.6-Design-Loop.md",
        ROOT / "design/v5.7-Protocol-Kernel-Design.md",
        ROOT / "design/v5.7-Protocol-Kernel-PLAN.md",
        ROOT / "design/IMPLEMENTATION-TRACKER.md",
        ROOT / "design/HISTORY.md",
    )

    for path in expected:
        assert path.is_file(), f"缺少当前设计资产: {path}"


def test_current_loop_design_keeps_authoritative_contracts() -> None:
    design = (
        ROOT / "design/v5.6-Design-Loop.md"
    ).read_text(encoding="utf-8")

    for contract in (
        "Tick 协议",
        "Host Adapter",
        "五层验证",
        "Init-Loop",
        "Release 验收",
    ):
        assert contract in design


def test_historical_protocol_docs_cannot_be_mistaken_for_current_runtime() -> None:
    v56 = (ROOT / "design/v5.6-Design-Loop.md").read_text(encoding="utf-8")
    v57 = (ROOT / "design/v5.7-Protocol-Kernel-Design.md").read_text(encoding="utf-8")
    index = (ROOT / "design/INDEX.md").read_text(encoding="utf-8")

    assert "非当前运行规范" in v56
    assert "非当前运行规范" in v57
    assert "当前已实现的协议与 CLI 基线" not in index
    assert "只使用 EventStore/Reducer" in v57
    assert "旧 checkpoint 模型不属于当前运行路径" in index


def test_current_audit_entry_uses_current_acceptance_and_tick_contract() -> None:
    audit = (ROOT / "commands/audit.md").read_text(encoding="utf-8")

    assert "design/v5.8-Real-Host-Acceptance-Runbook.md" in audit
    assert "docs/EARS-v5.0.md" not in audit
    assert "ae dev-loop --tick (" not in audit
    assert "禁止并行或全量扫描参考源码" in audit


def test_superseded_implementation_plans_are_explicitly_historical() -> None:
    for relative in (
        "design/v5.8-Protocol-Kernel-Convergence-PLAN.md",
        "design/v5.8-State-Reconciliation-PLAN.md",
        "design/v5.8-Real-Host-Closure-PLAN.md",
    ):
        text = (ROOT / relative).read_text(encoding="utf-8")
        assert "历史实施计划，仅供审计" in text
        assert "不得按" in text or "不得执行" in text


def test_scheme_a_current_recovery_section_excludes_retired_entrypoints() -> None:
    scheme_a = (
        ROOT / "design/v5.8-Scheme-A-Convergence-Plan.md"
    ).read_text(encoding="utf-8")
    current_recovery = scheme_a.split("### A005：", 1)[1].split(
        "### A006：", 1
    )[0]

    assert "只从同一 EventStore stream 恢复" in current_recovery
    assert "不提供 `--import-checkpoint`" in current_recovery
    for retired_entrypoint in (
        "checkpoint 只保留显式",
        "legacy façade",
    ):
        assert retired_entrypoint not in current_recovery
    assert "历史实施记录（仅审计，不是当前合同）" in scheme_a


def test_beacon_and_replaced_designs_cannot_reintroduce_old_runtime() -> None:
    beacon = (ROOT / "design/BEACON.md").read_text(encoding="utf-8")
    state_reconciliation = (
        ROOT / "design/v5.8-State-Reconciliation-Design.md"
    ).read_text(encoding="utf-8")
    session_decoupling = (
        ROOT / "design/v5.8-Session-Decoupling-Design.md"
    ).read_text(encoding="utf-8")
    action_scoped = (
        ROOT / "design/v5.8-Action-Scoped-Host-Context-Spec.md"
    ).read_text(encoding="utf-8")

    assert "v5.8.0-rc.5 是当前发布候选" in beacon
    assert "D78" in beacon
    assert "旧 Supervisor" in beacon
    assert "旧 Gate/Task 别名" in beacon

    assert "（历史）" in state_reconciliation.splitlines()[0]
    assert "旧 checkpoint 文件不参与读取、恢复、导入或事实拼接" in state_reconciliation
    assert "（历史）" in session_decoupling.splitlines()[0]
    assert "旧 checkpoint、迁移 façade 和第二套恢复入口不得参与当前运行" in session_decoupling
    assert "当前状态：历史方案" in action_scoped
    assert "不得恢复 Action-scoped Python Supervisor" in action_scoped


def test_user_guide_does_not_reintroduce_init_runtime_dependency() -> None:
    guide = (ROOT / "docs/USER_GUIDE.md").read_text(encoding="utf-8")

    assert "不强制依赖 Init Engineering" in guide
    assert "缺少 Init manifest 误报成安装失败" in guide

    for relative in ("AGENTS.md", "CLAUDE.md"):
        generated = (ROOT / relative).read_text(encoding="utf-8")
        assert "默认使用本地 ProjectProfile 探测" in generated
        assert "运行时不强制依赖 Init 实现" in generated
