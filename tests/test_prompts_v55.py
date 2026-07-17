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

    def test_includes_superpowers_review_dimensions(self) -> None:
        """Critic prompt 含 Superpowers 审查维度: 正确性/安全性/性能/可维护性/可读性."""
        prompt_lower = CRITIC_SYSTEM_PROMPT.lower()
        # At least 3 of the 5 dimensions should be present
        dimensions = ["正确性", "correctness", "安全性", "security",
                      "性能", "performance", "可维护性", "maintainability", "可读性", "readability"]
        found = [d for d in dimensions if d in prompt_lower]
        assert len(found) >= 3, f"Expected >=3 review dimensions, found: {found}"

    def test_includes_structured_findings_format(self) -> None:
        """Critic prompt 含结构化 findings 格式: file:line + severity(P0/P1/P2) + issue + suggested_fix."""
        assert "file:line" in CRITIC_SYSTEM_PROMPT.lower() or "file" in CRITIC_SYSTEM_PROMPT.lower()
        assert "P0" in CRITIC_SYSTEM_PROMPT
        assert "severity" in CRITIC_SYSTEM_PROMPT.lower()

    def test_includes_agent_permissions(self) -> None:
        """Critic prompt 含 Agent 权限声明: Read/Grep/Glob/Bash, 不可 Write/Edit."""
        assert "read" in CRITIC_SYSTEM_PROMPT.lower()
        assert "grep" in CRITIC_SYSTEM_PROMPT.lower() or "search" in CRITIC_SYSTEM_PROMPT.lower()
        # Should mention what Critic CANNOT do
        assert "禁止" in CRITIC_SYSTEM_PROMPT or "cannot" in CRITIC_SYSTEM_PROMPT.lower()

    def test_preserves_verdict_enum(self) -> None:
        """Critic prompt 保留 APPROVE/MAJOR 枚举判定."""
        assert "APPROVE" in CRITIC_SYSTEM_PROMPT
        assert "MAJOR" in CRITIC_SYSTEM_PROMPT

    def test_strengths_before_findings_section(self) -> None:
        """strengths 章节在 findings/issues 章节之前 (Superpowers: acknowledge strengths first).

        v5.6: critic prompt = B11 fragments (含合理化表, 内有单数 "finding") + 正文.
        按正文中 `findings` 章节 (复数字段名) 定位, 避免匹配到前置片段里的单数 "finding".
        """
        prompt_lower = CRITIC_SYSTEM_PROMPT.lower()
        strengths_pos = prompt_lower.find("strength")
        findings_pos = prompt_lower.find("findings")
        if strengths_pos >= 0 and findings_pos >= 0:
            assert strengths_pos < findings_pos, (
                f"strengths section should appear before findings, "
                f"got strengths@{strengths_pos}, findings@{findings_pos}"
            )


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
        """Architect prompt 含 3 模式: INTERACTIVE/PLAN-REFINE/DESIGN-INTEGRATION."""
        prompt = ARCHITECT_SYSTEM_PROMPT.lower()
        modes = ["interactive", "plan-refin", "design-integrat",
                 "plan_refin", "design_integrat"]
        found = [m for m in modes if m in prompt]
        assert len(found) >= 2, f"Expected >=2 mode keywords, found: {found}"

    def test_includes_brainstorming_workflow(self) -> None:
        """Architect prompt 含 brainstorming 简化流程."""
        prompt_lower = ARCHITECT_SYSTEM_PROMPT.lower()
        brainstorming_keywords = ["需求", "约束", "方案", "权衡",
                                  "requirement", "constraint", "approach", "tradeoff",
                                  "brainstorm"]
        found = [k for k in brainstorming_keywords if k in prompt_lower]
        assert len(found) >= 2, f"Expected >=2 brainstorming keywords, found: {found}"

    def test_includes_structured_batch_plan_output(self) -> None:
        """Architect prompt 含 batch_plan 结构化输出要求 (v7.8 规范化格式)."""
        prompt = ARCHITECT_SYSTEM_PROMPT
        assert "batch_plan" in prompt.lower()
        assert "batch_id" in prompt.lower()
        assert "file_targets" in prompt.lower()
        assert "tasks" in prompt.lower()

    def test_includes_agent_reach_reference(self) -> None:
        """Architect prompt 含 Agent-Reach 引用."""
        prompt = ARCHITECT_SYSTEM_PROMPT.lower()
        assert "agent-reach" in prompt or "外部参考" in prompt or "mcp" in prompt
