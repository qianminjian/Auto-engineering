"""公开 Host Execution Package 经真实 operations 到终态的纵向验收。"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any

import pytest
from click.testing import CliRunner

import auto_engineering.cli.dev_loop as dev_loop_module
from auto_engineering.cli import main
from auto_engineering.host import backends
from auto_engineering.host import supervisor as supervisor_module
from auto_engineering.host.invocation import (
    ActionExecutionReceipt,
    ActionExecutionRequest,
    HostInvocationProbe,
)


def _prompt_context(prompt: str) -> dict[str, Any]:
    marker = "## 本次任务上下文（编排器注入，禁止自行虚构）"
    if marker not in prompt:
        return {}
    encoded = prompt.split(marker, 1)[1].split("```json", 1)[1].split("```", 1)[0]
    value = json.loads(encoded)
    assert isinstance(value, dict)
    return value


class _PackageOnlyBackend:
    """不接触 Canonical Action，只消费 ActionExecutionRequest 引用的公开资产。"""

    def __init__(self, project_root: Path, *, backend: str) -> None:
        self.root = project_root
        self.backend = backend
        self.invocations = 0
        self.critic_runs = 0

    def probe(self) -> HostInvocationProbe:
        return HostInvocationProbe.available(self.backend)

    def cancel(self, host_context_id: str) -> None:
        raise AssertionError(host_context_id)

    def execute(self, request: ActionExecutionRequest) -> ActionExecutionReceipt:
        self.invocations += 1
        assert ("edit" in request.allowed_tools) is (
            request.stage in {"project_setup", "developer"}
        )
        envelope = json.loads(
            (self.root / request.compact_envelope_ref).read_text(encoding="utf-8")
        )
        coordinator = self.root / request.work_files["coordinator_result"]
        outcomes = self.root / request.work_files["outcomes"]
        coordinator.parent.mkdir(parents=True, exist_ok=True)
        workers = envelope.get("host_execution", {}).get("workers", [])
        recovery_refs = envelope.get("host_execution", {}).get(
            "recovery", {}
        ).get("semantic_context_refs", [])
        prompt_ref = (
            workers[0]["prompt_ref"] if workers
            else recovery_refs[0] if recovery_refs
            else request.coordinator_ref
        )
        prompt = (self.root / prompt_ref).read_text(encoding="utf-8")
        context = _prompt_context(prompt)
        payload = self._payload(request.stage, context)
        if workers:
            coordinator.write_text(
                json.dumps(payload, ensure_ascii=False), encoding="utf-8"
            )
            native = [{
                "worker_id": worker["worker_id"],
                "native_worker_handle": f"{self.backend}-{self.invocations}-{index}",
                "status": "completed",
                "payload": payload,
                "summary": "deterministic product trajectory",
                "actual_model": "deterministic-host",
                "isolation_evidence": (
                    "fork_context=false" if self.backend == "codex" else "fresh_context"
                ),
            } for index, worker in enumerate(workers)]
            outcomes.write_text(
                json.dumps({"outcomes": native}, ensure_ascii=False),
                encoding="utf-8",
            )
        else:
            coordinator.write_text(
                json.dumps(payload, ensure_ascii=False), encoding="utf-8"
            )
            recovery = envelope.get("host_execution", {}).get("recovery")
            if not isinstance(recovery, dict) or not recovery.get(
                "semantic_context_refs"
            ):
                outcomes.write_text('{"outcomes":[]}', encoding="utf-8")
        digests = {
            key: hashlib.sha256((self.root / relative).read_bytes()).hexdigest()
            for key, relative in request.work_files.items()
            if key != "result" and (self.root / relative).is_file()
        }
        return ActionExecutionReceipt.from_dict({
            "schema_version": "1.0",
            "thread_id": request.thread_id,
            "action_message_id": request.action_message_id,
            "build_id": request.build_id,
            "host_context_id": f"context-{self.backend}-{self.invocations}",
            "backend": self.backend,
            "status": "completed",
            "exit_code": 0,
            "work_file_digests": digests,
            "usage": {"input_tokens": 10, "cached_input_tokens": 0, "output_tokens": 10},
        })

    def _payload(self, stage: str, context: dict[str, Any]) -> dict[str, Any]:
        if stage == "project_setup":
            (self.root / "src").mkdir(exist_ok=True)
            (self.root / "tests").mkdir(exist_ok=True)
            (self.root / "package.json").write_text(json.dumps({
                "scripts": {
                    "test": "node -e \"console.log('1 test passed')\"",
                    "lint": "node -e \"console.log('lint passed')\"",
                    "typecheck": "node -e \"console.log('typecheck passed')\"",
                    "build": "node -e \"console.log('build passed')\"",
                },
                "devDependencies": {"typescript": "^5.0.0"},
            }), encoding="utf-8")
            return {"result_type": "project_setup_completed", "artifacts": [
                "package.json", "src", "tests",
            ]}
        if stage == "gap_scan":
            return {"gaps": [], "section_findings": [{
                "section_ref": item["section_ref"],
                "verdict": "clear",
                "evidence": ["设计章节已给出可验证要求"],
            } for item in context["host_design_sections"]]}
        if stage == "architect":
            plate = context["valid_plate_keys"][0]
            return {
                "plan": (
                    "严格保持设计中的页面职责、接口边界和验证要求，"
                    "先完成最小实现及单元测试，再执行独立审查、组件验证、"
                    "板块审计和系统级验证，发现问题时回到对应批次修复。"
                ),
                "batch_plan": [{
                    "batch_id": "B1", "batch_title": "实现页面",
                    "plate_keys": [plate], "design_sections": ["§C1"],
                    "tasks": [{
                        "id": "B1-T1", "description": "实现页面",
                        "kind": "implementation", "module_ref": "src/page.ts",
                        "file_targets": ["src/page.ts"],
                    }], "depends_on": [],
                }],
                "file_list": ["src/page.ts"], "contracts": {},
            }
        if stage == "developer":
            (self.root / "src/page.ts").write_text("export const page = true;\n")
            (self.root / "tests/page.test.ts").write_text(
                "import { page } from '../src/page';\nvoid page;\n",
                encoding="utf-8",
            )
            return {
                "batch_id": context["batch_id"],
                "files_changed": ["src/page.ts", "tests/page.test.ts"],
                "commit_hash": "", "test_results": {"passed": 1, "failed": 0, "total": 1},
                "red_evidence": ["先失败后通过"],
            }
        if stage == "critic":
            self.critic_runs += 1
            if self.critic_runs == 1:
                return {"verdict": "MAJOR", "findings": [{
                    "severity": "P1", "file": "src/page.ts",
                    "issue": "缺少边界回归", "suggestion": "补齐回归测试",
                }], "critic_feedback": "修复后重新审查"}
            return {"verdict": "APPROVE", "findings": [],
                    "critic_feedback": "实现符合设计"}
        if stage == "component_verifier":
            return {"component": context["component"], "coverage_map": [{
                "design_item": "§C1", "status": "IMPLEMENTED",
                "file": "src/page.ts", "line": 1, "note": "",
            }], "missing_count": 0, "diverged_count": 0}
        if stage == "plate_deep_audit":
            return {"plate": context["plate"], "findings": [], "p0_count": 0,
                    "p1_count": 0, "p2_count": 0, "cross_component_issues": [],
                    "total_audited_files": 1}
        if stage == "system_verifier":
            return {"full_coverage_map": [{"design_section": "§C1",
                                            "status": "IMPLEMENTED"}],
                    "total_design_items": 1, "covered_count": 1,
                    "missing_count": 0, "diverged_count": 0}
        if stage == "system_deep_audit":
            return {"findings": [], "p0_count": 0, "p1_count": 0, "p2_count": 0,
                    "total_audited_files": 1, "design_docs_stale": False,
                    "design_doc_suggestions": "", "missing_count": 0,
                    "diverged_count": 0}
        raise AssertionError(f"unexpected stage: {stage}")


@pytest.mark.parametrize("backend", ["codex", "claude"])
def test_public_execution_package_reaches_terminal_through_real_operations(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, backend: str,
) -> None:
    """禁止 FakeOperations、Canonical context 和手工 Tick 拼接。"""

    design = tmp_path / "design.md"
    design.write_text("## B1 页面\n\n### C1 实现\n\n实现页面并测试。\n", encoding="utf-8")
    runner = CliRunner()
    initialized = runner.invoke(main, [
        "dev-loop", "--init", "严格按设计实现", "--design-doc", str(design),
        "--project-root", str(tmp_path),
    ])
    assert initialized.exit_code == 0, initialized.output

    fake = _PackageOnlyBackend(tmp_path, backend=backend)
    monkeypatch.setattr(
        dev_loop_module,
        "detect_host",
        lambda: type("Detection", (), {"platform": (
            dev_loop_module.HostPlatform.CODEX
            if backend == "codex" else dev_loop_module.HostPlatform.CLAUDE_CODE
        )})(),
        raising=False,
    )
    backend_name = "CodexInvocationBackend" if backend == "codex" else "ClaudeInvocationBackend"
    monkeypatch.setattr(backends, backend_name, lambda **_: fake)
    # 源码工作树没有 packaged build-info；制品身份由独立 archive 验收覆盖。
    evidence = tmp_path / ".ae-state/reports/offline-product-evidence.json"
    evidence.parent.mkdir(parents=True, exist_ok=True)
    evidence.write_text("{}", encoding="utf-8")
    monkeypatch.setattr(
        supervisor_module.ProductEvidenceArtifactJournal,
        "record_terminal",
        lambda self, **kwargs: evidence,
    )

    host_env = {
        "AE_HOST_PLATFORM": "codex" if backend == "codex" else "claude-code",
        "CODEX_THREAD_ID": "test-host-session" if backend == "codex" else "",
        "CLAUDE_CODE_SESSION_ID": "test-host-session" if backend == "claude" else "",
    }
    result = runner.invoke(main, [
        "dev-loop", "--supervise", "--project-root", str(tmp_path),
    ], env=host_env)

    assert result.exit_code == 0, result.output
    final = json.loads([line for line in result.output.splitlines() if line.startswith("{")][-1])
    assert final["action"] == "done"
    assert final["verdict"] == "GOAL_ACHIEVED"
    assert fake.critic_runs == 2
    assert fake.invocations >= 8
