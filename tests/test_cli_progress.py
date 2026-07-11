"""test_cli_progress.py — T9b: ae progress (B9 ProgressTree 人视角看板).

覆盖 ae progress 从持久化 checkpoint 读 progress_tree_json → 展示:
  - text 模式: system/component 层次 + 完成率
  - --format json: summary 4 字段 (completion_pct/total_tasks/done_tasks/node_count)
  - 无 checkpoint: 优雅提示, 不崩溃 (exit 0)

CliRunner + tmp .ae-state, 直接种入 checkpoint (解耦 orchestrator tick 机制).
"""

from __future__ import annotations

import json

from click.testing import CliRunner

from auto_engineering.cli import main
from auto_engineering.engine.progress_tree import ProgressTree
from auto_engineering.engine.state import EngineState
from auto_engineering.loop.checkpoint.store import SQLiteCheckpointStore


def _seed_checkpoint(tmp_path, tree: ProgressTree) -> None:
    """种入一个含 progress_tree_json 的 checkpoint 到 .ae-state/checkpoints.db."""
    cp_dir = tmp_path / ".ae-state"
    cp_dir.mkdir(parents=True, exist_ok=True)
    state = EngineState(
        requirement="实现登录",
        current_stage="developer",
        progress_tree_json=json.dumps(tree.to_dict(), ensure_ascii=False),
    )
    store = SQLiteCheckpointStore(cp_dir / "checkpoints.db")
    try:
        store.save(state=state, round=1, step=1, history=[])
    finally:
        store.close()


def _half_done_tree() -> ProgressTree:
    """component AuthService: 2 tasks, 1 done → 50% (不折叠, 可见)."""
    tree = ProgressTree.from_batch_plan(
        [{"component": "AuthService", "design_section": "B2",
          "tasks": [{"id": "T1"}, {"id": "T2"}]}],
        requirement="实现登录",
    )
    cid = "§B2"
    tree.nodes[cid].done_tasks = 1
    tree.recalculate_parents(cid)
    return tree


def _parse_json_block(output: str) -> dict:
    """提取输出中的 JSON 对象 (indent=2 多行, 跳过 logging stderr 混入)."""
    start = output.index("{")
    end = output.rindex("}")
    return json.loads(output[start:end + 1])


class TestTextDisplay:
    def test_progress_text_shows_system_and_component(self, tmp_path) -> None:
        _seed_checkpoint(tmp_path, _half_done_tree())
        result = CliRunner().invoke(
            main, ["progress", "--project-root", str(tmp_path)])
        assert result.exit_code == 0, result.output
        assert "SYSTEM" in result.output
        assert "AuthService" in result.output


class TestJsonFormat:
    def test_progress_json_summary(self, tmp_path) -> None:
        _seed_checkpoint(tmp_path, _half_done_tree())
        result = CliRunner().invoke(
            main, ["progress", "--format", "json",
                   "--project-root", str(tmp_path)])
        assert result.exit_code == 0, result.output
        summary = _parse_json_block(result.output)
        assert summary["total_tasks"] == 2
        assert summary["done_tasks"] == 1
        assert summary["completion_pct"] == 50.0
        assert summary["node_count"] >= 2


class TestNoCheckpoint:
    def test_no_checkpoint_graceful(self, tmp_path) -> None:
        result = CliRunner().invoke(
            main, ["progress", "--project-root", str(tmp_path)])
        assert result.exit_code == 0, result.output
        assert "暂无进度" in result.output

    def test_no_checkpoint_json_zeros(self, tmp_path) -> None:
        result = CliRunner().invoke(
            main, ["progress", "--format", "json",
                   "--project-root", str(tmp_path)])
        assert result.exit_code == 0, result.output
        summary = _parse_json_block(result.output)
        assert summary["node_count"] == 0
        assert summary["completion_pct"] == 0.0
