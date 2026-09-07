"""EngineState 字段写入的确定性校验策略。"""

_VALID_VERDICTS = frozenset({"", "APPROVE", "MAJOR"})
_VALID_STAGES = frozenset({
    "", "project_setup", "gap_scan", "gap_review", "research", "architect",
    "developer", "critic", "component_verifier", "plate_deep_audit",
    "system_verifier", "system_deep_audit", "plan_refine",
})


def validate_field_value(name: str, value: object) -> None:
    """校验 EngineState 字段值是否合法。"""

    if name == "critic_verdict" and value not in _VALID_VERDICTS:
        raise ValueError(
            f"critic_verdict 非法值 '{value}'. 合法值: {sorted(_VALID_VERDICTS)}"
        )
    if name == "current_stage" and value not in _VALID_STAGES:
        raise ValueError(
            f"current_stage 非法值 '{value}'. 合法值: {sorted(_VALID_STAGES)}"
        )
    if name == "round" and not isinstance(value, int):
        raise ValueError(f"round 必须是 int, 收到 {type(value).__name__}")
    if name in (
        "majors_in_a_row", "total_majors", "plan_refine_count", "tick",
        "repair_cycle_count", "unchanged_finding_streak",
    ):
        if not isinstance(value, int):
            raise ValueError(f"{name} 必须是 int, 收到 {type(value).__name__}")
        if value < 0:
            raise ValueError(f"{name} 不能为负数, 收到 {value}")


__all__ = ["validate_field_value"]
