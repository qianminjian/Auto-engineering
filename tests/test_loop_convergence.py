"""v2.0 Phase 02 测试 — 4 级收敛判定 + SQLite Checkpoint 持久化.

设计来源:
    - design/v2.0-Analysis-Loop.md §4.7 (4 级收敛判定)
    - design/v2.0-Analysis-Loop.md §4.4 + §五 Phase 1.2 (Checkpoint 持久化)

测试覆盖:
    A. ConvergenceJudge 4 级判定 (≥4 用例)
    B. 停滞检测算法 (≥2 用例)
    C. Checkpoint save/load/list (≥3 用例)
    D. Checkpoint 事务 (并发 save 互不干扰, ≥1 用例)
    E. Schema 版本兼容性 (≥1 用例)
    合计: ≥10 用例

测试约束 (遵循 pytest-memory-management.md):
    - 单文件 pytest --no-cov --timeout=60
    - 用 :memory: SQLite 避免磁盘 IO
    - 跑完清理 .pytest_cache
"""

from __future__ import annotations

import sqlite3
import threading

import pytest

from auto_engineering.loop.checkpoint import (
    DB_SCHEMA_VERSION,
    CheckpointMeta,
    CheckpointNotFoundError,
    CheckpointSchemaMismatchError,
    SQLiteCheckpointStore,
)
from auto_engineering.loop.convergence import (
    DEFAULT_STAGNATION_DIFF_RATIO,
    LEVEL_CONTINUE,
    LEVEL_HARD_LIMIT,
    LEVEL_QUALITY,
    LEVEL_SEMANTIC,
    LEVEL_STAGNANT,
    ConvergenceConfig,
    ConvergenceJudge,
    RoundHistory,
    ConvergenceVerdict,
    detect_stagnation,
    diff_ratio,
)
from auto_engineering.loop.state import CheckpointEnvelope  # v2.3 P0-A 重命名 (原 LoopState, v2.0 Pydantic Checkpoint 数据信封)

# ============================================================
# Fixtures
# ============================================================


@pytest.fixture
def store() -> SQLiteCheckpointStore:
    """内存 SQLite store (测试隔离)."""
    return SQLiteCheckpointStore(":memory:")


@pytest.fixture
def default_config() -> ConvergenceConfig:
    """默认收敛配置."""
    return ConvergenceConfig()


@pytest.fixture
def make_history():
    """便捷构造 RoundHistory 列表的工厂函数."""

    def _make(
        round_ids: list[int],
        files: list[int] | None = None,
        added: list[int] | None = None,
        removed: list[int] | None = None,
        semantic: list[bool | None] | None = None,
        gates: list[dict[str, bool] | None] | None = None,
    ) -> list[RoundHistory]:
        n = len(round_ids)
        files = files or [0] * n
        added = added or [0] * n
        removed = removed or [0] * n
        semantic = semantic or [None] * n
        gates = gates or [None] * n
        return [
            RoundHistory(
                round_id=round_ids[i],
                files_changed=files[i],
                lines_added=added[i],
                lines_removed=removed[i],
                semantic_satisfied=semantic[i],
                gate_results=gates[i] or {},
            )
            for i in range(n)
        ]

    return _make


# ============================================================
# A. ConvergenceJudge 4 级判定
# ============================================================


def test_convergence_empty_history_continues(
    default_config: ConvergenceConfig,
) -> None:
    """空历史: 默认继续."""
    judge = ConvergenceJudge(default_config)
    verdict = judge.evaluate(history=[])
    assert verdict.should_stop is False
    assert verdict.level == LEVEL_CONTINUE
    assert "继续" in verdict.reason


def test_convergence_hard_limit_triggers_first(
    default_config: ConvergenceConfig,
) -> None:
    """硬上限 (level=4): 优先级最高, 即使其他条件也满足也返回硬上限."""
    history = [
        RoundHistory(
            round_id=10,
            gate_results={"g1": True, "g2": True},  # 质量门也满足
            semantic_satisfied=True,  # 语义也满足
        ),
    ]
    judge = ConvergenceJudge(default_config)  # max_iterations=10
    verdict = judge.evaluate(history=history)
    assert verdict.should_stop is True
    assert verdict.level == LEVEL_HARD_LIMIT
    assert "10" in verdict.reason  # max_iterations


def test_convergence_quality_gate_all_passed() -> None:
    """质量门 (level=3): 7 道 Gate 全 PASS → 停止."""
    from auto_engineering.gates.base import GateVerdict

    history = [
        RoundHistory(round_id=1),
        RoundHistory(
            round_id=2,
            gate_results={
                f"gate_{i}": GateVerdict.ok(f"ok-{i}", gate_name=f"gate_{i}")
                for i in range(7)
            },  # 7 道全过
        ),
    ]
    judge = ConvergenceJudge(ConvergenceConfig(max_iterations=10))
    verdict = judge.evaluate(history=history)
    assert verdict.should_stop is True
    assert verdict.level == LEVEL_QUALITY


def test_convergence_quality_gate_partial_returns_continue() -> None:
    """2026-07-05 对标审计 P0-1: gate 失败 → CONTINUE, 不 STOP.

    参考 LangGraph: gate 失败是诊断信号, 不是收敛条件.
    之前错误: gate 失败也返回 STOP(level=3), 将"质量不达标"混同"质量达标".
    orchestrator step 2i 被迫用反向补丁覆盖 judge 判定.
    """
    from auto_engineering.gates.base import GateVerdict

    history = [
        RoundHistory(
            round_id=1,
            gate_results={
                "g1": GateVerdict.ok("ok", gate_name="g1"),
                "g2": GateVerdict.failed("boom", gate_name="g2"),
                "g3": GateVerdict.ok("ok", gate_name="g3"),
            },
        ),
    ]
    judge = ConvergenceJudge(ConvergenceConfig(max_iterations=10))
    verdict = judge.evaluate(history=history)
    assert verdict.should_stop is False
    assert verdict.level == LEVEL_CONTINUE


def test_convergence_judge_quality_gate_failure_continues() -> None:
    """2026-07-05 对标审计 P0-1: 单 gate 失败 → CONTINUE."""
    from auto_engineering.gates.base import GateVerdict

    history = [
        RoundHistory(
            round_id=1,
            gate_results={
                "fake_failing": GateVerdict.failed(
                    "intentional failure for test", gate_name="fake_failing"
                ),
            },
        ),
    ]
    judge = ConvergenceJudge(ConvergenceConfig(max_iterations=10))
    verdict = judge.evaluate(history=history)
    assert verdict.should_stop is False
    assert verdict.level == LEVEL_CONTINUE


def test_convergence_judge_quality_gate_failure_falls_through_to_stagnation() -> None:
    """2026-07-05 对标审计 P0-1: gate 失败 → 继续检查停滞.

    之前错误: gate 失败返回 QUALITY STOP, 阻止了停滞检测.
    参考 LangGraph: gate 失败后, judge 继续检查下一级 (停滞/语义).
    """
    from auto_engineering.gates.base import GateVerdict

    # 连续 3 轮 files_changed=0 (触发停滞) + 最新一轮 gate 失败
    history = [
        RoundHistory(round_id=i, files_changed=0, lines_added=0, lines_removed=0)
        for i in range(1, 4)
    ] + [
        RoundHistory(
            round_id=4,
            files_changed=0,
            gate_results={
                "fail_gate": GateVerdict.failed("not passed", gate_name="fail_gate"),
            },
        ),
    ]
    judge = ConvergenceJudge(ConvergenceConfig(max_iterations=10))
    verdict = judge.evaluate(history=history)
    # gate 失败 → 回退到停滞检测 → STAGNANT
    assert verdict.level == LEVEL_STAGNANT
    assert verdict.should_stop is True


