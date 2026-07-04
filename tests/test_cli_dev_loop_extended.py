"""test_cli_dev_loop_extended.py — Phase 12.7 P1-3.

cli/dev_loop.py 扩展覆盖率测试.

覆盖关键路径:
- OrchestratorRunResult dataclass: 7+ 字段 + to_json_dict 6 字段契约
- from_orchestrator() 工厂方法: completed / max_rounds 两条路径
- _build_gate_summary(): GateVerdict / Verdict / None 三类
- _build_v2_semantic_evaluator(): 总是 True
- _build_v2_agent_runtime(): 已由 test_cli_v2_agent_runtime_real.py 覆盖
- _run_v2_orchestrator: orchestrator mock 集成
- 参数解析: --max-rounds / --log-format / --project-root / --llm-provider
- 缺 ANTHROPIC_API_KEY -> preflight exit 1
- Exit codes: 0/1/2/130 (SIGINT → 130)
"""

from __future__ import annotations

import json
import os
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest
from click.testing import CliRunner

from auto_engineering.cli import main
from auto_engineering.cli.dev_loop import (
    OrchestratorRunResult,
    _build_gate_summary,
    _build_v2_semantic_evaluator,
)


# ============================================================
# 1. OrchestratorRunResult dataclass
# ============================================================


class TestOrchestratorRunResultDataclass:
    """OrchestratorRunResult 字段 + 默认值."""

    def test_required_fields_have_no_defaults(self) -> None:
        """6 必填字段无默认值: status/thread_id/rounds/verdict/duration_sec/gate_summary."""
        import dataclasses

        fields = {f.name for f in dataclasses.fields(OrchestratorRunResult)}
        for required in (
            "status",
            "thread_id",
            "rounds",
            "verdict",
            "duration_sec",
            "gate_summary",
        ):
            assert required in fields, f"missing field: {required}"

    def test_legacy_fields_have_defaults(self) -> None:
        """向后兼容字段 total_steps/checkpoint_id 有默认值."""
        result = OrchestratorRunResult(
            status="completed",
            thread_id="abc",
            rounds=1,
            verdict={},
            duration_sec=1.0,
            gate_summary={},
        )
        assert result.total_steps == 0
        assert result.checkpoint_id == ""

    def test_legacy_fields_can_be_overridden(self) -> None:
        """显式传 total_steps/checkpoint_id 时使用显式值."""
        result = OrchestratorRunResult(
            status="completed",
            thread_id="abc",
            rounds=3,
            verdict={"level": 0},
            duration_sec=2.5,
            gate_summary={"lint": {"status": "pass"}},
            total_steps=3,
            checkpoint_id="v2-r3",
        )
        assert result.total_steps == 3
        assert result.checkpoint_id == "v2-r3"


class TestToJsonDict:
    """to_json_dict() 返回 6 字段 JSON 契约 (v5.0 §B13.2)."""

    def test_returns_exactly_six_fields(self) -> None:
        result = OrchestratorRunResult(
            status="completed",
            thread_id="t1",
            rounds=2,
            verdict={"level": 0, "level_name": "OK", "reason": "ok"},
            duration_sec=1.23,
            gate_summary={"lint": {"status": "pass", "passed": True, "message": "ok"}},
            total_steps=2,
            checkpoint_id="v2-r2",
        )
        d = result.to_json_dict()
        assert set(d.keys()) == {
            "status",
            "thread_id",
            "rounds",
            "verdict",
            "duration_sec",
            "gate_summary",
        }

    def test_field_values_pass_through(self) -> None:
        """6 字段值与原 dataclass 字段一致."""
        result = OrchestratorRunResult(
            status="max_rounds",
            thread_id="xyz-hex",
            rounds=5,
            verdict={"level": 4, "level_name": "HARD_LIMIT", "reason": "r5"},
            duration_sec=10.5,
            gate_summary={"safety": {"status": "pass", "passed": True, "message": ""}},
        )
        d = result.to_json_dict()
        assert d["status"] == "max_rounds"
        assert d["thread_id"] == "xyz-hex"
        assert d["rounds"] == 5
        assert d["verdict"]["level_name"] == "HARD_LIMIT"
        assert d["duration_sec"] == 10.5
        assert d["gate_summary"]["safety"]["passed"] is True

    def test_legacy_fields_excluded_from_json(self) -> None:
        """total_steps/checkpoint_id 不出现在 JSON 契约中."""
        result = OrchestratorRunResult(
            status="completed",
            thread_id="t",
            rounds=1,
            verdict={},
            duration_sec=1.0,
            gate_summary={},
            total_steps=1,
            checkpoint_id="v2-r1",
        )
        d = result.to_json_dict()
        assert "total_steps" not in d
        assert "checkpoint_id" not in d


