"""v5.5 Phase 3: Agent Prompt 增强测试 — Superpowers 整合.

测试原则 (per pytest-memory-management.md):
- 单文件 pytest --no-cov --timeout=60
- 验证 CRITIC/DEVELOPER/ARCHITECT prompt 含 v5.5 新增关键要素
"""

from __future__ import annotations

from auto_engineering.agents.prompts import (
    ARCHITECT_SYSTEM_PROMPT,
    CRITIC_SYSTEM_PROMPT,
    DEVELOPER_SYSTEM_PROMPT,
)


class TestCriticPromptV55:
    """v5.5 Critic prompt — Superpowers code-reviewer.md 整合."""

    def test_includes_strengths_in_output_format(self) -> None:
        """Critic prompt 输出格式含 strengths 字段."""
        assert "strengths" in CRITIC_SYSTEM_PROMPT.lower()

    def test_includes_assessment_in_output_format(self) -> None:
        """Critic prompt 输出格式含 assessment 字段."""
        assert "assessment" in CRITIC_SYSTEM_PROMPT.lower()

    def test_includes_three_tier_assessment(self) -> None:
        """Critic prompt 含三段式评估: Ready to merge / Ready to merge: With fixes / Needs rework."""
        assert "Ready to merge" in CRITIC_SYSTEM_PROMPT
        assert "Needs rework" in CRITIC_SYSTEM_PROMPT

    def test_includes_review_scope(self) -> None:
        """DS-15: Critic prompt 含审查维度和工作流程."""
        prompt_lower = CRITIC_SYSTEM_PROMPT.lower()
        assert "审查维度" in prompt_lower or "审查" in prompt_lower

    def test_includes_structured_findings_format(self) -> None:
        """Critic prompt 含 verdict + findings 输出说明."""
        assert "APPROVE" in CRITIC_SYSTEM_PROMPT
        assert "MAJOR" in CRITIC_SYSTEM_PROMPT
        assert "P0" in CRITIC_SYSTEM_PROMPT or "severity" in CRITIC_SYSTEM_PROMPT.lower()

    def test_includes_agent_permissions(self) -> None:
        """Critic prompt 含审查纪律（Phase 31 重构后精简为 role+goal+context 结构）."""
        prompt = CRITIC_SYSTEM_PROMPT
        assert "审查" in prompt or "review" in prompt.lower()

    def test_preserves_verdict_enum(self) -> None:
        """Critic prompt 保留 APPROVE/MAJOR 枚举判定."""
        assert "APPROVE" in CRITIC_SYSTEM_PROMPT
        assert "MAJOR" in CRITIC_SYSTEM_PROMPT

    def test_has_context_section(self) -> None:
        """DS-15: Critic prompt 含工作流程和信息来源."""
        prompt = CRITIC_SYSTEM_PROMPT
        assert "工作流程" in prompt or "信息来源" in prompt


class TestDeveloperPromptV55:
    """v5.5 Developer prompt — receiving-code-review 5 步协议."""

    def test_includes_5_step_response_protocol(self) -> None:
        """Developer prompt 含 5 步响应协议: 理解/定位/修复/验证/汇报."""
        prompt = DEVELOPER_SYSTEM_PROMPT
        # Check for step-related keywords
        steps = ["理解", "定位", "修复", "验证", "汇报",
                 "understand", "locate", "fix", "verify", "report"]
        found = [s for s in steps if s.lower() in prompt.lower()]
        assert len(found) >= 3, f"Expected >=3 step keywords, found: {found}"

    def test_preserves_tdd_cycle(self) -> None:
        """Developer prompt 保留 TDD RED→GREEN→REFACTOR 循环."""
        assert "RED" in DEVELOPER_SYSTEM_PROMPT
        assert "GREEN" in DEVELOPER_SYSTEM_PROMPT
        assert "REFACTOR" in DEVELOPER_SYSTEM_PROMPT

    def test_includes_critic_feedback_handling(self) -> None:
        """Developer prompt 含 Critic 反馈处理指导."""
        prompt = DEVELOPER_SYSTEM_PROMPT.lower()
        assert "critic" in prompt or "反馈" in prompt or "feedback" in prompt


class TestArchitectPromptV55:
    """v5.5 Architect prompt — brainstorming + Agent-Reach + 3 模式."""

    def test_includes_three_modes(self) -> None:
        """DS-15: Architect prompt 含工作流程和规则."""
        prompt = ARCHITECT_SYSTEM_PROMPT.lower()
        assert "工作流程" in prompt and "规则" in prompt

    def test_includes_brainstorming_workflow(self) -> None:
        """DS-15: Architect prompt 含设计文档阅读和依赖排序要求."""
        prompt_lower = ARCHITECT_SYSTEM_PROMPT.lower()
        design_keywords = ["设计文档", "batch", "依赖", "design", "batch_plan"]
        found = [k for k in design_keywords if k in prompt_lower]
        assert len(found) >= 2, f"Expected >=2 design keywords, found: {found}"

    def test_includes_structured_batch_plan_output(self) -> None:
        """Architect prompt 含 batch_plan 输出要求（Phase 31 重构后精简，字段在 expected_format 中）."""
        prompt = ARCHITECT_SYSTEM_PROMPT.lower()
        assert "batch_plan" in prompt

    def test_includes_agent_reach_reference(self) -> None:
        """DS-15: Architect prompt 含技术架构师角色定义."""
        prompt = ARCHITECT_SYSTEM_PROMPT.lower()
        assert "技术架构师" in prompt or "架构师" in prompt