def test_convergence_quality_gate_multiple_failed_continues() -> None:
    """2026-07-05 对标审计 P0-1: 多道 gate 失败 → CONTINUE."""
    from auto_engineering.gates.base import GateVerdict

    history = [
        RoundHistory(
            round_id=1,
            gate_results={
                "g1": GateVerdict.failed("err-1", gate_name="g1"),
                "g2": GateVerdict.failed("err-2", gate_name="g2"),
                "g3": GateVerdict.failed("err-3", gate_name="g3"),
                "g4": GateVerdict.failed("err-4", gate_name="g4"),
            },
        ),
    ]
    judge = ConvergenceJudge(ConvergenceConfig(max_iterations=10))
    verdict = judge.evaluate(history=history)
    assert verdict.should_stop is False
    assert verdict.level == LEVEL_CONTINUE


def test_convergence_semantic_satisfied_stops() -> None:
    """语义收敛 (level=1): LLM 评估 semantic_satisfied=True → 停止."""
    history = [
        RoundHistory(round_id=1),
        RoundHistory(round_id=2, semantic_satisfied=True),
    ]
    judge = ConvergenceJudge(ConvergenceConfig(max_iterations=10))
    verdict = judge.evaluate(history=history)
    assert verdict.should_stop is True
    assert verdict.level == LEVEL_SEMANTIC
    assert "LLM" in verdict.reason


def test_convergence_priority_hard_limit_beats_quality() -> None:
    """优先级: 硬上限 (4) > 质量门 (3). 同时满足时返回硬上限."""
    from auto_engineering.gates.base import GateVerdict

    history = [
        RoundHistory(
            round_id=10,  # = max_iterations
            gate_results={"g1": GateVerdict.ok("ok", gate_name="g1")},
            semantic_satisfied=True,
        ),
    ]
    judge = ConvergenceJudge(ConvergenceConfig(max_iterations=10))
    verdict = judge.evaluate(history=history)
    assert verdict.level == LEVEL_HARD_LIMIT  # 不是 QUALITY


def test_convergence_priority_quality_beats_stagnant() -> None:
    """优先级: 质量门 (3) > 停滞检测 (2). 同时满足时返回质量门."""
    from auto_engineering.gates.base import GateVerdict

    # 连续 3 轮无变化 (触发停滞), 同时最新一轮所有 gate 通过 (触发质量门)
    history = [
        RoundHistory(round_id=1, files_changed=5),
        RoundHistory(round_id=2, files_changed=5),  # 无变化
        RoundHistory(round_id=3, files_changed=5),  # 无变化
        RoundHistory(
            round_id=4,
            files_changed=5,  # 无变化
            gate_results={
                "g1": GateVerdict.ok("ok", gate_name="g1"),
                "g2": GateVerdict.ok("ok", gate_name="g2"),
            },  # 全过
        ),
    ]
    judge = ConvergenceJudge(ConvergenceConfig(max_iterations=10))
    verdict = judge.evaluate(history=history)
    assert verdict.level == LEVEL_QUALITY  # 优先级更高


def test_verdict_continue_factory() -> None:
    """ConvergenceVerdict.continue_() 工厂."""
    v = ConvergenceVerdict.continue_()
    assert v.should_stop is False
    assert v.level == LEVEL_CONTINUE


def test_verdict_stop_validates_level() -> None:
    """ConvergenceVerdict.stop() 拒绝非法 level."""
    with pytest.raises(ValueError):
        ConvergenceVerdict.stop(level=99, reason="invalid")
    # 合法 level 不报错
    v = ConvergenceVerdict.stop(level=LEVEL_HARD_LIMIT, reason="test")
    assert v.should_stop is True
    assert v.level_name == "MAX_ITERATIONS"


# ============================================================
# B. 停滞检测算法
# ============================================================


def test_diff_ratio_identical_returns_zero() -> None:
    """diff_ratio: 两轮完全相同 → 0.0."""
    h1 = RoundHistory(round_id=1, files_changed=5, lines_added=10, lines_removed=3)
    h2 = RoundHistory(round_id=2, files_changed=5, lines_added=10, lines_removed=3)
    assert diff_ratio(h2, h1) == 0.0


def test_diff_ratio_both_zero_returns_zero() -> None:
    """diff_ratio: 两轮都为 0 → 0.0 (边界)."""
    h1 = RoundHistory(round_id=1)
    h2 = RoundHistory(round_id=2)
    assert diff_ratio(h2, h1) == 0.0


def test_diff_ratio_one_zero_returns_one() -> None:
    """diff_ratio: 一方为 0, 一方非 0 → 1.0 (相对变化无穷大)."""
    h_empty = RoundHistory(round_id=1)
    h_full = RoundHistory(round_id=2, files_changed=10)
    assert diff_ratio(h_full, h_empty) == 1.0
    assert diff_ratio(h_empty, h_full) == 1.0


def test_diff_ratio_partial_change() -> None:
    """diff_ratio: 部分变化."""
    # curr=10, prev=5, |10-5|/max(10,5) = 5/10 = 0.5
    h_prev = RoundHistory(round_id=1, files_changed=5)
    h_curr = RoundHistory(round_id=2, files_changed=10)
    assert diff_ratio(h_curr, h_prev) == pytest.approx(0.5)


def test_detect_stagnation_triggers_when_no_change_for_n_rounds() -> None:
    """detect_stagnation: 连续 N 轮无变化 → True."""
    # 4 轮, 全部 files_changed=5 (无变化)
    history = [
        RoundHistory(round_id=i, files_changed=5, lines_added=10, lines_removed=2)
        for i in range(1, 5)
    ]
    # threshold=2 表示连续 2 轮无变化
    stagnant = detect_stagnation(
        history, threshold=2, diff_ratio_threshold=DEFAULT_STAGNATION_DIFF_RATIO
    )
    assert stagnant is True


def test_detect_stagnation_no_trigger_when_change_occurs() -> None:
    """detect_stagnation: 出现变化 → 不触发."""
    history = [
        RoundHistory(round_id=1, files_changed=5),
        RoundHistory(round_id=2, files_changed=5),  # 无变化
        RoundHistory(round_id=3, files_changed=100),  # 大变化 → 重置
        RoundHistory(round_id=4, files_changed=5),  # 无变化 (但不到 N)
    ]
    # threshold=2 需要连续 2 轮无变化
    stagnant = detect_stagnation(
        history, threshold=2, diff_ratio_threshold=DEFAULT_STAGNATION_DIFF_RATIO
    )
    assert stagnant is False


def test_detect_stagnation_insufficient_history() -> None:
    """detect_stagnation: 历史不足 → 不触发."""
    history = [RoundHistory(round_id=1, files_changed=5)]
    stagnant = detect_stagnation(history, threshold=2, diff_ratio_threshold=0.05)
    assert stagnant is False


def test_stagnation_triggers_via_judge(make_history) -> None:
    """ConvergenceJudge: 停滞检测 (level=2) 端到端."""
    # 连续 3 轮 files_changed=5 (无变化), threshold=2 → 触发
    history = make_history(
        round_ids=[1, 2, 3],
        files=[5, 5, 5],
        added=[10, 10, 10],
        removed=[2, 2, 2],
    )
    judge = ConvergenceJudge(ConvergenceConfig(max_iterations=10, stagnation_threshold=2))
    verdict = judge.evaluate(history=history)
    assert verdict.should_stop is True
    assert verdict.level == LEVEL_STAGNANT


# ============================================================
# B+. v5.5 ConvergenceConfig 扩展字段
# ============================================================


