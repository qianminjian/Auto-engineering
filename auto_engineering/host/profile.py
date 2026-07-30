"""宿主声明、探测、授权与有效能力的安全交集模型。"""

from __future__ import annotations

from dataclasses import dataclass

from auto_engineering.host import HostCapabilities, HostPlatform


@dataclass(frozen=True, slots=True)
class HostProfile:
    """单次宿主会话的四层能力快照。"""

    platform: HostPlatform
    declared: HostCapabilities
    detected: HostCapabilities
    authorized: HostCapabilities

    @property
    def effective(self) -> HostCapabilities:
        """返回三层输入的安全交集，不赋予任何推断能力。"""

        subagents = (
            self.declared.subagents
            and self.detected.subagents
            and self.authorized.subagents
        )
        return HostCapabilities(
            skills=(
                self.declared.skills
                and self.detected.skills
                and self.authorized.skills
            ),
            commands=(
                self.declared.commands
                and self.detected.commands
                and self.authorized.commands
            ),
            hooks=(
                self.declared.hooks
                & self.detected.hooks
                & self.authorized.hooks
            ),
            subagents=subagents,
            parallel_subagents=(
                subagents
                and self.declared.parallel_subagents
                and self.detected.parallel_subagents
                and self.authorized.parallel_subagents
            ),
            interactive_questions=(
                self.declared.interactive_questions
                and self.detected.interactive_questions
                and self.authorized.interactive_questions
            ),
            transcript_usage=(
                self.declared.transcript_usage
                and self.detected.transcript_usage
                and self.authorized.transcript_usage
            ),
            web_search=(
                self.declared.web_search
                and self.detected.web_search
                and self.authorized.web_search
            ),
            git_mutation=(
                self.declared.git_mutation
                and self.detected.git_mutation
                and self.authorized.git_mutation
            ),
            session_handoff=(
                self.declared.session_handoff
                and self.detected.session_handoff
                and self.authorized.session_handoff
            ),
        )


__all__ = ["HostProfile"]
