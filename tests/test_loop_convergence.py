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
    SCHEMA_VERSION,
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
    Verdict,
    detect_stagnation,
    diff_ratio,
)
from auto_engineering.loop.state import LoopState

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
    verdict = judge.evaluate(state=None, history=[])
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
    verdict = judge.evaluate(state=None, history=history)
    assert verdict.should_stop is True
    assert verdict.level == LEVEL_HARD_LIMIT
    assert "10" in verdict.reason  # max_iterations


def test_convergence_quality_gate_all_passed() -> None:
    """质量门 (level=3): 7 道 Gate 全 PASS → 停止."""
    history = [
        RoundHistory(round_id=1),
        RoundHistory(
            round_id=2,
            gate_results={f"gate_{i}": True for i in range(7)},  # 7 道全过
        ),
    ]
    judge = ConvergenceJudge(ConvergenceConfig(max_iterations=10))
    verdict = judge.evaluate(state=None, history=history)
    assert verdict.should_stop is True
    assert verdict.level == LEVEL_QUALITY


def test_convergence_quality_gate_partial_does_not_stop() -> None:
    """质量门: 任一 Gate FAIL → 不触发停止."""
    history = [
        RoundHistory(
            round_id=1,
            gate_results={"g1": True, "g2": False, "g3": True},  # g2 失败
        ),
    ]
    judge = ConvergenceJudge(ConvergenceConfig(max_iterations=10))
    verdict = judge.evaluate(state=None, history=history)
    assert verdict.should_stop is False
    assert verdict.level == LEVEL_CONTINUE


def test_convergence_semantic_satisfied_stops() -> None:
    """语义收敛 (level=1): LLM 评估 semantic_satisfied=True → 停止."""
    history = [
        RoundHistory(round_id=1),
        RoundHistory(round_id=2, semantic_satisfied=True),
    ]
    judge = ConvergenceJudge(ConvergenceConfig(max_iterations=10))
    verdict = judge.evaluate(state=None, history=history)
    assert verdict.should_stop is True
    assert verdict.level == LEVEL_SEMANTIC
    assert "LLM" in verdict.reason


def test_convergence_priority_hard_limit_beats_quality() -> None:
    """优先级: 硬上限 (4) > 质量门 (3). 同时满足时返回硬上限."""
    history = [
        RoundHistory(
            round_id=10,  # = max_iterations
            gate_results={"g1": True},
            semantic_satisfied=True,
        ),
    ]
    judge = ConvergenceJudge(ConvergenceConfig(max_iterations=10))
    verdict = judge.evaluate(state=None, history=history)
    assert verdict.level == LEVEL_HARD_LIMIT  # 不是 QUALITY


def test_convergence_priority_quality_beats_stagnant() -> None:
    """优先级: 质量门 (3) > 停滞检测 (2). 同时满足时返回质量门."""
    # 连续 3 轮无变化 (触发停滞), 同时最新一轮所有 gate 通过 (触发质量门)
    history = [
        RoundHistory(round_id=1, files_changed=5),
        RoundHistory(round_id=2, files_changed=5),  # 无变化
        RoundHistory(round_id=3, files_changed=5),  # 无变化
        RoundHistory(
            round_id=4,
            files_changed=5,  # 无变化
            gate_results={"g1": True, "g2": True},  # 全过
        ),
    ]
    judge = ConvergenceJudge(ConvergenceConfig(max_iterations=10))
    verdict = judge.evaluate(state=None, history=history)
    assert verdict.level == LEVEL_QUALITY  # 优先级更高


def test_verdict_continue_factory() -> None:
    """Verdict.continue_() 工厂."""
    v = Verdict.continue_()
    assert v.should_stop is False
    assert v.level == LEVEL_CONTINUE


def test_verdict_stop_validates_level() -> None:
    """Verdict.stop() 拒绝非法 level."""
    with pytest.raises(ValueError):
        Verdict.stop(level=99, reason="invalid")
    # 合法 level 不报错
    v = Verdict.stop(level=LEVEL_HARD_LIMIT, reason="test")
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
    verdict = judge.evaluate(state=None, history=history)
    assert verdict.should_stop is True
    assert verdict.level == LEVEL_STAGNANT


# ============================================================
# C. Checkpoint save/load/list
# ============================================================


def test_checkpoint_save_returns_id(store: SQLiteCheckpointStore) -> None:
    """save() 返回 checkpoint_id (UUID 字符串)."""
    state = LoopState()
    cp_id = store.save(state, round=1)
    assert isinstance(cp_id, str)
    assert len(cp_id) > 0


def test_checkpoint_save_and_load(store: SQLiteCheckpointStore) -> None:
    """save() → load() 往返一致."""
    state = LoopState()
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
    state = LoopState()
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
    state = LoopState()
    store.save(state, round=1)
    store.save(state, round=2, step=5)
    cp = store.load_by_round(round=2)
    assert cp is not None
    assert cp.round == 2
    assert cp.step == 5


