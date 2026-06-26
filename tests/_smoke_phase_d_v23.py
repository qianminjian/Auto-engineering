"""v2.3 Phase D runtime smoke — RoundHistory 保留 Verdict.message (P0.4).

执行: .venv/bin/python -c "import asyncio; from tests._smoke_phase_d_v23 import main; \
        sys_exit_code = asyncio.run(main()); print(f'exit={sys_exit_code}')"
成功 → print "Phase D runtime smoke PASS" + return 0
失败 → raise + return non-zero

测试严禁虚化: 真实集成 Orchestrator + SafetyGate + LintGate + FailingGate.
"""
from __future__ import annotations

import tempfile
from pathlib import Path


def main():
    return _smoke()


async def _smoke() -> int:
    from auto_engineering.gates.base import Gate, Verdict
    from auto_engineering.gates.lint import LintGate
    from auto_engineering.gates.safety import SafetyGate
    from auto_engineering.loop.convergence import ConvergenceJudge
    from auto_engineering.loop.orchestrator import Orchestrator, OrchestratorConfig
    from auto_engineering.loop.plan import Task
    from auto_engineering.loop.round import TaskOutcome

    class FailingGate(Gate):
        name = "fake_failing"

        def run(self, project_root: Path) -> Verdict:
            return Verdict.failed("intentional failure for test", gate_name=self.name)

    async def noop(task, ctx):
        return TaskOutcome(
            task_id=task.id,
            status="completed",
            output="done",
        )

    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        (root / "test.py").write_text('print("hi")\n')

        tasks = [
            Task(
                id="t1",
                title="t",
                description="d",
                expected_output="json",
                role="developer",
                target_files=frozenset(),
            ),
        ]
        config = OrchestratorConfig(
            gates=[SafetyGate(), LintGate(), FailingGate()],
            project_root=root,
        )
        orch = Orchestrator(
            requirement="test",
            tasks=tasks,
            executor=noop,
            config=config,
        )
        history = await orch.run()

        latest = history[-1]

        # 验证 1: gate_results 是 Verdict (有 message)
        fake_verdict = latest.gate_results.get("fake_failing")
        assert fake_verdict is not None, "fake_failing missing in gate_results"
        assert fake_verdict.passed is False, f"expected passed=False, got {fake_verdict.passed}"
        assert "intentional" in fake_verdict.message, (
            f"fake_verdict.message missing 'intentional': {fake_verdict.message}"
        )

        # 验证 2: safety 和 lint 也是 Verdict
        safety_verdict = latest.gate_results.get("safety")
        lint_verdict = latest.gate_results.get("lint")
        assert isinstance(safety_verdict, Verdict), (
            f"safety gate_results is not Verdict: {type(safety_verdict)}"
        )
        assert isinstance(lint_verdict, Verdict), (
            f"lint gate_results is not Verdict: {type(lint_verdict)}"
        )

        # 验证 3: ConvergenceJudge 不应触发 LEVEL_QUALITY (有 failed gate)
        judge = ConvergenceJudge()
        verdict = judge.evaluate(state=None, history=history)

        # 由于 fake_failing 失败 → _check_quality_gates 不应触发 stop
        # 但 hard_limit 也不会触发 (max_rounds=10, only ran 1 round)
        # 语义也不通过 (无 evaluator) → 应返回 LEVEL_CONTINUE 或硬上限
        assert verdict.level != 3 or "质量门失败" not in verdict.reason, (
            f"verdict 错误触发了 QUALITY_PASS 但有失败 gate: level={verdict.level}, "
            f"reason={verdict.reason}"
        )

        # 验证 4: 通过 history[-1].gate_results 仍可读到 Verdict.message
        # 这是 P0.4 的核心 — 用户能查到失败原因
        failed_messages = [
            (name, v.message)
            for name, v in latest.gate_results.items()
            if not v.passed
        ]
        assert len(failed_messages) >= 1, "expected at least 1 failed gate"
        assert any("intentional" in msg for _, msg in failed_messages), (
            f"fake_failing message not in failed_messages: {failed_messages}"
        )

        print(
            f"  verdict: level={verdict.level} (should_stop={verdict.should_stop}), "
            f"reason={verdict.reason[:80]}"
        )
        print(f"  failed gates: {failed_messages}")
        print("P0.4 runtime smoke PASS: RoundHistory 保留 Verdict.message")
        return 0


if __name__ == "__main__":
    raise SystemExit(main())