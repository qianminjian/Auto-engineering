"""Phase 80 T409：审计 revision 作用域脱离兼容 façade。"""

from __future__ import annotations

from auto_engineering.engine.batch_state import BatchState
from auto_engineering.engine.state import EngineState
from auto_engineering.loop.audit_revision import AuditRevisionService


def test_plate_audit_key_is_scoped_to_current_plate(tmp_path) -> None:
    batch_state = BatchState.from_batch_plan([
        {"batch_id": "B1", "plate": "Platform", "component": "Core", "tasks": []}
    ])
    service = AuditRevisionService(tmp_path)

    assert service.key("plate_deep_audit", batch_state) == (
        "plate_deep_audit:(single)"
    )
    assert service.key("system_deep_audit", batch_state) == "system_deep_audit"


def test_fingerprint_is_stable_for_same_projection(tmp_path) -> None:
    state = EngineState(thread_id="thread-1")
    state.files_changed = ["src/core.py"]
    service = AuditRevisionService(tmp_path)

    first = service.fingerprint("system_deep_audit", state, None)
    second = service.fingerprint("system_deep_audit", state, None)

    assert first == second