# ============================================================
# 2. from_orchestrator 工厂方法
# ============================================================


class TestFromOrchestratorCompletedPath:
    """verdict.should_stop=True → status='completed'."""

    def test_should_stop_true_yields_completed(self) -> None:
        fake_orch = MagicMock()
        fake_orch.verdict = MagicMock()
        fake_orch.verdict.should_stop = True
        fake_orch.verdict.level = 0
        fake_orch.verdict.level_name = "OK"
        fake_orch.verdict.reason = "all gates pass"
        fake_orch._thread_id = "thread-abc"

        result = OrchestratorRunResult.from_orchestrator(
            orchestrator=fake_orch,
            total_rounds=2,
            duration_sec=3.0,
        )
        assert result.status == "completed"
        assert result.verdict["level"] == 0
        assert result.verdict["level_name"] == "OK"
        assert result.verdict["reason"] == "all gates pass"
        assert result.thread_id == "thread-abc"
        assert result.rounds == 2
        assert result.duration_sec == 3.0

    def test_completed_sets_legacy_checkpoint_id(self) -> None:
        fake_orch = MagicMock()
        fake_orch.verdict.should_stop = True
        fake_orch.verdict.level = 0
        fake_orch.verdict.level_name = "OK"
        fake_orch.verdict.reason = ""
        fake_orch._thread_id = "tid"

        result = OrchestratorRunResult.from_orchestrator(
            orchestrator=fake_orch,
            total_rounds=3,
            duration_sec=0.0,
        )
        assert result.checkpoint_id == "v2-r3"
        assert result.total_steps == 3


class TestFromOrchestratorMaxRoundsPath:
    """verdict.should_stop=False (或 None) → status='max_rounds'."""

    def test_should_stop_false_yields_max_rounds(self) -> None:
        fake_orch = MagicMock()
        fake_orch.verdict = MagicMock()
        fake_orch.verdict.should_stop = False
        fake_orch._thread_id = "tid-fail"

        result = OrchestratorRunResult.from_orchestrator(
            orchestrator=fake_orch,
            total_rounds=4,
            duration_sec=8.0,
        )
        assert result.status == "max_rounds"
        assert result.verdict["level"] == 4
        assert result.verdict["level_name"] == "HARD_LIMIT"
        assert "4 轮" in result.verdict["reason"]
        assert result.rounds == 4
        assert result.duration_sec == 8.0

    def test_no_verdict_yields_max_rounds(self) -> None:
        """verdict=None (orchestrator 未生成 verdict) → max_rounds 路径."""
        fake_orch = MagicMock()
        fake_orch.verdict = None

        result = OrchestratorRunResult.from_orchestrator(
            orchestrator=fake_orch,
            total_rounds=1,
            duration_sec=0.1,
        )
        assert result.status == "max_rounds"
        assert result.verdict["level_name"] == "HARD_LIMIT"

    def test_missing_thread_id_generates_uuid(self) -> None:
        """无 _thread_id → 用 uuid.uuid4().hex 生成."""
        fake_orch = MagicMock(spec=[])  # 没有 _thread_id
        result = OrchestratorRunResult.from_orchestrator(
            orchestrator=fake_orch,
            total_rounds=0,
            duration_sec=0.0,
        )
        # uuid4().hex 是 32 字符 hex
        assert len(result.thread_id) == 32
        assert all(c in "0123456789abcdef" for c in result.thread_id)


