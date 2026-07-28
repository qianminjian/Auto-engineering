"""T138 God Class 拆分后的职责边界测试。"""

from pathlib import Path


def test_prompt_logging_is_owned_by_dedicated_module(tmp_path: Path) -> None:
    from auto_engineering.loop.prompt_logger import write_action_prompt_log

    write_action_prompt_log(
        tmp_path,
        {
            "action": "developer",
            "stage": "developer",
            "tick": 3,
            "instruction": "实现任务",
            "expected_format": {"stage": "developer"},
        },
    )

    log_dir = tmp_path / "_scratch" / "prompt-log"
    assert len(list(log_dir.glob("*-rendered-*.json"))) == 1
    prompt = next(log_dir.glob("*-rendered-*.md")).read_text()
    assert "实现任务" in prompt
    assert "Expected Format" in prompt


def test_ratchet_runner_is_independent_from_orchestrator(
    tmp_path: Path,
) -> None:
    from auto_engineering.metrics.ratchet_runner import run_ratchet

    class EmptyCollector:
        @staticmethod
        def load_baseline() -> dict:
            return {}

    assert run_ratchet(tmp_path, EmptyCollector(), {}) is None