class TestConvergenceConfigV55:
    """v5.5 Phase 2: ConvergenceConfig 新字段 (auto_tune, max_plan_refines,
    min_samples_for_learning)."""

    def test_default_auto_tune_is_false(self) -> None:
        """auto_tune 默认 False (向后兼容)."""
        config = ConvergenceConfig()
        assert config.auto_tune is False

    def test_default_max_plan_refines_is_three(self) -> None:
        """max_plan_refines 默认 3."""
        config = ConvergenceConfig()
        assert config.max_plan_refines == 3

    def test_default_min_samples_for_learning_is_five(self) -> None:
        """min_samples_for_learning 默认 5 (冷启动最小样本)."""
        config = ConvergenceConfig()
        assert config.min_samples_for_learning == 5

    def test_auto_tune_can_be_enabled(self) -> None:
        """auto_tune 可显式启用."""
        config = ConvergenceConfig(auto_tune=True)
        assert config.auto_tune is True

    def test_max_plan_refines_custom_value(self) -> None:
        """max_plan_refines 可自定义."""
        config = ConvergenceConfig(max_plan_refines=5)
        assert config.max_plan_refines == 5

    def test_min_samples_for_learning_custom_value(self) -> None:
        """min_samples_for_learning 可自定义."""
        config = ConvergenceConfig(min_samples_for_learning=10)
        assert config.min_samples_for_learning == 10

    def test_backward_compatible_with_judge(self) -> None:
        """ConvergenceJudge 接受 v5.5 扩展字段."""
        config = ConvergenceConfig(
            max_iterations=10,
            auto_tune=True,
            max_plan_refines=4,
            min_samples_for_learning=7,
        )
        judge = ConvergenceJudge(config=config)
        assert judge.config.max_iterations == 10
        assert judge.config.auto_tune is True
        assert judge.config.max_plan_refines == 4
        assert judge.config.min_samples_for_learning == 7

    def test_backward_compatible_old_constructor(self) -> None:
        """旧构造方式仍有效 (不传 v5.5 字段)."""
        config = ConvergenceConfig(max_iterations=10, stagnation_threshold=2)
        assert config.max_iterations == 10
        assert config.stagnation_threshold == 2
        # v5.5 默认值
        assert config.auto_tune is False
        assert config.max_plan_refines == 3
        assert config.min_samples_for_learning == 5


# ============================================================
# B++. v5.5 ConvergenceJudge auto_tune + 冷启动
# ============================================================


class TestConvergenceJudgeV55AutoTune:
    """v5.5 Task 4.3: ConvergenceJudge.auto_tune_max_iter + 冷启动."""

    def test_auto_tune_max_iter_cold_start_returns_none(self, tmp_path) -> None:
        """冷启动 (样本不足) 返回 None, 表示使用默认 max_iter."""
        from pathlib import Path

        from auto_engineering.loop.audit_history import AuditHistory

        root = Path(tmp_path)
        history = AuditHistory(project_root=root)
        # 只写 3 条 (不足 MIN_SAMPLES=5)
        for _ in range(3):
            history.append_entry(p0=0, p1=2, p2=0, threshold=6,
                                 total_files=50, plan_refine_triggered=False)

        judge = ConvergenceJudge(ConvergenceConfig(auto_tune=True))
        result = judge.auto_tune_max_iter(audit_history=history)
        assert result is None, "冷启动应返回 None"

    def test_auto_tune_max_iter_sufficient_samples_returns_int(self, tmp_path) -> None:
        """足够样本后返回计算值 (min(avg_rounds*2, 20))."""
        from pathlib import Path

        from auto_engineering.loop.audit_history import AuditHistory

        root = Path(tmp_path)
        history = AuditHistory(project_root=root)
        # 写 8 条 (足够 MIN_SAMPLES=5), entries without rounds → defaults=1
        for _ in range(8):
            history.append_entry(p0=0, p1=2, p2=0, threshold=6,
                                 total_files=50, plan_refine_triggered=False)
        # With defaults (rounds=1): avg=1, max_iter=min(2,20)=2

        judge = ConvergenceJudge(ConvergenceConfig(auto_tune=True))
        result = judge.auto_tune_max_iter(audit_history=history)
        assert result is not None
        assert result == 2

    def test_auto_tune_max_iter_empty_history_returns_none(self, tmp_path) -> None:
        """空历史返回 None."""
        from pathlib import Path

        from auto_engineering.loop.audit_history import AuditHistory

        root = Path(tmp_path)
        history = AuditHistory(project_root=root)

        judge = ConvergenceJudge(ConvergenceConfig(auto_tune=True))
        result = judge.auto_tune_max_iter(audit_history=history)
        assert result is None

    def test_auto_tune_max_iter_uses_judge_config_min_samples(self, tmp_path) -> None:
        """使用 judge.config.min_samples_for_learning 而非 ThresholdLearner.MIN_SAMPLES."""
        from pathlib import Path

        from auto_engineering.loop.audit_history import AuditHistory

        root = Path(tmp_path)
        history = AuditHistory(project_root=root)
        # 写 6 条, 自定义 min_samples_for_learning=10 → 冷启动
        for _ in range(6):
            history.append_entry(p0=0, p1=2, p2=0, threshold=6,
                                 total_files=50, plan_refine_triggered=False)

        judge = ConvergenceJudge(ConvergenceConfig(
            auto_tune=True, min_samples_for_learning=10,
        ))
        result = judge.auto_tune_max_iter(audit_history=history)
        assert result is None, "自定义 min_samples=10, 6 条应不足"


# ============================================================
# C. Checkpoint save/load/list
# ============================================================


def test_checkpoint_save_returns_id(store: SQLiteCheckpointStore) -> None:
    """save() 返回 checkpoint_id (UUID 字符串)."""
    state = CheckpointEnvelope()
    cp_id = store.save(state, round=1)
    assert isinstance(cp_id, str)
    assert len(cp_id) > 0


def test_checkpoint_save_and_load(store: SQLiteCheckpointStore) -> None:
    """save() → load() 往返一致."""
    state = CheckpointEnvelope()
    cp_id = store.save(state, round=3, step=2)
    loaded = store.load(cp_id)
    assert loaded.id == cp_id
    assert loaded.round == 3
    assert loaded.step == 2


def test_checkpoint_load_not_found_raises(store: SQLiteCheckpointStore) -> None:
    """load() 不存在的 ID → CheckpointNotFoundError."""
    with pytest.raises(CheckpointNotFoundError):
        store.load("nonexistent-id")


def test_checkpoint_load_latest(store: SQLiteCheckpointStore) -> None:
    """load_latest() 返回 round 最大的 Checkpoint."""
    state = CheckpointEnvelope()
    store.save(state, round=1)
    store.save(state, round=3)
    store.save(state, round=2)
    latest = store.load_latest()
    assert latest is not None
    assert latest.round == 3


def test_checkpoint_load_latest_empty_returns_none(
    store: SQLiteCheckpointStore,
) -> None:
    """load_latest() 空库 → None."""
    assert store.load_latest() is None


def test_checkpoint_load_by_round(store: SQLiteCheckpointStore) -> None:
    """load_by_round() 按轮次查询."""
    state = CheckpointEnvelope()
    store.save(state, round=1)
    store.save(state, round=2, step=5)
    cp = store.load_by_round(round=2)
    assert cp is not None
    assert cp.round == 2
    assert cp.step == 5


def test_checkpoint_load_by_round_not_found(store: SQLiteCheckpointStore) -> None:
    """load_by_round() 不存在的轮次 → None."""
    state = CheckpointEnvelope()
    store.save(state, round=1)
    assert store.load_by_round(round=99) is None


def test_checkpoint_list_all_returns_sorted(
    store: SQLiteCheckpointStore,
) -> None:
    """list_all() 按 round ASC 排序."""
    state = CheckpointEnvelope()
    store.save(state, round=3)
    store.save(state, round=1)
    store.save(state, round=2)
    all_meta = store.list_all()
    assert len(all_meta) == 3
    assert [m.round for m in all_meta] == [1, 2, 3]