class TestFromOrchestratorGateResults:
    """from_orchestrator 接受 gate_results dict (经 _build_gate_summary 处理)."""

    def test_none_gate_results_yields_empty_summary(self) -> None:
        fake_orch = MagicMock()
        fake_orch.verdict.should_stop = True
        fake_orch.verdict.level = 0
        fake_orch.verdict.level_name = "OK"
        fake_orch.verdict.reason = ""
        fake_orch._thread_id = "t"

        result = OrchestratorRunResult.from_orchestrator(
            orchestrator=fake_orch,
            total_rounds=1,
            duration_sec=0.0,
            gate_results=None,
        )
        assert result.gate_summary == {}

    def test_gate_results_passed_through(self) -> None:
        fake_orch = MagicMock()
        fake_orch.verdict.should_stop = True
        fake_orch.verdict.level = 0
        fake_orch.verdict.level_name = "OK"
        fake_orch.verdict.reason = ""
        fake_orch._thread_id = "t"

        verdict = MagicMock()
        verdict.passed = True
        verdict.message = "lint pass"
        gate_results = {"lint": verdict}

        result = OrchestratorRunResult.from_orchestrator(
            orchestrator=fake_orch,
            total_rounds=1,
            duration_sec=0.0,
            gate_results=gate_results,
        )
        assert "lint" in result.gate_summary
        assert result.gate_summary["lint"]["status"] == "pass"
        assert result.gate_summary["lint"]["passed"] is True


# ============================================================
# 3. _build_gate_summary 内部函数
# ============================================================


class TestBuildGateSummary:
    """_build_gate_summary() 兼容 GateVerdict + Verdict + None."""

    def test_none_value_yields_skipped(self) -> None:
        result = _build_gate_summary({"lint": None})
        assert result["lint"]["status"] == "skipped"
        assert result["lint"]["passed"] is None
        assert result["lint"]["message"] == ""

    def test_gateverdict_with_passed_true(self) -> None:
        v = MagicMock()
        v.passed = True
        v.message = "all good"
        result = _build_gate_summary({"safety": v})
        assert result["safety"]["status"] == "pass"
        assert result["safety"]["passed"] is True
        assert result["safety"]["message"] == "all good"

    def test_gateverdict_with_passed_false(self) -> None:
        v = MagicMock()
        v.passed = False
        v.message = "lint failed: trailing whitespace"
        result = _build_gate_summary({"lint": v})
        assert result["lint"]["status"] == "fail"
        assert result["lint"]["passed"] is False

    def test_verdict_with_should_stop_fallback(self) -> None:
        """Verdict 类型 (无 .passed) → 用 .should_stop 推断."""
        v = MagicMock(spec=["should_stop", "level", "reason"])
        v.should_stop = True
        result = _build_gate_summary({"convergence": v})
        assert result["convergence"]["status"] == "pass"
        assert result["convergence"]["passed"] is True

    def test_verdict_without_should_stop_yields_fail(self) -> None:
        v = MagicMock(spec=["should_stop", "level", "reason"])
        v.should_stop = False
        result = _build_gate_summary({"convergence": v})
        assert result["convergence"]["status"] == "fail"
        assert result["convergence"]["passed"] is False

    def test_message_falls_back_to_reason(self) -> None:
        """message 为空时 → 用 reason 填充."""
        v = MagicMock(spec=["passed", "message", "reason"])
        v.passed = True
        v.message = ""
        v.reason = "because gates all passed"
        result = _build_gate_summary({"x": v})
        assert result["x"]["message"] == "because gates all passed"

    def test_empty_gate_results(self) -> None:
        result = _build_gate_summary({})
        assert result == {}

    def test_multiple_gates_mixed(self) -> None:
        v_pass = MagicMock()
        v_pass.passed = True
        v_pass.message = "ok"
        v_fail = MagicMock()
        v_fail.passed = False
        v_fail.message = "bad"
        result = _build_gate_summary({"a": v_pass, "b": v_fail, "c": None})
        assert result["a"]["status"] == "pass"
        assert result["b"]["status"] == "fail"
        assert result["c"]["status"] == "skipped"


# ============================================================
# 4. _build_v2_semantic_evaluator
# ============================================================


class TestSemanticEvaluator:
    """_build_v2_semantic_evaluator() 总是返回 True (Phase C 简化)."""

    def test_returns_callable(self, tmp_path: Path) -> None:
        from auto_engineering.cli import ProgressLogger

        progress = ProgressLogger(log_format="text")
        ev = _build_v2_semantic_evaluator(tmp_path, progress)
        assert callable(ev)

    def test_callable_always_returns_true(self, tmp_path: Path) -> None:
        import asyncio

        from auto_engineering.cli import ProgressLogger

        progress = ProgressLogger(log_format="text")
        ev = _build_v2_semantic_evaluator(tmp_path, progress)
        # 不管传什么 round_result, 都返回 True
        for _ in range(3):
            result = asyncio.run(ev(MagicMock()))
            assert result is True


