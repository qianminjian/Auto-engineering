"""Host Runtime 预创建 Action 交接目录的回归测试。"""

from __future__ import annotations

from pathlib import Path


def test_precreates_all_bound_host_artifact_parents(tmp_path: Path) -> None:
    from auto_engineering.cli.host_action_work_files import (
        ensure_action_work_file_parents,
    )

    mapped = {
        "host_execution": {
            "work_files": {
                "outcomes": ".ae-state/host-runtime/work/a/outcomes.json",
                "coordinator_result": ".ae-state/host-runtime/work/a/coordinator-result.json",
                "result": ".ae-state/host-runtime/work/a/result.json",
            },
            "workers": [
                {
                    "outcome_path": ".ae-state/host-runtime/worker-outcomes/a.json",
                    "native_result_path": ".ae-state/host-runtime/native-results/a.json",
                    "observation_path": ".ae-state/host-runtime/worker-observations/a.json",
                    "receipt_path": ".ae-state/spawn-proofs/a.json",
                },
            ],
        },
    }

    ensure_action_work_file_parents(mapped, tmp_path)

    for relative in (
        ".ae-state/host-runtime/work/a",
        ".ae-state/host-runtime/worker-outcomes",
        ".ae-state/host-runtime/native-results",
        ".ae-state/host-runtime/worker-observations",
        ".ae-state/spawn-proofs",
    ):
        assert (tmp_path / relative).is_dir()


def test_rejects_worker_artifact_parent_escape(tmp_path: Path) -> None:
    from auto_engineering.cli.host_action_work_files import (
        ensure_action_work_file_parents,
    )

    mapped = {
        "host_execution": {
            "work_files": {},
            "workers": [{"outcome_path": "../outside.json"}],
        },
    }

    try:
        ensure_action_work_file_parents(mapped, tmp_path)
    except ValueError as exc:
        assert str(exc) == "HOST_ACTION_WORK_FILE_PATH_ESCAPE"
    else:
        raise AssertionError("worker artifact path escape must fail closed")