def test_checkpoint_list_empty(store: SQLiteCheckpointStore) -> None:
    """list_all() 空库 → 空列表."""
    assert store.list_all() == []


def test_checkpoint_count(store: SQLiteCheckpointStore) -> None:
    """count() 返回总 Checkpoint 数."""
    state = CheckpointEnvelope()
    assert store.count() == 0
    store.save(state, round=1)
    store.save(state, round=2)
    assert store.count() == 2


def test_checkpoint_delete(store: SQLiteCheckpointStore) -> None:
    """delete() 删除指定 ID."""
    state = CheckpointEnvelope()
    cp_id = store.save(state, round=1)
    assert store.delete(cp_id) is True
    assert store.count() == 0
    # 再次删除 → False
    assert store.delete(cp_id) is False


def test_checkpoint_clear(store: SQLiteCheckpointStore) -> None:
    """clear() 清空所有 Checkpoint."""
    state = CheckpointEnvelope()
    store.save(state, round=1)
    store.save(state, round=2)
    store.clear()
    assert store.count() == 0


def test_checkpoint_with_history(store: SQLiteCheckpointStore) -> None:
    """save() 带 history → load() 可还原."""
    state = CheckpointEnvelope()
    history = [
        RoundHistory(round_id=1, files_changed=5),
        RoundHistory(round_id=2, files_changed=10),
    ]
    cp_id = store.save(state, round=2, history=history)
    loaded = store.load(cp_id)
    assert len(loaded.history) == 2
    assert loaded.history[0]["files_changed"] == 5
    assert loaded.history[1]["files_changed"] == 10


def test_checkpoint_with_parent_and_tag(store: SQLiteCheckpointStore) -> None:
    """save() 支持 parent_id 和 tag."""
    state = CheckpointEnvelope()
    parent_id = store.save(state, round=1)
    cp_id = store.save(state, round=2, parent_id=parent_id, tag="v1.0-milestone")
    loaded = store.load(cp_id)
    assert loaded.parent_id == parent_id
    assert loaded.tag == "v1.0-milestone"


def test_checkpoint_explicit_id(store: SQLiteCheckpointStore) -> None:
    """save() 支持显式指定 checkpoint_id."""
    state = CheckpointEnvelope()
    store.save(state, round=1, checkpoint_id="my-custom-id-001")
    loaded = store.load("my-custom-id-001")
    assert loaded.id == "my-custom-id-001"


def test_checkpoint_meta_is_lightweight(store: SQLiteCheckpointStore) -> None:
    """CheckpointMeta 不含 state/history (仅元数据)."""
    state = CheckpointEnvelope()
    store.save(state, round=1)
    meta = store.list_all()[0]
    assert isinstance(meta, CheckpointMeta)
    assert not hasattr(meta, "state") or getattr(meta, "state", None) is None
    assert not hasattr(meta, "history") or getattr(meta, "history", None) is None


# ============================================================
# D. Checkpoint 事务 (并发 save 互不干扰)
# ============================================================


