"""设计输入进入 Loop 前的确定性结构检查。"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from auto_engineering.engine.design_doc import DesignDoc
from auto_engineering.loop.actions import ErrorResponse, build_terminal_acceptance_summary
from auto_engineering.loop.design_decision_ledger import DesignDecisionLedger

DESIGN_STRUCTURE_PREFLIGHT_REQUIRED = "DESIGN_STRUCTURE_PREFLIGHT_REQUIRED"


@dataclass(frozen=True, slots=True)
class DesignPreflight:
    """只描述设计输入是否具备进入 Gap Scan 的最小结构。"""

    valid: bool
    reason_code: str | None
    section_count: int
    parse_warnings: tuple[str, ...]

    def to_dict(self) -> dict[str, object]:
        value: dict[str, object] = {
            "valid": self.valid,
            "section_count": self.section_count,
            "parse_warnings": list(self.parse_warnings),
        }
        if self.reason_code is not None:
            value["reason_code"] = self.reason_code
        return value


def inspect_design_doc(design_doc: DesignDoc) -> DesignPreflight:
    """拒绝完全没有可识别层次的设计文档，避免先启动 Gap Scan Worker。

    H2-only 文档仍是当前兼容设计输入：EngineeringModel 会把 plate 投影为
    一个可扫描章节。只有完全没有 plate（也没有有效 ae 标记）才属于首轮
    无法由模型可靠修复的输入前置条件。
    """

    if design_doc.plates:
        return DesignPreflight(
            valid=True,
            reason_code=None,
            section_count=sum(
                max(1, len(plate.components)) for plate in design_doc.plates
            ),
            parse_warnings=tuple(design_doc.parse_warnings),
        )
    return DesignPreflight(
        valid=False,
        reason_code=DESIGN_STRUCTURE_PREFLIGHT_REQUIRED,
        section_count=0,
        parse_warnings=tuple(design_doc.parse_warnings),
    )


def prepare_design_ledger(
    project_root: Path,
    design_doc_path: Path,
    design_doc: DesignDoc,
) -> DesignDecisionLedger:
    if inspect_design_doc(design_doc).valid:
        return DesignDecisionLedger.ensure_intake(project_root, design_doc_path)
    return DesignDecisionLedger(())


def build_design_structure_preflight_gate(
    stage: str,
    design_doc: DesignDoc | None,
) -> dict[str, object] | None:
    if stage != "gap_scan" or design_doc is None:
        return None
    preflight = inspect_design_doc(design_doc)
    if preflight.valid:
        return None
    return {
        "id": "design_structure_preflight",
        "type": "manual",
        "reason_code": DESIGN_STRUCTURE_PREFLIGHT_REQUIRED,
        "question": (
            "设计文档没有可识别的 H2/H3 或 ae 层次，不能启动 Gap Scan。"
            "请修复设计文档后重新初始化当前 Loop。"
        ),
        "options": [
            {
                "label": "修复设计文档后重新初始化",
                "meaning": "停止当前 Loop，修复文档后重新执行 --init",
                "enabled": True,
            },
            {
                "label": "终止 loop",
                "meaning": "放弃本次设计驱动运行",
                "enabled": True,
            },
        ],
        "default": "修复设计文档后重新初始化",
        "design_preflight": preflight.to_dict(),
    }


def resolve_design_structure_preflight_gate(
    active_action: object,
    gate_resolution: Mapping[str, Any],
    state: Any,
) -> dict[str, Any]:
    gate_id = gate_resolution.get("gate_id", "")
    resolution = gate_resolution.get("resolution", "")
    active_gate = (
        active_action.get("gate", {})
        if isinstance(active_action, Mapping) else {}
    )
    if not isinstance(active_gate, Mapping) or active_gate.get("id") != gate_id:
        return ErrorResponse(
            error_code="INVALID_GATE_RESOLUTION",
            message="design_structure_preflight 不是当前 active Gate",
        ).to_dict()
    if resolution not in {"修复设计文档后重新初始化", "终止 loop"}:
        return ErrorResponse(
            error_code="INVALID_GATE_RESOLUTION",
            message=(
                "design_structure_preflight 只接受‘修复设计文档后重新初始化’"
                "或‘终止 loop’"
            ),
        ).to_dict()
    return {
        "action": "done",
        "verdict": "TERMINATED",
        "message": (
            "设计文档结构未通过首轮前置检查；请修复文档后重新执行 --init。"
            if resolution == "修复设计文档后重新初始化"
            else "用户终止本次 Loop"
        ),
        "stage": state.current_stage,
        "tick": state.tick + 1,
        "thread_id": state.thread_id,
        "acceptance_summary": build_terminal_acceptance_summary(
            state, verdict="TERMINATED"
        ),
    }


__all__ = [
    "DESIGN_STRUCTURE_PREFLIGHT_REQUIRED",
    "DesignPreflight",
    "build_design_structure_preflight_gate",
    "inspect_design_doc",
    "prepare_design_ledger",
    "resolve_design_structure_preflight_gate",
]
