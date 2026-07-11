"""v5.1 B1.13 — Agent 输出 Pydantic 模型.

设计来源: design/v5.6-Design-Loop.md §B1.13 (line 888-912).
用途: Agent 输出的结构化校验 — 替代原 dict-based 的手动字段检查.
"""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, Field

__all__ = ["ArchitectOutput", "CriticOutput", "DeveloperOutput"]

class ArchitectOutput(BaseModel):
    """Architect 角色输出契约 (§B4.1a)."""

    files_needed: list[str] = Field(default_factory=list, description="所有涉及的文件路径")
    files_to_create: list[str] = Field(default_factory=list, description="本次新创建的文件")
    files_to_modify: list[str] = Field(default_factory=list, description="本次修改的已有文件")
    plan: str = Field(default="", description="实现计划 (Markdown)")
    file_list: list[str] = Field(default_factory=list, description="需创建/修改的文件路径")
    batch_plan: list[dict] = Field(
        default_factory=list,
        description=(
            "分批策略 (B6.1a 嵌套): [{batch_id, design_section, component, "
            "tasks:[{id, description, module_ref, file_targets}], depends_on}]"
        ),
    )
    contracts: dict = Field(default_factory=dict, description="跨模块契约")


class DeveloperOutput(BaseModel):
    """Developer 角色输出契约 (§B4.2a)."""

    files_changed: list[str] = Field(default_factory=list, description="修改/创建的文件路径")
    commit_hash: str = Field(
        default="",
        pattern=r"^[0-9a-f]{40}$",
        description="git commit hash (40 hex chars)",
    )
    test_results: dict = Field(
        default_factory=lambda: {"passed": 0, "failed": 0, "errors": 0},
        description="测试结果 {passed, failed, errors}",
    )


class CriticOutput(BaseModel):
    """Critic 角色输出契约 (§B4.3a)."""

    verdict: Literal["APPROVE", "MAJOR"] = Field(
        default="MAJOR",
        description="审查判定: APPROVE 或 MAJOR",
    )
    findings: list[dict] = Field(
        default_factory=list,
        description="问题清单 [{file, line?, severity, issue, suggested_fix?}]",
    )
    critic_feedback: str = Field(default="", description="总体反馈")
    suggested_fix: str = Field(
        default="",
        description="unified diff patch (MAJOR 时必填)",
    )
    # v5.5 Phase 3: Superpowers code-reviewer.md 整合
    strengths: list[dict[str, Any]] | None = Field(
        default=None,
        description="本轮的强项/做对了什么 [{description, location}]",
    )
    assessment: str | None = Field(
        default=None,
        description="总体评估结论: Ready to merge / Ready to merge: With fixes / Needs rework",
    )