def test_checkpoint_concurrent_saves_isolated(tmp_path) -> None:
    """并发 save (10 线程 × 10 次): 全部成功, 无丢失."""
    db_path = tmp_path / "concurrent.db"
    store = SQLiteCheckpointStore(db_path)

    errors: list[Exception] = []
    saved_ids: list[str] = []

    def save_worker(thread_id: int) -> None:
        try:
            for i in range(10):
                cp_id = store.save(CheckpointEnvelope(), round=thread_id * 10 + i)
                saved_ids.append(cp_id)
        except Exception as e:
            errors.append(e)

    threads = [threading.Thread(target=save_worker, args=(t,)) for t in range(10)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()

    assert len(errors) == 0
    assert len(saved_ids) == 100
    assert store.count() == 100


def test_checkpoint_transaction_atomicity(tmp_path) -> None:
    """save 失败时事务回滚: 计数不变."""
    db_path = tmp_path / "atomic.db"
    store = SQLiteCheckpointStore(db_path)

    # 初始状态
    store.save(CheckpointEnvelope(), round=1)
    assert store.count() == 1

    # 制造一个失败: 模拟 schema_version 冲突 (插入重复主键)
    # 用直接 SQL 插入一个 ID, 然后 save 时用相同 ID 触发主键冲突
    state = CheckpointEnvelope()
    cp_id = store.save(state, round=2)
    assert store.count() == 2

    # 再次 save 相同 ID 应抛 IntegrityError, 事务回滚
    with pytest.raises(sqlite3.IntegrityError):
        store.save(state, round=3, checkpoint_id=cp_id)

    # 失败后 count 应仍为 2 (事务回滚)
    assert store.count() == 2


# ============================================================
# E. Schema 版本兼容性
# ============================================================


def test_checkpoint_schema_version_recorded(store: SQLiteCheckpointStore) -> None:
    """save() 记录的 schema_version 等于当前 DB_SCHEMA_VERSION."""
    state = CheckpointEnvelope()
    cp_id = store.save(state, round=1)
    loaded = store.load(cp_id)
    assert loaded.schema_version == DB_SCHEMA_VERSION


def test_checkpoint_schema_mismatch_raises(tmp_path) -> None:
    """手动写入旧 schema_version → load 抛 CheckpointSchemaMismatchError."""
    db_path = tmp_path / "schema_test.db"
    store = SQLiteCheckpointStore(db_path)

    # 用 store 正常建表
    cp_id = store.save(CheckpointEnvelope(), round=1)

    # 手动修改 schema_version 为旧版本
    conn = sqlite3.connect(str(db_path))
    conn.execute(
        "UPDATE checkpoints SET schema_version = ? WHERE id = ?",
        (DB_SCHEMA_VERSION - 1, cp_id),
    )
    conn.commit()
    conn.close()

    # load 应抛 SchemaMismatch
    with pytest.raises(CheckpointSchemaMismatchError) as exc_info:
        store.load(cp_id)
    assert exc_info.value.found == DB_SCHEMA_VERSION - 1
    assert exc_info.value.expected == DB_SCHEMA_VERSION


def test_checkpoint_schema_mismatch_latest_raises(tmp_path) -> None:
    """load_latest 也校验 schema."""
    db_path = tmp_path / "schema_latest.db"
    store = SQLiteCheckpointStore(db_path)

    cp_id = store.save(CheckpointEnvelope(), round=1)
    conn = sqlite3.connect(str(db_path))
    conn.execute(
        "UPDATE checkpoints SET schema_version = 999 WHERE id = ?", (cp_id,)
    )
    conn.commit()
    conn.close()

    with pytest.raises(CheckpointSchemaMismatchError):
        store.load_latest()


# ============================================================
# 集成: ConvergenceJudge + Checkpoint (端到端)
# ============================================================


def test_end_to_end_save_checkpoint_with_convergence_verdict(
    store: SQLiteCheckpointStore,
) -> None:
    """端到端: history 序列 → 判定 verdict → 保存为 checkpoint → 重新加载判定."""
    # 阶段 1: 运行 3 轮, 触发停滞
    history = [
        RoundHistory(round_id=1, files_changed=5, lines_added=10, lines_removed=2),
        RoundHistory(round_id=2, files_changed=5, lines_added=10, lines_removed=2),
        RoundHistory(round_id=3, files_changed=5, lines_added=10, lines_removed=2),
    ]
    judge = ConvergenceJudge(ConvergenceConfig(max_iterations=10, stagnation_threshold=2))
    verdict_before = judge.evaluate(history=history)
    assert verdict_before.should_stop is True
    assert verdict_before.level == LEVEL_STAGNANT

    # 阶段 2: 保存为 checkpoint
    cp_id = store.save(state=CheckpointEnvelope(), round=3, history=history)
    assert cp_id is not None

    # 阶段 3: 重新加载, 用同一 judge 判定
    loaded = store.load(cp_id)
    history_reloaded = [
        RoundHistory(**h) for h in loaded.history
    ]
    verdict_after = judge.evaluate(history=history_reloaded)
    assert verdict_after.level == LEVEL_STAGNANT
    assert verdict_after.reason == verdict_before.reason


# ============================================================
# G. Phase 2.3-D: RoundHistory 保留 Verdict.message (P0.4)
# ============================================================


def test_round_history_gate_results_contains_verdict() -> None:
    """RoundHistory.gate_results[name] 应为 Verdict 实例 (P0.4).

    之前 gate_results 被降级为 dict[str, bool], 丢失 verdict.message 语义.
    现在应保留完整 Verdict (含 gate_name/passed/message).
    """
    from auto_engineering.gates.base import GateVerdict

    history = RoundHistory(
        round_id=1,
        gate_results={
            "safety": GateVerdict.ok("ok", gate_name="safety"),
            "lint": GateVerdict.failed("syntax error at line 3", gate_name="lint"),
        },
    )
    # 关键: 每个 value 都是 Verdict, 不是 bool
    assert isinstance(history.gate_results["safety"], GateVerdict)
    assert isinstance(history.gate_results["lint"], GateVerdict)
    assert history.gate_results["safety"].passed is True
    assert history.gate_results["safety"].message == "ok"
    assert history.gate_results["lint"].passed is False
    assert history.gate_results["lint"].message == "syntax error at line 3"


def test_convergence_judge_quality_failure_continues_with_message_in_history() -> None:
    """2026-07-05 对标审计 P0-1: gate 失败 → CONTINUE, gate 信息在 history 中.

    judge 不再将 gate 失败混同收敛。gate 结果是 RoundHistory 的一部分,
    供 orchestrator step 2i 使用 (gate 失败时阻止 judge 误判停止).
    """
    from auto_engineering.gates.base import GateVerdict

    history = [
        RoundHistory(
            round_id=1,
            gate_results={
                "lint": GateVerdict.failed("syntax error at line 3", gate_name="lint"),
            },
        ),
    ]
    judge = ConvergenceJudge(ConvergenceConfig(max_iterations=10))
    verdict = judge.evaluate(history=history)
    # gate 失败 → 继续 (不触发 QUALITY STOP)
    assert verdict.should_stop is False
    assert verdict.level == LEVEL_CONTINUE
    # gate 结果仍在 history 中供 orchestrator 使用
    assert history[-1].gate_results["lint"].message == "syntax error at line 3"


def test_round_history_gate_results_serialization_roundtrip() -> None:
    """RoundHistory gate_results save → load → message 保留 (P0.4).

    Verdict 必须可 JSON 序列化 + 反序列化还原 message.
    否则 checkpoint 重启后 quality gate 失败原因丢失.
    """
    from auto_engineering.gates.base import GateVerdict
    from auto_engineering.loop.checkpoint import SQLiteCheckpointStore

    history = [
        RoundHistory(
            round_id=1,
            gate_results={
                "safety": GateVerdict.ok("no secrets", gate_name="safety"),
                "lint": GateVerdict.failed("unused import 'os'", gate_name="lint"),
            },
        ),
    ]

    store = SQLiteCheckpointStore(":memory:")
    cp_id = store.save(state=CheckpointEnvelope(), round=1, history=history)
    loaded = store.load(cp_id)

    # 关键: 加载后 history[0].gate_results 仍是 dict[gate_name, Verdict-like]
    # 且 message 保留 (checkpoint 层做 JSON 序列化)
    loaded_gate = loaded.history[0]["gate_results"]
    assert "safety" in loaded_gate
    assert "lint" in loaded_gate

    # safety 保持 passed + message
    assert loaded_gate["safety"]["passed"] is True
    assert loaded_gate["safety"]["message"] == "no secrets"

    # lint 保持 passed=False + message
    assert loaded_gate["lint"]["passed"] is False
    assert loaded_gate["lint"]["message"] == "unused import 'os'"


def test_convergence_judge_quality_all_passed_uses_verdict_objects() -> None:
    """ConvergenceJudge: 全 PASS 时 reason 含 gate 数量, 字段从 Verdict 读 (P0.4).

    验证 _check_quality_gates 现在从 Verdict.passed 读取 (而不是 bool 直接 all()).
    """
    from auto_engineering.gates.base import GateVerdict

    history = [
        RoundHistory(
            round_id=1,
            gate_results={
                "safety": GateVerdict.ok("clean", gate_name="safety"),
                "lint": GateVerdict.ok("no issues", gate_name="lint"),
            },
        ),
    ]
    judge = ConvergenceJudge(ConvergenceConfig(max_iterations=10))
    verdict = judge.evaluate(history=history)
    assert verdict.should_stop is True
    assert verdict.level == LEVEL_QUALITY
    # reason 应含门数量 (2 道)
    assert "2" in verdict.reason


def test_convergence_judge_quality_mixed_continues() -> None:
    """2026-07-05 对标审计 P0-1: 混合 pass+failed → CONTINUE.

    gate 全部通过 → QUALITY STOP; gate 有失败 → CONTINUE.
    参考 LangGraph: gate 是诊断, 不是收敛.
    """
    from auto_engineering.gates.base import GateVerdict

    history = [
        RoundHistory(
            round_id=1,
            gate_results={
                "lint": GateVerdict.failed("undefined variable 'x'", gate_name="lint"),
                "type_check": GateVerdict.ok("ok", gate_name="type_check"),
            },
        ),
    ]
    judge = ConvergenceJudge(ConvergenceConfig(max_iterations=10))
    verdict = judge.evaluate(history=history)
    assert verdict.should_stop is False
    assert verdict.level == LEVEL_CONTINUE


# ============================================================
# F. Phase 2.2-G: Checkpoint.state 类型重构 (P2.1)
# ============================================================


class TestCheckpointStateTyping:
    """Phase 2.2-G: Checkpoint.state 用 Generic[T] 约束, v5.5 P1-8 移除 Protocol bound.

    设计动机: 旧版 `state: Any` 让 IDE/mypy 看不到字段. 重构后用 TypeVar 泛型.
    """

    def test_checkpoint_state_field_is_not_any(
        self, store: SQLiteCheckpointStore
    ) -> None:
        """运行时检查: Checkpoint.state 字段类型不是 Any.

        通过 __annotations__ 反射获取声明类型, 验证不是 Any.
        """
        from typing import Any, get_type_hints

        from auto_engineering.loop.checkpoint import Checkpoint

        hints = get_type_hints(Checkpoint)
        # 关键: state 字段类型不是 Any
        assert "state" in hints, "Checkpoint 必须有 state 字段"
        assert hints["state"] is not Any, (
            f"Checkpoint.state 类型不能是 Any (应为 TypeVar 泛型). "
            f"实际: {hints['state']}"
        )

    def test_checkpoint_generic_with_loopstate(
        self, store: SQLiteCheckpointStore
    ) -> None:
        """泛型 Checkpoint[CheckpointEnvelope] 应被接受 (mypy 类型系统视角).

        验证: 构造 Checkpoint[CheckpointEnvelope] 不抛 TypeError, .state 保留为 CheckpointEnvelope.
        """
        from datetime import UTC, datetime

        from auto_engineering.loop.checkpoint import Checkpoint
        from auto_engineering.loop.state import CheckpointEnvelope  # v2.3 P0-A 重命名

        state = CheckpointEnvelope()
        cp: Checkpoint[CheckpointEnvelope] = Checkpoint(
            id="test-cp",
            round=1,
            step=0,
            state=state,
            history=[],
            created_at=datetime.now(UTC),
            schema_version=DB_SCHEMA_VERSION,
        )
        assert isinstance(cp.state, CheckpointEnvelope)
        assert cp.state is state, "state 引用应保留 (无深拷贝)"

    def test_types_module_exposes_helpers(self) -> None:
        """types.py 必须暴露 serialize/deserialize 帮助函数."""
        from auto_engineering.loop import types

        assert hasattr(types, "serialize_state"), "types.py 必须暴露 serialize_state"
        assert hasattr(types, "deserialize_state"), "types.py 必须暴露 deserialize_state"

    def test_checkpoint_state_round_trip_preserves_type(
        self, store: SQLiteCheckpointStore
    ) -> None:
        """运行时集成: save(CheckpointEnvelope) → load(id) → state 仍是 CheckpointEnvelope 实例.

        验证 Phase 2.1-D load() 重建 Channel 的能力未受 Protocol 重构影响.
        """
        from auto_engineering.loop.state import CheckpointEnvelope  # v2.3 P0-A 重命名

        state = CheckpointEnvelope(round=5, step=3, status="running")
        # 不需要 channel - 验证 state 字段类型和基础字段即可
        # (CheckpointEnvelope 重建能力由 Phase 2.1-D 保障, 此处只验证 Protocol 重构不影响)

        cp_id = store.save(state=state, round=5, history=[])
        loaded = store.load(cp_id)

        # 关键: 加载后 state 应是 CheckpointEnvelope (不是 dict)
        assert isinstance(loaded.state, CheckpointEnvelope), (
            f"加载后 state 必须是 CheckpointEnvelope, 实际: {type(loaded.state).__name__}"
        )
        assert loaded.state.round == 5
        assert loaded.state.step == 3
        assert loaded.state.status == "running"


# ============================================================
# G. v2.3 Phase G: RoundResult.history 含 RoundHistory (P1.3)
# ============================================================


class TestRoundResultHistory:
    """Phase 2.3-G: RoundResult.history: list[RoundHistory] 字段.

    设计动机 (P1.3 数据冗余修复):
        RoundResult (round.py) 与 RoundHistory (convergence.py) 有大量数据冗余:
        - gate_results: 两边都有
        - files_changed / lines_added/removed: RoundHistory 跑 git diff 重算
        - task_outcomes: RoundResult.outcomes 与 RoundHistory.task_outcomes

    修复方案: RoundResult 直接含 history: list[RoundHistory] 字段.
        run_round 末尾自动构造 1 个 RoundHistory 写入 round_result.history.
        Orchestrator 不再 _build_history, 直接 round_result.history 累加.

    借鉴 LangGraph Pregel.tick() Packet 模式:
        Pregel 在 tick() 末尾把数据打包成 Packet 直接传给 channel,
        不在调用方 (PregelLoop) 重复打包数据.
    """

    @pytest.mark.asyncio
    async def test_round_result_contains_history_after_run_round(
        self, tmp_path
    ) -> None:
        """run_round 末尾 RoundResult.history 必须含 1 个 RoundHistory.

        这是 Phase G 核心契约: RoundResult.history 是 RoundHistory 的
        直接载体, 不需 Orchestrator 二次构造.
        """
        from auto_engineering.gates.safety import SafetyGate
        from auto_engineering.loop.convergence import RoundHistory
        from auto_engineering.loop.orchestrator import (
            Orchestrator,
            OrchestratorConfig,
        )
        from auto_engineering.loop.plan import Task
        from auto_engineering.loop.round import TaskOutcome

        async def noop(task, ctx):
            return TaskOutcome(
                task_id=task.id, status="completed", output="ok"
            )

        # 准备空 git 仓库 (SafetyGate 需要可读目录)
        (tmp_path / "test.py").write_text("print('hi')\n")

        task = Task(
            id="t1",
            title="t",
            description="d",
            expected_output="json",
            role="developer",
            target_files=frozenset(),
        )
        config = OrchestratorConfig(
            convergence_config=ConvergenceConfig(
                max_iterations=1, stagnation_threshold=999
            ),
            gates=[SafetyGate()],
            project_root=tmp_path,
        )
        orch = Orchestrator(
            requirement="test", tasks=[task], executor=noop, config=config
        )
        await orch.run()

        # 核心断言: round_result.history 含 1 个 RoundHistory
        assert len(orch.round_results) == 1
        rr = orch.round_results[0]
        assert hasattr(rr, "history"), "RoundResult 必须有 history 字段"
        assert len(rr.history) == 1, (
            f"RoundResult.history 应含 1 个 RoundHistory, 实际: {len(rr.history)}"
        )
        assert isinstance(rr.history[0], RoundHistory), (
            f"rr.history[0] 必须是 RoundHistory, 实际: {type(rr.history[0]).__name__}"
        )
        assert rr.history[0].round_id == 1, "RoundHistory.round_id 必须等于轮次"

    @pytest.mark.asyncio
    async def test_round_history_includes_tasks_run_and_gate_results(
        self, tmp_path
    ) -> None:
        """RoundHistory 必须含 tasks_run + gate_results (非空, 真集成).

        验证 Phase G 修复后, RoundHistory 不再是 Orchestrator 二次包装的空壳,
        而是 run_round 末尾从 RoundResult 真实数据构造.
        """
        from auto_engineering.gates.safety import SafetyGate
        from auto_engineering.loop.orchestrator import (
            Orchestrator,
            OrchestratorConfig,
        )
        from auto_engineering.loop.plan import Task
        from auto_engineering.loop.round import TaskOutcome

        async def noop(task, ctx):
            return TaskOutcome(
                task_id=task.id, status="completed", output="ok"
            )

        (tmp_path / "app.py").write_text("# empty\n")

        tasks = [
            Task(
                id="t1",
                title="t1",
                description="d1",
                expected_output="json",
                role="developer",
                target_files=frozenset(),
            ),
            Task(
                id="t2",
                title="t2",
                description="d2",
                expected_output="json",
                role="developer",
                target_files=frozenset(),
            ),
        ]
        config = OrchestratorConfig(
            convergence_config=ConvergenceConfig(
                max_iterations=1, stagnation_threshold=999
            ),
            gates=[SafetyGate()],
            project_root=tmp_path,
        )
        orch = Orchestrator(
            requirement="test", tasks=tasks, executor=noop, config=config
        )
        await orch.run()

        # 验证 RoundResult.history[0] 含 tasks_run + gate_results
        rr = orch.round_results[0]
        rh = rr.history[0]
        assert sorted(rh.tasks_run) == ["t1", "t2"], (
            f"tasks_run 必须含两个 task id, 实际: {rh.tasks_run}"
        )
        assert rh.task_outcomes == {"t1": "completed", "t2": "completed"}, (
            f"task_outcomes 记录 status, 实际: {rh.task_outcomes}"
        )
        # gate_results 应非空 (SafetyGate 真跑过)
        assert "safety" in rh.gate_results, (
            f"gate_results 必须含 'safety', 实际 keys: {list(rh.gate_results.keys())}"
        )
        assert rh.gate_results["safety"].passed is True, (
            f"SafetyGate 必须 PASS (空仓库无 secret), 实际: {rh.gate_results['safety']}"
        )

    @pytest.mark.asyncio
    async def test_round_result_history_persists_via_checkpoint(
        self, store: SQLiteCheckpointStore, tmp_path
    ) -> None:
        """round_result.history 必须能经 Checkpoint save/load 持久化 (round-trip).

        Phase G 的数据契约: round_result.history 通过 orchestrator.history
        累加 (extend 而非 append), 然后作为 Checkpoint.history 持久化.
        关键: 加载后 history 列表中每个项的 round_id / gate_results 保持一致.
        """
        from auto_engineering.gates.safety import SafetyGate
        from auto_engineering.loop.orchestrator import (
            Orchestrator,
            OrchestratorConfig,
        )
        from auto_engineering.loop.plan import Task
        from auto_engineering.loop.round import TaskOutcome
        from auto_engineering.loop.state import CheckpointEnvelope  # v2.3 P0-A 重命名

        async def noop(task, ctx):
            return TaskOutcome(
                task_id=task.id, status="completed", output="ok"
            )

        (tmp_path / "app.py").write_text("# ok\n")

        task = Task(
            id="t1",
            title="t",
            description="d",
            expected_output="json",
            role="developer",
            target_files=frozenset(),
        )
        config = OrchestratorConfig(
            convergence_config=ConvergenceConfig(
                max_iterations=1, stagnation_threshold=999
            ),
            gates=[SafetyGate()],
            project_root=tmp_path,
        )
        orch = Orchestrator(
            requirement="test", tasks=[task], executor=noop, config=config
        )
        await orch.run()

        # orchestrator.history 应是 round_result.history 的累加
        assert len(orch.history) == len(orch.round_results), (
            f"orch.history 长度必须 == round_results 长度, "
            f"实际 history={len(orch.history)} vs round_results={len(orch.round_results)}"
        )

        # 持久化 round-trip
        state = CheckpointEnvelope(round=1, step=0, status="running")
        cp_id = store.save(state=state, round=1, history=orch.history)
        loaded = store.load(cp_id)

        # 关键: 加载后 history 列表保留 gate_results 完整结构
        assert len(loaded.history) == 1, (
            f"Checkpoint.history 长度必须 == 1, 实际: {len(loaded.history)}"
        )
        loaded_item = loaded.history[0]
        assert loaded_item["round_id"] == 1
        assert "safety" in loaded_item["gate_results"], (
            f"Checkpoint 历史项必须含 'safety' gate, "
            f"实际 keys: {list(loaded_item['gate_results'].keys())}"
        )


# ============================================================
# H. Phase 10 子目标 2: StageRouter + EngineState 集成 + 停滞检测边界
# ============================================================


class TestStageRouterIntegration:
    """Phase 10: StageRouter + EngineState 集成测试.

    已有 test_stage_router.py 覆盖 StageRouter 单独行为 (37 用例).
    本测试套验证 StageRouter 与 EngineState 真实协作:
    - 连续 MAJOR 计数累加 + 超限 stop_reason 含正确数字
    - APPROVE 重置 majors_in_a_row 但保留 total_majors
    - clear_stage_fields 真实清空 EngineState 字段
    - _derive_status 真实判定 EngineState.status
    """

    def test_stage_router_major_in_a_row_accumulates_in_engine_state(self) -> None:
        """连续 MAJOR 计数累加: 模拟 3 轮 MAJOR, EngineState.majors_in_a_row 累加.

        边界: 第 1 轮 MAJOR (1/1), 第 2 轮 MAJOR (2/2) 触发超限 stop.
        """
        from auto_engineering.engine.state import EngineState
        from auto_engineering.loop.stage_router import StageRouter, update_majors_count

        state = EngineState()
        router = StageRouter(max_majors_in_a_row=2, max_total_majors=3)

        # 第 1 轮 MAJOR
        update_majors_count(state, "MAJOR")
        assert state.majors_in_a_row == 1
        assert state.total_majors == 1
        decision = router.next("critic", "MAJOR", state.majors_in_a_row, state.total_majors)
        assert decision.next_stage == "developer"  # 未超限

        # 第 2 轮 MAJOR → 连续 2 触发 T6
        update_majors_count(state, "MAJOR")
        assert state.majors_in_a_row == 2
        assert state.total_majors == 2
        decision = router.next("critic", "MAJOR", state.majors_in_a_row, state.total_majors)
        assert decision.should_stop is True
        assert "连续2" in decision.stop_reason  # 含累加数字
        assert "累计2" in decision.stop_reason

    def test_stage_router_approve_resets_in_a_row_but_preserves_total(self) -> None:
        """APPROVE: 重置 majors_in_a_row=0 但 total_majors 保留.

        业务场景: 累计 3 次 MAJOR 后终于 APPROVE, majors_in_a_row 应清零.
        """
        from auto_engineering.engine.state import EngineState
        from auto_engineering.loop.stage_router import update_majors_count

        state = EngineState()
        # 累计 3 轮 MAJOR
        update_majors_count(state, "MAJOR")
        update_majors_count(state, "MAJOR")
        update_majors_count(state, "MAJOR")
        assert state.majors_in_a_row == 3
        assert state.total_majors == 3

        # APPROVE → 重置 in_a_row, 保留 total
        update_majors_count(state, "APPROVE")
        assert state.majors_in_a_row == 0
        assert state.total_majors == 3  # 保留

    def test_stage_router_total_majors_exceeds_independent_of_in_a_row(self) -> None:
        """累计 MAJOR 超限: 即便 in_a_row 较小, total 触发 T6 stop.

        场景: 间隔 APPROVE 重置 in_a_row 后, 累计总数仍超限.
        """
        from auto_engineering.engine.state import EngineState
        from auto_engineering.loop.stage_router import StageRouter, update_majors_count

        state = EngineState()
        router = StageRouter(max_majors_in_a_row=2, max_total_majors=3)

        # 模式: MAJOR, MAJOR, APPROVE, MAJOR, MAJOR (累计 4 次)
        for verdict in ["MAJOR", "MAJOR", "APPROVE", "MAJOR", "MAJOR"]:
            update_majors_count(state, verdict)

        # in_a_row=2 (最后一个 APPROVE 后重置, 然后 +2)
        # total=4 (累计)
        assert state.majors_in_a_row == 2
        assert state.total_majors == 4

        # 累计超限触发 (即便 in_a_row=2 == max_in_a_row, 这里应仍触发)
        decision = router.next("critic", "MAJOR", state.majors_in_a_row, state.total_majors)
        # 先检查连续 (in_a_row=2 == max=2) → 触发
        assert decision.should_stop is True

    def test_stage_router_empty_verdict_in_critic_triggers_safety_stop(self) -> None:
        """critic 阶段 verdict="" 异常: 抛 CriticVerdictInvalid (Bug 3 prismscan 修复).

        2026-07-04 行为变更: 旧实现 should_stop=True + reason 含 '异常' / '' 静默归一化为 PASS
        (反向语义). 新实现 raise CriticVerdictInvalid 让 orchestrator 显式处理.
        """
        import pytest
        from auto_engineering.loop.stage_router import CriticVerdictInvalid, StageRouter

        router = StageRouter()
        with pytest.raises(CriticVerdictInvalid) as exc_info:
            router.next("critic", "", majors_in_a_row=0, total_majors=0)
        assert exc_info.value.verdict == ""

    def test_stage_router_unknown_stage_returns_safety_stop(self) -> None:
        """未知 stage 防御性 stop (避免 Orchestrator 僵死)."""
        from auto_engineering.loop.stage_router import StageRouter

        router = StageRouter()
        decision = router.next("unknown_stage", "APPROVE", 0, 0)
        assert decision.should_stop is True
        assert "未知" in decision.stop_reason
        assert "unknown_stage" in decision.stop_reason

    def testclear_stage_fields_actually_clears_engine_state(self) -> None:
        """clear_stage_fields 真实清空 EngineState 字段 (各 stage)."""
        from auto_engineering.engine.state import EngineState
        from auto_engineering.loop.stage_router import clear_stage_fields

        state = EngineState()

        # 准备: 填充所有 stage 字段
        state.plan = "test plan"
        state.file_list = ["a.py", "b.py"]
        state.batch_plan = [{"task": "x"}]
        state.contracts = {"contract1": "spec"}
        state.files_changed = ["a.py"]
        state.commit_hash = "abc123"
        state.test_results = {"test1": "pass"}
        state.verdict = "MAJOR"
        state.findings = ["finding1"]
        state.critic_feedback = "fix this"

        # 清空 architect
        clear_stage_fields(state, "architect")
        assert state.plan == ""
        assert state.file_list == []
        assert state.batch_plan == []
        assert state.contracts == {}
        # 其他 stage 字段未动
        assert state.verdict == "MAJOR"

        # 清空 developer
        clear_stage_fields(state, "developer")
        assert state.files_changed == []
        assert state.commit_hash == ""
        assert state.test_results == {}

        # 清空 critic
        clear_stage_fields(state, "critic")
        assert state.verdict == ""
        assert state.findings == []
        assert state.critic_feedback == ""

    def testclear_stage_fields_unknown_stage_is_noop(self) -> None:
        """clear_stage_fields 传入未知 stage → no-op (防御性)."""
        from auto_engineering.engine.state import EngineState
        from auto_engineering.loop.stage_router import clear_stage_fields

        state = EngineState()
        state.plan = "keep me"
        clear_stage_fields(state, "unknown_stage")
        assert state.plan == "keep me"  # 未被清空

    def test_stage_router_init_validates_positive_limits(self) -> None:
        """StageRouter 拒绝 ≤0 限制 (无意义配置)."""
        from auto_engineering.loop.stage_router import StageRouter

        # max_majors_in_a_row < 1 → ValueError
        with pytest.raises(ValueError, match="max_majors_in_a_row"):
            StageRouter(max_majors_in_a_row=0)

        # max_total_majors < 1 → ValueError
        with pytest.raises(ValueError, match="max_total_majors"):
            StageRouter(max_total_majors=-1)


class TestDetectStagnationEdgeCases:
    """Phase 10: detect_stagnation 边界值测试.

    已有测试覆盖基本场景. 本套补充:
    - threshold=1 边界 (只 1 轮无变化即触发)
    - diff_ratio_threshold=0 边界 (任何变化都视为有变化)
    - diff_ratio_threshold=1.0 边界 (任何变化都视为无变化)
    - 空 history (0 轮)
    """

    def test_detect_stagnation_threshold_one_single_round(self) -> None:
        """threshold=1: 1 轮无变化即触发 (最少 2 轮比较)."""
        history = [
            RoundHistory(round_id=1, files_changed=5),
            RoundHistory(round_id=2, files_changed=5),  # 1 轮无变化
        ]
        stagnant = detect_stagnation(history, threshold=1, diff_ratio_threshold=0.1)
        assert stagnant is True

    def test_detect_stagnation_empty_history_returns_false(self) -> None:
        """空 history → 不触发 (无数据可比较)."""
        assert detect_stagnation([], threshold=2, diff_ratio_threshold=0.05) is False

    def test_detect_stagnation_diff_ratio_threshold_zero(self) -> None:
        """diff_ratio_threshold=0: 任何非零变化都视为有变化.

        此时: 0.0 < 0 → False (永远触发), 但实际应用用 > 0.
        """
        history = [
            RoundHistory(round_id=1, files_changed=5),
            RoundHistory(round_id=2, files_changed=5),  # diff=0.0
        ]
        # threshold=0.0 时: 0.0 < 0.0 = False → 不触发
        stagnant = detect_stagnation(history, threshold=1, diff_ratio_threshold=0.0)
        assert stagnant is False

    def test_detect_stagnation_diff_ratio_threshold_one(self) -> None:
        """diff_ratio_threshold=1.0: diff=0.95 < 1.0 触发 (算法严格小于).

        设计意图: diff_ratio_threshold 是上界 (严格小于), 不是 inclusive.
        diff_ratio=0.95 (从 5 变到 100) < 1.0 → 触发.
        """
        history = [
            RoundHistory(round_id=1, files_changed=5),
            RoundHistory(round_id=2, files_changed=100),  # diff=95/100=0.95
        ]
        # 0.95 < 1.0 → 视为无变化, 触发
        stagnant = detect_stagnation(history, threshold=1, diff_ratio_threshold=1.0)
        assert stagnant is True

    def test_detect_stagnation_high_diff_ratio_threshold_always_triggers(self) -> None:
        """diff_ratio_threshold=0.99 + 小变化 → 触发 (设计意图)."""
        history = [
            RoundHistory(round_id=1, files_changed=5),
            RoundHistory(round_id=2, files_changed=6),  # diff=1/6=0.167 < 0.99
            RoundHistory(round_id=3, files_changed=5),  # diff=1/6=0.167 < 0.99
        ]
        stagnant = detect_stagnation(history, threshold=2, diff_ratio_threshold=0.99)
        assert stagnant is True

    def test_detect_stagnation_exact_threshold_round(self) -> None:
        """精确 threshold 轮无变化才触发 (边界 inclusive)."""
        # 3 轮无变化 + threshold=3 → 触发
        history = [
            RoundHistory(round_id=i, files_changed=5)
            for i in range(1, 5)  # 4 轮, 比较 3 次
        ]
        stagnant = detect_stagnation(history, threshold=3, diff_ratio_threshold=0.05)
        assert stagnant is True

        # 2 轮无变化 + threshold=3 → 不触发
        history_short = [
            RoundHistory(round_id=1, files_changed=5),
            RoundHistory(round_id=2, files_changed=5),
        ]
        stagnant_short = detect_stagnation(history_short, threshold=3, diff_ratio_threshold=0.05)
        assert stagnant_short is False

    def test_detect_stagnation_change_in_middle_resets_counter(self) -> None:
        """中间出现变化重置计数器 (验证 reset 行为).

        场景: 5 轮, 中间第 3 轮有变化, 后续 2 轮无变化 + threshold=3 → 不触发.
        """
        history = [
            RoundHistory(round_id=1, files_changed=5),
            RoundHistory(round_id=2, files_changed=5),  # 无变化 (1)
            RoundHistory(round_id=3, files_changed=100),  # 大变化 → 重置
            RoundHistory(round_id=4, files_changed=5),  # 无变化 (重置后 1)
            RoundHistory(round_id=5, files_changed=5),  # 无变化 (重置后 2)
        ]
        # threshold=3, 重置后只连续 2 轮 → 不触发
        stagnant = detect_stagnation(history, threshold=3, diff_ratio_threshold=0.05)
        assert stagnant is False


class TestConvergenceJudgeEmptyAndBoundary:
    """Phase 10: ConvergenceJudge 边界 + 默认值."""

    def test_convergence_judge_continues_when_history_at_max_minus_one(self) -> None:
        """历史长度 < max_iterations → 不触发硬上限 (差 1 也不触发).

        设计意图: hard limit 在 round_id == max_iterations 时才触发,
        round_id == max_iterations - 1 时不触发.
        """
        history = [RoundHistory(round_id=9)]  # 1 轮, max=10
        judge = ConvergenceJudge(ConvergenceConfig(max_iterations=10))
        verdict = judge.evaluate(history=history)
        # round 9 + max 10 → 不应触发硬上限
        assert verdict.should_stop is False
        assert verdict.level == LEVEL_CONTINUE

    def test_convergence_judge_default_config_has_reasonable_values(self) -> None:
        """默认 ConvergenceConfig 应有合理默认值 (>= 1 限制)."""
        config = ConvergenceConfig()
        assert config.max_iterations >= 1
        assert config.stagnation_threshold >= 1

    def test_convergence_judge_picks_hard_limit_over_stagnant_when_both_apply(self) -> None:
        """硬上限优先于停滞: 同时满足时返回硬上限 (优先级 4 > 2)."""
        history = [
            RoundHistory(round_id=i, files_changed=5) for i in range(1, 11)
        ]  # 10 轮无变化 + round 10 == max
        judge = ConvergenceJudge(
            ConvergenceConfig(max_iterations=10, stagnation_threshold=2)
        )
        verdict = judge.evaluate(history=history)
        # 硬上限 (4) > 停滞 (2)
        assert verdict.level == LEVEL_HARD_LIMIT
        assert verdict.should_stop is True