def test_checkpoint_load_by_round_not_found(store: SQLiteCheckpointStore) -> None:
    """load_by_round() 不存在的轮次 → None."""
    state = LoopState()
    store.save(state, round=1)
    assert store.load_by_round(round=99) is None


def test_checkpoint_list_all_returns_sorted(
    store: SQLiteCheckpointStore,
) -> None:
    """list_all() 按 round ASC 排序."""
    state = LoopState()
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
    state = LoopState()
    assert store.count() == 0
    store.save(state, round=1)
    store.save(state, round=2)
    assert store.count() == 2


def test_checkpoint_delete(store: SQLiteCheckpointStore) -> None:
    """delete() 删除指定 ID."""
    state = LoopState()
    cp_id = store.save(state, round=1)
    assert store.delete(cp_id) is True
    assert store.count() == 0
    # 再次删除 → False
    assert store.delete(cp_id) is False


def test_checkpoint_clear(store: SQLiteCheckpointStore) -> None:
    """clear() 清空所有 Checkpoint."""
    state = LoopState()
    store.save(state, round=1)
    store.save(state, round=2)
    store.clear()
    assert store.count() == 0


def test_checkpoint_with_history(store: SQLiteCheckpointStore) -> None:
    """save() 带 history → load() 可还原."""
    state = LoopState()
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
    state = LoopState()
    parent_id = store.save(state, round=1)
    cp_id = store.save(state, round=2, parent_id=parent_id, tag="v1.0-milestone")
    loaded = store.load(cp_id)
    assert loaded.parent_id == parent_id
    assert loaded.tag == "v1.0-milestone"


def test_checkpoint_explicit_id(store: SQLiteCheckpointStore) -> None:
    """save() 支持显式指定 checkpoint_id."""
    state = LoopState()
    store.save(state, round=1, checkpoint_id="my-custom-id-001")
    loaded = store.load("my-custom-id-001")
    assert loaded.id == "my-custom-id-001"


def test_checkpoint_meta_is_lightweight(store: SQLiteCheckpointStore) -> None:
    """CheckpointMeta 不含 state/history (仅元数据)."""
    state = LoopState()
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
                cp_id = store.save(LoopState(), round=thread_id * 10 + i)
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
    store.save(LoopState(), round=1)
    assert store.count() == 1

    # 制造一个失败: 模拟 schema_version 冲突 (插入重复主键)
    # 用直接 SQL 插入一个 ID, 然后 save 时用相同 ID 触发主键冲突
    state = LoopState()
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
    """save() 记录的 schema_version 等于当前 SCHEMA_VERSION."""
    state = LoopState()
    cp_id = store.save(state, round=1)
    loaded = store.load(cp_id)
    assert loaded.schema_version == SCHEMA_VERSION


def test_checkpoint_schema_mismatch_raises(tmp_path) -> None:
    """手动写入旧 schema_version → load 抛 CheckpointSchemaMismatchError."""
    db_path = tmp_path / "schema_test.db"
    store = SQLiteCheckpointStore(db_path)

    # 用 store 正常建表
    cp_id = store.save(LoopState(), round=1)

    # 手动修改 schema_version 为旧版本
    conn = sqlite3.connect(str(db_path))
    conn.execute(
        "UPDATE checkpoints SET schema_version = ? WHERE id = ?",
        (SCHEMA_VERSION - 1, cp_id),
    )
    conn.commit()
    conn.close()

    # load 应抛 SchemaMismatch
    with pytest.raises(CheckpointSchemaMismatchError) as exc_info:
        store.load(cp_id)
    assert exc_info.value.found == SCHEMA_VERSION - 1
    assert exc_info.value.expected == SCHEMA_VERSION


def test_checkpoint_schema_mismatch_latest_raises(tmp_path) -> None:
    """load_latest 也校验 schema."""
    db_path = tmp_path / "schema_latest.db"
    store = SQLiteCheckpointStore(db_path)

    cp_id = store.save(LoopState(), round=1)
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
    verdict_before = judge.evaluate(state=None, history=history)
    assert verdict_before.should_stop is True
    assert verdict_before.level == LEVEL_STAGNANT

    # 阶段 2: 保存为 checkpoint
    cp_id = store.save(state=LoopState(), round=3, history=history)
    assert cp_id is not None

    # 阶段 3: 重新加载, 用同一 judge 判定
    loaded = store.load(cp_id)
    history_reloaded = [
        RoundHistory(**h) for h in loaded.history
    ]
    verdict_after = judge.evaluate(state=None, history=history_reloaded)
    assert verdict_after.level == LEVEL_STAGNANT
    assert verdict_after.reason == verdict_before.reason