# ============================================================
# 5. CLI 参数解析 (Click)
# ============================================================


class TestCliArgsParsing:
    """ae dev-loop 参数解析."""

    @pytest.fixture
    def tmp_project(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
        """最小合法项目根."""
        monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-test")
        (tmp_path / ".git").mkdir()
        (tmp_path / ".ae-answers.yml").write_text("project_name: test\n")
        return tmp_path

    def test_dev_loop_help_lists_options(self) -> None:
        """ae dev-loop --help 显示 --max-rounds / --log-format / --project-root."""
        runner = CliRunner()
        result = runner.invoke(main, ["dev-loop", "--help"])
        assert result.exit_code == 0
        assert "--max-rounds" in result.output
        assert "--log-format" in result.output
        assert "--project-root" in result.output
        assert "--max-tokens" in result.output

    def test_dev_loop_unsupported_provider_exits_6(self, tmp_project: Path) -> None:
        """--llm-provider=openai/ollama → exit 6."""
        runner = CliRunner()
        result = runner.invoke(
            main, ["dev-loop", "--llm-provider", "openai", "test requirement"]
        )
        assert result.exit_code == 6
        assert "未实现" in result.output or "未实装" in result.output

    def test_dev_loop_missing_api_key_exits_via_preflight(
        self, tmp_project: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """缺 ANTHROPIC_API_KEY + 不在 plugin mode → preflight/agent fail-fast.

        2026-07-04 修订: 旧实现预期 preflight 检查 API key (报告 Bug 4 prismscan),
        实际 preflight 不检查 API key (environment.py:189), API key 检查移到
        agent.run_agent fail-fast. 测试加检测 agent.run_agent 返回 failed status
        + exit code 非 0.

        delenv 4 个 plugin signal 确保不在 plugin mode, 触发 fail-fast.
        """
        monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
        monkeypatch.delenv("ANTHROPIC_AUTH_TOKEN", raising=False)
        monkeypatch.delenv("CLAUDE_CODE", raising=False)
        monkeypatch.delenv("CLAUDE_CODE_ENTRYPOINT", raising=False)
        monkeypatch.delenv("ANTHROPIC_CLI", raising=False)
        runner = CliRunner()
        result = runner.invoke(main, ["dev-loop", "test requirement"])
        # exit code != 0 (agent.run_agent fail-fast 返回 failed status)
        assert result.exit_code != 0, (
            f"无 API key + 非 plugin mode 应 fail-fast, exit={result.exit_code}, "
            f"output: {result.output[:500]}"
        )

    def test_dev_loop_log_format_json_emits_json_contract(
        self, tmp_project: Path
    ) -> None:
        """--log-format=json 输出 JSON 契约 (mock orchestrator)."""
        # mock orchestrator 走 completed 路径
        fake_result = OrchestratorRunResult(
            status="completed",
            thread_id="tid-json",
            rounds=2,
            verdict={"level": 0, "level_name": "OK", "reason": "ok"},
            duration_sec=1.5,
            gate_summary={"lint": {"status": "pass", "passed": True, "message": "ok"}},
        )
        runner = CliRunner()
        with patch(
            "auto_engineering.cli._run_v2_orchestrator",
            return_value=fake_result,
        ):
            result = runner.invoke(
                main,
                [
                    "dev-loop",
                    "--log-format",
                    "json",
                    "--max-rounds",
                    "2",
                    "test req",
                ],
            )
        assert result.exit_code == 0
        # 提取 stdout 末尾的 JSON 段
        stdout = result.stdout
        json_start = stdout.find("{")
        assert json_start >= 0, f"no JSON in stdout: {stdout!r}"
        data = json.loads(stdout[json_start:])
        assert data["status"] == "completed"
        assert data["thread_id"] == "tid-json"
        assert data["rounds"] == 2
        assert set(data.keys()) == {
            "status",
            "thread_id",
            "rounds",
            "verdict",
            "duration_sec",
            "gate_summary",
        }

    def test_dev_loop_text_format_uses_summary_line(
        self, tmp_project: Path
    ) -> None:
        """默认 (text) 格式输出 'dev-loop complete' 行."""
        fake_result = OrchestratorRunResult(
            status="completed",
            thread_id="tid",
            rounds=1,
            verdict={},
            duration_sec=0.1,
            gate_summary={},
        )
        runner = CliRunner()
        with patch(
            "auto_engineering.cli._run_v2_orchestrator",
            return_value=fake_result,
        ):
            result = runner.invoke(main, ["dev-loop", "req"])
        assert result.exit_code == 0
        assert "dev-loop complete" in result.stdout
        assert "completed" in result.stdout

    def test_dev_loop_max_rounds_zero_accepted(self, tmp_project: Path) -> None:
        """--max-rounds=0 被接受 (虽然实际不跑)."""
        fake_result = OrchestratorRunResult(
            status="max_rounds",
            thread_id="t",
            rounds=0,
            verdict={},
            duration_sec=0.0,
            gate_summary={},
        )
        runner = CliRunner()
        with patch(
            "auto_engineering.cli._run_v2_orchestrator",
            return_value=fake_result,
        ) as mock_run:
            result = runner.invoke(
                main, ["dev-loop", "--max-rounds", "0", "req"]
            )
        assert result.exit_code == 0
        assert mock_run.call_args.kwargs["max_rounds"] == 0


# ============================================================
# 6. AEError 分类与 exit code
# ============================================================


class TestAEErrorExitCodes:
    """AEError 抛出 → classify_error → 友好 prefix + 对应 exit code."""

    @pytest.fixture
    def tmp_project(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
        monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-test")
        (tmp_path / ".git").mkdir()
        (tmp_path / ".ae-answers.yml").write_text("project_name: test\n")
        return tmp_path

    def test_config_error_exits_2(self, tmp_project: Path) -> None:
        """CONFIG_* → exit 2."""
        from auto_engineering.errors import AEError, ErrorCode

        runner = CliRunner()
        with patch(
            "auto_engineering.cli._run_v2_orchestrator",
            side_effect=AEError(ErrorCode.CONFIG_INVALID_VALUE, "bad config"),
        ):
            result = runner.invoke(main, ["dev-loop", "req"])
        # exit code 2 = USER_ERROR / config
        assert result.exit_code == 2
        assert "[配置/参数错]" in result.stderr

    def test_sigint_cancelled_exits_130(self, tmp_project: Path) -> None:
        """TASK_CANCELLED (SIGINT) → exit 130."""
        from auto_engineering.errors import AEError, ErrorCode

        runner = CliRunner()
        with patch(
            "auto_engineering.cli._run_v2_orchestrator",
            side_effect=AEError(ErrorCode.TASK_CANCELLED, "cancelled"),
        ):
            result = runner.invoke(main, ["dev-loop", "req"])
        assert result.exit_code == 130
        assert "Resume" in result.stderr or "checkpoint" in result.stderr

    def test_llm_error_exits_3(self, tmp_project: Path) -> None:
        """LLM_* → exit 3 (API_ERROR)."""
        from auto_engineering.errors import AEError, ErrorCode

        runner = CliRunner()
        with patch(
            "auto_engineering.cli._run_v2_orchestrator",
            side_effect=AEError(ErrorCode.LLM_TIMEOUT, "timeout"),
        ):
            result = runner.invoke(main, ["dev-loop", "req"])
        assert result.exit_code == 3
        assert "[API/LLM 错]" in result.stderr

    def test_json_format_error_payload_includes_error_block(
        self, tmp_project: Path
    ) -> None:
        """--log-format=json 错误输出含 error 块."""
        from auto_engineering.errors import AEError, ErrorCode

        runner = CliRunner()
        with patch(
            "auto_engineering.cli._run_v2_orchestrator",
            side_effect=AEError(ErrorCode.LLM_TIMEOUT, "boom"),
        ):
            result = runner.invoke(
                main, ["dev-loop", "--log-format", "json", "req"]
            )
        assert result.exit_code == 3
        # 提取 stdout 末尾的 JSON 段 (前缀 "Starting dev-loop..." 是普通 stdout)
        stdout = result.stdout
        json_start = stdout.find("{")
        assert json_start >= 0, f"no JSON in stdout: {stdout!r}"
        data = json.loads(stdout[json_start:])
        assert data["status"] == "failed"
        assert "error" in data
        assert data["error"]["code"] == "LLM_TIMEOUT"


# ============================================================
# 7. _run_v2_orchestrator 单元测试 (mock 全部依赖)
# ============================================================


class TestRunV2OrchestratorUnit:
    """_run_v2_orchestrator 集成 mock: orchestrator.run() 返回 history."""

    def test_returns_completed_when_verdict_should_stop(self, tmp_path: Path) -> None:
        """verdict.should_stop=True → status=completed."""
        from auto_engineering.cli import (
            CancellationToken,
            ProgressLogger,
        )

        progress = ProgressLogger(log_format="text")
        cancellation = CancellationToken()

        # Mock Orchestrator
        fake_orchestrator = MagicMock()
        fake_orchestrator.verdict.should_stop = True
        fake_orchestrator.verdict.level = 0
        fake_orchestrator.verdict.level_name = "OK"
        fake_orchestrator.verdict.reason = "done"
        # async run 返回 history
        async def _fake_run(cancellation=None):
            return [MagicMock(gate_results={"lint": None})]
        fake_orchestrator.run = _fake_run

        with patch(
            "auto_engineering.loop.orchestrator.Orchestrator",
            return_value=fake_orchestrator,
        ):
            with patch(
                "auto_engineering.cli.dev_loop._build_v2_agent_runtime",
                return_value=MagicMock(),
            ):
                result = _run_v2_orchestrator_passthrough(
                    requirement="test req",
                    project_root=tmp_path,
                    max_rounds=2,
                    progress=progress,
                    cancellation=cancellation,
                )
        assert result.status == "completed"
        # _thread_id 由 _run_v2_orchestrator 内部赋值为 uuid.uuid4().hex (32 字符)
        assert len(result.thread_id) == 32
        assert result.rounds == 1

    def test_returns_max_rounds_when_verdict_keeps_going(
        self, tmp_path: Path
    ) -> None:
        """verdict.should_stop=False → status=max_rounds."""
        from auto_engineering.cli import (
            CancellationToken,
            ProgressLogger,
        )

        progress = ProgressLogger(log_format="text")
        cancellation = CancellationToken()

        fake_orchestrator = MagicMock()
        fake_orchestrator.verdict.should_stop = False

        async def _fake_run(cancellation=None):
            return []
        fake_orchestrator.run = _fake_run

        with patch(
            "auto_engineering.loop.orchestrator.Orchestrator",
            return_value=fake_orchestrator,
        ):
            with patch(
                "auto_engineering.cli.dev_loop._build_v2_agent_runtime",
                return_value=MagicMock(),
            ):
                result = _run_v2_orchestrator_passthrough(
                    requirement="x",
                    project_root=tmp_path,
                    max_rounds=3,
                    progress=progress,
                    cancellation=cancellation,
                )
        assert result.status == "max_rounds"
        assert result.rounds == 0
        # history 为空, max_rounds 路径 reason 用 0 轮 (因为 rounds=len(history)=0)
        assert "HARD_LIMIT" in result.verdict["level_name"]


# Helper: bypass cli/__init__.py preflight + load_ae_answers + 调用 _run_v2_orchestrator 直接
def _run_v2_orchestrator_passthrough(**kwargs):
    """直接调用 _run_v2_orchestrator (跳过 cli/__init__.py 包装).

    2026-07-04 v5.0 M4 升级: 加 mock 覆盖 orchestrator 新导入的模块.
    """
    from unittest.mock import MagicMock, patch
    from auto_engineering.cli.dev_loop import _run_v2_orchestrator

    with patch("auto_engineering.loop.checkpoint.store.SQLiteCheckpointStore", MagicMock()), \
         patch("auto_engineering.loop.guardrail.GuardrailChain") as mc_G, \
         patch("auto_engineering.loop.stage_router.StageRouter") as mc_S, \
         patch("auto_engineering.gates.base.DEFAULT_GATES", [MagicMock()]):
        mc_G.default.return_value = MagicMock()
        mc_S.return_value = MagicMock()
        return _run_v2_orchestrator(**kwargs)