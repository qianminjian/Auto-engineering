"""设计、缺口、任务与验证证据的统一确定性投影。"""

from __future__ import annotations

import hashlib
import re
import unicodedata
from collections.abc import Iterable
from dataclasses import dataclass, replace

from auto_engineering.engine.design_doc import DesignDoc


class EngineeringModelError(ValueError):
    """工程模型包含未知身份或非法追溯关系。"""


@dataclass(frozen=True, slots=True)
class EngineeringSection:
    section_id: str
    design_section: str
    plate: str | None
    component: str | None
    title: str


@dataclass(frozen=True, slots=True)
class TraceLink:
    source_id: str
    target_id: str
    relation: str


@dataclass(frozen=True, slots=True)
class EngineeringModel:
    design_digest: str
    sections: tuple[EngineeringSection, ...]
    links: tuple[TraceLink, ...] = ()

    @classmethod
    def from_design_doc(
        cls,
        design_doc: DesignDoc,
        *,
        design_digest: str,
    ) -> EngineeringModel:
        if re.fullmatch(r"sha256:[0-9a-f]{64}", design_digest) is None:
            raise EngineeringModelError("ENGINEERING_DIGEST_INVALID")
        summaries = design_doc.sections_summary()
        if not summaries:
            summaries = [
                {
                    "plate": plate.name,
                    "component": None,
                    "design_section": plate.design_section,
                }
                for plate in design_doc.plates
            ]
        if not summaries:
            summaries = [{
                "plate": None,
                "component": None,
                "design_section": "document",
            }]
        sections = tuple(
            EngineeringSection(
                section_id=_stable_section_id(str(item["design_section"])),
                design_section=str(item["design_section"]),
                plate=(
                    str(item["plate"])
                    if item.get("plate") is not None
                    else None
                ),
                component=(
                    str(item["component"])
                    if item.get("component") is not None
                    else None
                ),
                title=str(item.get("component") or item.get("plate") or "document"),
            )
            for item in summaries
        )
        identities = [section.section_id for section in sections]
        if len(identities) != len(set(identities)):
            raise EngineeringModelError("ENGINEERING_SECTION_ID_DUPLICATE")
        return cls(design_digest=design_digest, sections=sections)

    def action_sections(self) -> list[dict[str, str | None]]:
        """返回供全部 Stage 共用的稳定身份和展示信息。"""

        return [
            {
                "section_id": section.section_id,
                "design_section": section.design_section,
                "plate": section.plate,
                "component": section.component,
                "title": section.title,
            }
            for section in self.sections
        ]

    def host_sections(self) -> list[dict[str, str | None]]:
        """返回 Agent 可读的章节引用；内部哈希身份不越过宿主边界。"""

        return [
            {
                "section_ref": section.design_section,
                "plate": section.plate,
                "component": section.component,
                "title": section.title,
            }
            for section in self.sections
        ]

    def select_sections(
        self,
        references: Iterable[str],
    ) -> tuple[EngineeringSection, ...]:
        """把稳定 ID 或旧展示引用解析到同一章节身份。"""

        selected: set[str] = set()
        for reference in references:
            normalized = _normalize_reference(reference)
            matches = [
                section
                for section in self.sections
                if normalized in self._reference_aliases(section)
            ]
            if not matches:
                raise EngineeringModelError(
                    f"ENGINEERING_SECTION_UNKNOWN:{reference}"
                )
            if len(matches) > 1:
                raise EngineeringModelError(
                    f"ENGINEERING_SECTION_AMBIGUOUS:{reference}"
                )
            selected.add(matches[0].section_id)
        return tuple(
            section for section in self.sections
            if section.section_id in selected
        )

    @staticmethod
    def _reference_aliases(section: EngineeringSection) -> set[str]:
        values = {
            section.section_id,
            section.design_section,
            section.title,
            section.component or "",
        }
        for label in {section.title, section.component or ""}:
            if label:
                values.add(f"{section.design_section} {label}")
        return {_normalize_reference(value) for value in values}

    def bind_gap(self, *, section_id: str, gap_id: str) -> EngineeringModel:
        if section_id not in self._known_ids():
            raise EngineeringModelError("ENGINEERING_SOURCE_UNKNOWN")
        return self._bind(section_id, gap_id, "section_gap")

    def bind_task(self, *, source_id: str, task_id: str) -> EngineeringModel:
        if source_id not in self._known_ids():
            raise EngineeringModelError("ENGINEERING_SOURCE_UNKNOWN")
        return self._bind(source_id, task_id, "source_task")

    def bind_evidence(self, *, task_id: str, evidence_id: str) -> EngineeringModel:
        if task_id not in self._known_ids():
            raise EngineeringModelError("ENGINEERING_SOURCE_UNKNOWN")
        return self._bind(task_id, evidence_id, "task_evidence")

    def trace(self, evidence_id: str) -> tuple[str, ...]:
        if evidence_id not in self._known_ids():
            raise EngineeringModelError("ENGINEERING_TARGET_UNKNOWN")
        parents = {link.target_id: link.source_id for link in self.links}
        path = [evidence_id]
        while path[-1] in parents:
            path.append(parents[path[-1]])
        path.reverse()
        return tuple(path)

    def _known_ids(self) -> frozenset[str]:
        return frozenset(
            [section.section_id for section in self.sections]
            + [link.target_id for link in self.links]
        )

    def _bind(
        self,
        source_id: str,
        target_id: str,
        relation: str,
    ) -> EngineeringModel:
        if not target_id.strip():
            raise EngineeringModelError("ENGINEERING_TARGET_INVALID")
        existing = next(
            (link for link in self.links if link.target_id == target_id),
            None,
        )
        candidate = TraceLink(source_id, target_id, relation)
        if existing is not None:
            if existing != candidate:
                raise EngineeringModelError("ENGINEERING_TARGET_REBOUND")
            return self
        return replace(self, links=(*self.links, candidate))


def _stable_section_id(design_section: str) -> str:
    normalized = _normalize_reference(design_section)
    digest = hashlib.sha256(normalized.encode("utf-8")).hexdigest()[:16]
    return f"section:{digest}"


def _normalize_reference(value: str) -> str:
    return unicodedata.normalize("NFKC", value).strip().casefold()


__all__ = [
    "EngineeringModel",
    "EngineeringModelError",
    "EngineeringSection",
    "TraceLink",
]
