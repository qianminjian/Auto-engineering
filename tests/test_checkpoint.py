"""CheckpointStore SQLite CRUD + Checkpoint dataclass 行为."""

import pytest

from auto_engineering.engine.checkpoint import Checkpoint, CheckpointStore
from auto_engineering.engine.state import LoopState
from auto_engineering.errors import AEError, ErrorCode


def test_checkpoint_create_生成_UUID_和初始_step(checkpoint_dir):
    state = LoopState(requirement="x")
    cp = Checkpoint.create("thread-1", state)

    assert cp.id != ""  # UUID
    assert cp.parent_id is None
    assert cp.thread_id == "thread-1"
    assert cp.step == 0
    assert cp.status == "pending"


def test_checkpoint_increment_step_累加(checkpoint_dir):
    cp = Checkpoint.create("t", LoopState())
    cp.increment_step()
    cp.increment_step()
    assert cp.step == 2


def test_checkpoint_apply_writes_委托给_LoopState(checkpoint_dir):
    state = LoopState(plan="original")
    cp = Checkpoint.create("t", state)
    cp.apply_writes({"plan": "updated", "verdict": "APPROVE"})

    assert cp.state.plan == "updated"
    assert cp.state.verdict == "APPROVE"


def test_checkpoint_store_save_and_load_往返(checkpoint_dir):
    store = CheckpointStore(f"{checkpoint_dir}/thread.db")
    state = LoopState(requirement="test req", plan="p", file_list=["x.py"])
    cp = Checkpoint.create("thread-1", state)

    store.save_checkpoint(cp)
    loaded = store.load_checkpoint(cp.id)

    assert loaded.id == cp.id
    assert loaded.thread_id == "thread-1"
    assert loaded.state.requirement == "test req"
    assert loaded.state.file_list == ["x.py"]


def test_checkpoint_store_load_不存在抛_CHECKPOINT_LOAD_FAILED(checkpoint_dir):
    store = CheckpointStore(f"{checkpoint_dir}/thread.db")
    with pytest.raises(AEError) as exc_info:
        store.load_checkpoint("nonexistent-uuid")
    assert exc_info.value.code == ErrorCode.CHECKPOINT_LOAD_FAILED


def test_checkpoint_store_save_writes_追加_不覆盖(checkpoint_dir):
    store = CheckpointStore(f"{checkpoint_dir}/thread.db")
    cp = Checkpoint.create("t", LoopState())
    store.save_checkpoint(cp)

    store.save_writes(cp.id, "architect", {"plan": "p1"})
    store.save_writes(cp.id, "developer", {"commit_hash": "abc"})

    # writes 表是 append-only,两条记录都保留
    conn = store._get_conn()
    rows = conn.execute(
        "SELECT task_id, channel, value_json FROM writes WHERE checkpoint_id = ? ORDER BY id",
        (cp.id,),
    ).fetchall()
    assert len(rows) == 2
    assert rows[0][0] == "architect"
    assert rows[0][1] == "plan"
    assert rows[1][0] == "developer"
    assert rows[1][1] == "commit_hash"


def test_checkpoint_store_WAL_模式启用(checkpoint_dir):
    store = CheckpointStore(f"{checkpoint_dir}/thread.db")
    store.save_checkpoint(Checkpoint.create("t", LoopState()))
    # WAL 模式启用后会生成 .db-wal 文件(临时)
    # 这里只检查 PRAGMA 已设置,不强制文件存在(SQLite 可能在 commit 后清理)
    conn = store._get_conn()
    mode = conn.execute("PRAGMA journal_mode").fetchone()[0]
    assert mode.lower() == "wal"


# ----- v3.1 B3 修复: CheckpointStore 实现 context manager -----

def test_context_manager_yields_store(checkpoint_dir):
    """B3: CheckpointStore 应实现 __enter__/__exit__,with 语句可正常 yield store.

    Why: 用户用 `with CheckpointStore(path) as store:` 时,__exit__ 应自动 close,
    避免 sqlite3 fd 泄漏(ResourceWarning).
    """
    db_path = f"{checkpoint_dir}/ctx.db"
    with CheckpointStore(db_path) as store:
        assert store is not None
        # __enter__ 后应能正常使用
        cp = Checkpoint.create("t", LoopState())
        store.save_checkpoint(cp)
        loaded = store.load_checkpoint(cp.id)
        assert loaded.id == cp.id
    # 退出 with 后,_conn 已被关闭(防止 ResourceWarning)
    assert store._conn is None
