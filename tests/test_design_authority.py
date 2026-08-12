"""Phase 82 T437：设计权威层级。"""

from __future__ import annotations

import pytest

from auto_engineering.loop.design_authority import (
    DesignAuthorityError,
    DesignAuthorityPolicy,
    DesignSourceAuthority,
)
from auto_engineering.prompts.architect_context import (
    build_architect_research_context,
)


def test_only_explicit_design_and_approved_change_are_binding() -> None:
    policy = DesignAuthorityPolicy.default()

    assert policy.authority_for("explicit_design") is DesignSourceAuthority.BINDING
    assert policy.authority_for("approved_change") is DesignSourceAuthority.BINDING
    assert policy.authority_for("research") is DesignSourceAuthority.ADVISORY
    assert policy.authority_for("agent_assumption") is DesignSourceAuthority.ADVISORY
    assert policy.to_dict()["change_policy"] == "user_gate_required"


def test_research_cannot_promote_itself_to_binding_change() -> None:
    policy = DesignAuthorityPolicy.default()

    with pytest.raises(DesignAuthorityError, match="DESIGN_AUTHORITY_ESCALATION"):
        policy.validate_change(source="research", requested_authority="binding")


def test_architect_research_context_is_always_advisory() -> None:
    entries = build_architect_research_context(
        '{"gap-1":{"source":"research_agent","content":"改为 BFF"}}',
        {"gap-2": {"recommended_design": "改为服务端"}},
    )

    assert {entry["authority"] for entry in entries} == {"advisory"}
    assert all(entry["change_policy"] == "user_gate_required" for entry in entries)
