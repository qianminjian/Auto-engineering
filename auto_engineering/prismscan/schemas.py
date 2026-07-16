"""PrismScan V5.1 数据对象 — ProjectShape / SymbolIndex / AnalysisResult.

每个 dataclass 对应一个 JSON Schema 文件, 提供 to_dict/from_dict/jsonschema_validate
以保证 Python ↔ Agent JSONL 数据契约的一致性.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path

import jsonschema

_SCHEMAS_DIR = Path(__file__).parent / "schemas"


def _load_schema(name: str) -> dict:
    """加载 JSON Schema 文件."""
    return json.loads((_SCHEMAS_DIR / name).read_text())


def jsonschema_validate(data: dict, schema: dict) -> bool:
    """校验 data 是否符合 schema. 返回 True/False, 不抛异常."""
    try:
        jsonschema.validate(data, schema)
        return True
    except jsonschema.ValidationError:
        return False


# ── ProjectShape (Discover 阶段输出) ──


@dataclass
class ModuleInfo:
    name: str
    path: str
    file_count: int
    language: str
    entry_point: str = ""

    def to_dict(self) -> dict:
        d = {"name": self.name, "path": self.path,
             "file_count": self.file_count, "language": self.language}
        if self.entry_point:
            d["entry_point"] = self.entry_point
        return d

    @classmethod
    def from_dict(cls, d: dict) -> ModuleInfo:
        return cls(
            name=d["name"], path=d["path"],
            file_count=d["file_count"], language=d["language"],
            entry_point=d.get("entry_point", ""),
        )


@dataclass
class ProjectShape:
    project_name: str
    languages: list[str] = field(default_factory=list)
    build_system: str = ""
    modules: list[ModuleInfo] = field(default_factory=list)
    entry_points: list[str] = field(default_factory=list)
    has_docker: bool = False
    total_files: int = 0
    directory_tree_summary: str = ""

    @staticmethod
    def jsonschema() -> dict:
        return _load_schema("project-shape.schema.json")

    def to_dict(self) -> dict:
        return {
            "project_name": self.project_name,
            "languages": self.languages,
            "build_system": self.build_system,
            "modules": [m.to_dict() for m in self.modules],
            "entry_points": self.entry_points,
            "has_docker": self.has_docker,
            "total_files": self.total_files,
            "directory_tree_summary": self.directory_tree_summary,
        }

    @classmethod
    def from_dict(cls, d: dict) -> ProjectShape:
        return cls(
            project_name=d["project_name"],
            languages=d.get("languages", []),
            build_system=d.get("build_system", ""),
            modules=[ModuleInfo.from_dict(m) for m in d.get("modules", [])],
            entry_points=d.get("entry_points", []),
            has_docker=d.get("has_docker", False),
            total_files=d.get("total_files", 0),
            directory_tree_summary=d.get("directory_tree_summary", ""),
        )


# ── SymbolIndex (Extract 阶段输出) ──


@dataclass
class SymbolInfo:
    name: str
    kind: str  # class/function/method/interface/struct/enum/variable/module
    file: str
    line: int
    scope: str = ""
    signature: str = ""

    def to_dict(self) -> dict:
        d = {"name": self.name, "kind": self.kind,
             "file": self.file, "line": self.line}
        if self.scope:
            d["scope"] = self.scope
        if self.signature:
            d["signature"] = self.signature
        return d

    @classmethod
    def from_dict(cls, d: dict) -> SymbolInfo:
        return cls(
            name=d["name"], kind=d["kind"],
            file=d["file"], line=d["line"],
            scope=d.get("scope", ""),
            signature=d.get("signature", ""),
        )


@dataclass
class SymbolIndex:
    symbols: list[SymbolInfo] = field(default_factory=list)
    dependency_graph: dict[str, list[str]] = field(default_factory=dict)

    @staticmethod
    def jsonschema() -> dict:
        return _load_schema("symbol-index.schema.json")

    def to_dict(self) -> dict:
        return {
            "symbols": [s.to_dict() for s in self.symbols],
            "dependency_graph": self.dependency_graph,
        }

    @classmethod
    def from_dict(cls, d: dict) -> SymbolIndex:
        return cls(
            symbols=[SymbolInfo.from_dict(s) for s in d.get("symbols", [])],
            dependency_graph=d.get("dependency_graph", {}),
        )


# ── AnalysisResult (Analyze 阶段输出, Agent LLM 推理) ──


@dataclass
class ArchitectureInfo:
    pattern: str
    description: str
    layers: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, object]:
        d: dict[str, object] = {"pattern": self.pattern, "description": self.description}
        if self.layers:
            d["layers"] = self.layers
        return d

    @classmethod
    def from_dict(cls, d: dict) -> ArchitectureInfo:
        return cls(
            pattern=d["pattern"], description=d.get("description", ""),
            layers=d.get("layers", []),
        )


@dataclass
class BusinessDomainInfo:
    name: str
    type: str
    key_classes: list[str] = field(default_factory=list)
    description: str = ""

    def to_dict(self) -> dict:
        d = {"name": self.name, "type": self.type,
             "key_classes": self.key_classes}
        if self.description:
            d["description"] = self.description
        return d

    @classmethod
    def from_dict(cls, d: dict) -> BusinessDomainInfo:
        return cls(
            name=d["name"], type=d["type"],
            key_classes=d.get("key_classes", []),
            description=d.get("description", ""),
        )


@dataclass
class ApiSurfaceInfo:
    total_endpoints: int = 0
    grouped_by_resource: dict[str, int] = field(default_factory=dict)
    auth_required_endpoints: int = 0

    def to_dict(self) -> dict:
        d: dict = {"total_endpoints": self.total_endpoints}
        if self.grouped_by_resource:
            d["grouped_by_resource"] = self.grouped_by_resource
        if self.auth_required_endpoints:
            d["auth_required_endpoints"] = self.auth_required_endpoints
        return d

    @classmethod
    def from_dict(cls, d: dict) -> ApiSurfaceInfo:
        return cls(
            total_endpoints=d.get("total_endpoints", 0),
            grouped_by_resource=d.get("grouped_by_resource", {}),
            auth_required_endpoints=d.get("auth_required_endpoints", 0),
        )


@dataclass
class DataModelInfo:
    entity: str
    table: str
    fields: list[str] = field(default_factory=list)
    relationships: list[str] = field(default_factory=list)

    def to_dict(self) -> dict:
        return {
            "entity": self.entity, "table": self.table,
            "fields": self.fields, "relationships": self.relationships,
        }

    @classmethod
    def from_dict(cls, d: dict) -> DataModelInfo:
        return cls(
            entity=d["entity"], table=d["table"],
            fields=d.get("fields", []),
            relationships=d.get("relationships", []),
        )


@dataclass
class SecurityInfo:
    auth_mechanism: str = ""
    auth_files: list[str] = field(default_factory=list)
    permission_model: str = ""

    def to_dict(self) -> dict:
        d: dict = {}
        if self.auth_mechanism:
            d["auth_mechanism"] = self.auth_mechanism
        if self.auth_files:
            d["auth_files"] = self.auth_files
        if self.permission_model:
            d["permission_model"] = self.permission_model
        return d

    @classmethod
    def from_dict(cls, d: dict) -> SecurityInfo:
        return cls(
            auth_mechanism=d.get("auth_mechanism", ""),
            auth_files=d.get("auth_files", []),
            permission_model=d.get("permission_model", ""),
        )


@dataclass
class ScheduledTaskInfo:
    name: str
    schedule: str
    file: str

    def to_dict(self) -> dict:
        return {"name": self.name, "schedule": self.schedule, "file": self.file}

    @classmethod
    def from_dict(cls, d: dict) -> ScheduledTaskInfo:
        return cls(name=d["name"], schedule=d["schedule"], file=d["file"])


@dataclass
class DeploymentInfo:
    has_docker: bool = False
    has_k8s: bool = False
    ci_platform: str = ""
    env_files: list[str] = field(default_factory=list)

    def to_dict(self) -> dict:
        d: dict = {"has_docker": self.has_docker}
        if self.has_k8s:
            d["has_k8s"] = self.has_k8s
        if self.ci_platform:
            d["ci_platform"] = self.ci_platform
        if self.env_files:
            d["env_files"] = self.env_files
        return d

    @classmethod
    def from_dict(cls, d: dict) -> DeploymentInfo:
        return cls(
            has_docker=d.get("has_docker", False),
            has_k8s=d.get("has_k8s", False),
            ci_platform=d.get("ci_platform", ""),
            env_files=d.get("env_files", []),
        )


@dataclass
class AnalysisResult:
    architecture: ArchitectureInfo = field(default_factory=lambda: ArchitectureInfo(pattern="", description=""))
    business_domains: list[BusinessDomainInfo] = field(default_factory=list)
    api_surface: ApiSurfaceInfo = field(default_factory=ApiSurfaceInfo)
    data_models: list[DataModelInfo] = field(default_factory=list)
    security: SecurityInfo = field(default_factory=SecurityInfo)
    scheduled_tasks: list[ScheduledTaskInfo] = field(default_factory=list)
    deployment: DeploymentInfo = field(default_factory=DeploymentInfo)

    @staticmethod
    def jsonschema() -> dict:
        return _load_schema("analysis-result.schema.json")

    def to_dict(self) -> dict:
        return {
            "architecture": self.architecture.to_dict(),
            "business_domains": [b.to_dict() for b in self.business_domains],
            "api_surface": self.api_surface.to_dict(),
            "data_models": [m.to_dict() for m in self.data_models],
            "security": self.security.to_dict(),
            "scheduled_tasks": [t.to_dict() for t in self.scheduled_tasks],
            "deployment": self.deployment.to_dict(),
        }

    @classmethod
    def from_dict(cls, d: dict) -> AnalysisResult:
        return cls(
            architecture=ArchitectureInfo.from_dict(d.get("architecture", {})),
            business_domains=[BusinessDomainInfo.from_dict(b)
                              for b in d.get("business_domains", [])],
            api_surface=ApiSurfaceInfo.from_dict(d.get("api_surface", {})),
            data_models=[DataModelInfo.from_dict(m)
                         for m in d.get("data_models", [])],
            security=SecurityInfo.from_dict(d.get("security", {})),
            scheduled_tasks=[ScheduledTaskInfo.from_dict(t)
                             for t in d.get("scheduled_tasks", [])],
            deployment=DeploymentInfo.from_dict(d.get("deployment", {})),
        )
