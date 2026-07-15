"""Tests for PrismScan schemas — JSON Schema validation + dataclass round-trip."""

from __future__ import annotations

import json
from pathlib import Path

import pytest


SCHEMAS_DIR = Path(__file__).parent.parent / "auto_engineering" / "prismscan" / "schemas"


class TestProjectShapeSchema:
    """project-shape.schema.json 校验."""

    @pytest.fixture
    def schema(self):
        path = SCHEMAS_DIR / "project-shape.schema.json"
        assert path.exists(), f"Schema not found: {path}"
        return json.loads(path.read_text())

    @pytest.fixture
    def valid_shape(self):
        return {
            "project_name": "test-project",
            "languages": ["python", "typescript"],
            "build_system": "uv",
            "modules": [
                {
                    "name": "core",
                    "path": "src/core",
                    "file_count": 15,
                    "language": "python",
                    "entry_point": "src/core/__init__.py",
                }
            ],
            "entry_points": ["src/main.py", "src/cli.py"],
            "has_docker": True,
            "total_files": 42,
            "directory_tree_summary": "test-project/\n  src/\n    core/\n    cli/",
        }

    def test_valid_shape_passes(self, schema, valid_shape):
        from auto_engineering.prismscan.schemas import jsonschema_validate

        result = jsonschema_validate(valid_shape, schema)
        assert result is True

    def test_missing_required_field_fails(self, schema):
        from auto_engineering.prismscan.schemas import jsonschema_validate

        invalid = {"project_name": "test"}
        result = jsonschema_validate(invalid, schema)
        assert result is False

    def test_wrong_type_fails(self, schema):
        from auto_engineering.prismscan.schemas import jsonschema_validate

        invalid = {
            "project_name": "test",
            "languages": "python",  # should be list
            "build_system": "uv",
            "modules": [],
            "entry_points": [],
            "has_docker": False,
            "total_files": 0,
            "directory_tree_summary": "",
        }
        result = jsonschema_validate(invalid, schema)
        assert result is False


class TestSymbolIndexSchema:
    """symbol-index.schema.json 校验."""

    @pytest.fixture
    def schema(self):
        path = SCHEMAS_DIR / "symbol-index.schema.json"
        assert path.exists(), f"Schema not found: {path}"
        return json.loads(path.read_text())

    @pytest.fixture
    def valid_index(self):
        return {
            "symbols": [
                {
                    "name": "MyClass",
                    "kind": "class",
                    "file": "src/core/my_class.py",
                    "line": 10,
                    "scope": "module",
                    "signature": "class MyClass(BaseClass)",
                }
            ],
            "dependency_graph": {"MyClass": ["BaseClass"], "main": ["MyClass"]},
        }

    def test_valid_index_passes(self, schema, valid_index):
        from auto_engineering.prismscan.schemas import jsonschema_validate

        result = jsonschema_validate(valid_index, schema)
        assert result is True

    def test_empty_symbols_ok(self, schema):
        from auto_engineering.prismscan.schemas import jsonschema_validate

        result = jsonschema_validate(
            {"symbols": [], "dependency_graph": {}}, schema
        )
        assert result is True


class TestAnalysisResultSchema:
    """analysis-result.schema.json 校验."""

    @pytest.fixture
    def schema(self):
        path = SCHEMAS_DIR / "analysis-result.schema.json"
        assert path.exists(), f"Schema not found: {path}"
        return json.loads(path.read_text())

    @pytest.fixture
    def valid_result(self):
        return {
            "architecture": {
                "pattern": "layered",
                "description": "标准三层架构",
                "layers": ["controller", "service", "repository"],
            },
            "business_domains": [
                {
                    "name": "用户管理",
                    "type": "core",
                    "key_classes": ["UserController", "UserService"],
                    "description": "核心用户管理域",
                }
            ],
            "api_surface": {
                "total_endpoints": 42,
                "grouped_by_resource": {"用户管理": 15, "订单管理": 27},
                "auth_required_endpoints": 35,
            },
            "data_models": [
                {
                    "entity": "User",
                    "table": "users",
                    "fields": ["id", "name", "email", "gmt_create"],
                    "relationships": ["has_many: Order"],
                }
            ],
            "security": {
                "auth_mechanism": "JWT",
                "auth_files": ["src/auth/interceptor.py"],
                "permission_model": "RBAC",
            },
            "scheduled_tasks": [
                {
                    "name": "DailyReport",
                    "schedule": "0 6 * * *",
                    "file": "src/tasks/report_task.py",
                }
            ],
            "deployment": {
                "has_docker": True,
                "has_k8s": False,
                "ci_platform": "github-actions",
                "env_files": [".env.example", ".env.production"],
            },
        }

    def test_valid_result_passes(self, schema, valid_result):
        from auto_engineering.prismscan.schemas import jsonschema_validate

        result = jsonschema_validate(valid_result, schema)
        assert result is True


class TestDataClasses:
    """schemas.py dataclass to_dict/from_dict 往返一致性."""

    def test_project_shape_round_trip(self):
        from auto_engineering.prismscan.schemas import ProjectShape

        shape = ProjectShape(
            project_name="test",
            languages=["python"],
            build_system="uv",
            modules=[],
            entry_points=["main.py"],
            has_docker=False,
            total_files=10,
            directory_tree_summary="test/",
        )
        d = shape.to_dict()
        restored = ProjectShape.from_dict(d)
        assert restored.project_name == "test"
        assert restored.languages == ["python"]
        assert restored.total_files == 10

    def test_symbol_index_round_trip(self):
        from auto_engineering.prismscan.schemas import SymbolIndex

        idx = SymbolIndex(symbols=[], dependency_graph={})
        d = idx.to_dict()
        restored = SymbolIndex.from_dict(d)
        assert restored.symbols == []
        assert restored.dependency_graph == {}

    def test_analysis_result_round_trip(self):
        from auto_engineering.prismscan.schemas import (
            AnalysisResult, ArchitectureInfo, ApiSurfaceInfo,
            SecurityInfo, DeploymentInfo,
        )

        result = AnalysisResult(
            architecture=ArchitectureInfo(pattern="layered", description="三层架构"),
            business_domains=[],
            api_surface=ApiSurfaceInfo(total_endpoints=0),
            data_models=[],
            security=SecurityInfo(),
            scheduled_tasks=[],
            deployment=DeploymentInfo(),
        )
        d = result.to_dict()
        restored = AnalysisResult.from_dict(d)
        assert restored.architecture.pattern == "layered"

    def test_jsonschema_validate_with_project_shape_schema(self):
        from auto_engineering.prismscan.schemas import (
            ProjectShape,
            jsonschema_validate,
        )

        shape = ProjectShape(
            project_name="test",
            languages=["python"],
            build_system="uv",
            modules=[],
            entry_points=[],
            has_docker=False,
            total_files=0,
            directory_tree_summary="",
        )
        d = shape.to_dict()
        assert jsonschema_validate(d, shape.jsonschema()) is True

    def test_jsonschema_validate_rejects_invalid(self):
        from auto_engineering.prismscan.schemas import jsonschema_validate

        schema = {
            "type": "object",
            "required": ["name"],
            "properties": {"name": {"type": "string"}},
        }
        assert jsonschema_validate({}, schema) is False
        assert jsonschema_validate({"name": "ok"}, schema) is True


class TestMinimalAnalysisResult:
    """S6.2: Agent 产出最小 AnalysisResult（仅必填字段）→ 通过校验."""

    def test_minimal_analysis_result_passes_schema(self):
        from auto_engineering.prismscan.schemas import (
            AnalysisResult, ArchitectureInfo, ApiSurfaceInfo,
            SecurityInfo, DeploymentInfo, jsonschema_validate,
        )

        result = AnalysisResult(
            architecture=ArchitectureInfo(pattern="script", description=""),
            business_domains=[],
            api_surface=ApiSurfaceInfo(),
            data_models=[],
            security=SecurityInfo(),
            scheduled_tasks=[],
            deployment=DeploymentInfo(),
        )
        d = result.to_dict()
        assert jsonschema_validate(d, result.jsonschema()) is True

    def test_minimal_analysis_result_round_trip(self):
        from auto_engineering.prismscan.schemas import (
            AnalysisResult, ArchitectureInfo, ApiSurfaceInfo,
            SecurityInfo, DeploymentInfo,
        )

        result = AnalysisResult(
            architecture=ArchitectureInfo(pattern="script", description=""),
            business_domains=[],
            api_surface=ApiSurfaceInfo(),
            data_models=[],
            security=SecurityInfo(),
            scheduled_tasks=[],
            deployment=DeploymentInfo(),
        )
        d = result.to_dict()
        restored = AnalysisResult.from_dict(d)
        assert restored.architecture.pattern == "script"
        assert restored.architecture.description == ""
        assert restored.architecture.layers == []
        assert restored.business_domains == []
        assert restored.api_surface.total_endpoints == 0
        assert restored.data_models == []
        assert restored.security.auth_mechanism == ""
        assert restored.scheduled_tasks == []
        assert restored.deployment.has_docker is False

    def test_security_info_empty_to_dict(self):
        from auto_engineering.prismscan.schemas import SecurityInfo

        s = SecurityInfo()
        d = s.to_dict()
        assert d == {}

    def test_deployment_info_only_has_docker_to_dict(self):
        from auto_engineering.prismscan.schemas import DeploymentInfo

        d = DeploymentInfo(has_docker=True)
        result = d.to_dict()
        assert result == {"has_docker": True}

    def test_deployment_info_all_fields_to_dict(self):
        from auto_engineering.prismscan.schemas import DeploymentInfo

        d = DeploymentInfo(has_docker=True, has_k8s=True, ci_platform="github-actions",
                          env_files=[".env"])
        result = d.to_dict()
        assert result["has_docker"] is True
        assert result["has_k8s"] is True
        assert result["ci_platform"] == "github-actions"
        assert result["env_files"] == [".env"]

    def test_api_surface_empty_to_dict(self):
        from auto_engineering.prismscan.schemas import ApiSurfaceInfo

        a = ApiSurfaceInfo()
        d = a.to_dict()
        assert d == {"total_endpoints": 0}

    def test_symbol_info_with_scope_and_signature_to_dict(self):
        from auto_engineering.prismscan.schemas import SymbolInfo

        s = SymbolInfo(name="foo", kind="function", file="a.py", line=10,
                       scope="module", signature="def foo(x: int) -> str")
        d = s.to_dict()
        assert d["scope"] == "module"
        assert d["signature"] == "def foo(x: int) -> str"

    def test_module_info_with_entry_point_to_dict(self):
        from auto_engineering.prismscan.schemas import ModuleInfo

        m = ModuleInfo(name="core", path="src/core", file_count=5, language="python",
                       entry_point="src/core/__init__.py")
        d = m.to_dict()
        assert d["entry_point"] == "src/core/__init__.py"


class TestComplexAnalysisResult:
    """S6.3: 高复杂度 AnalysisResult — 压力测试."""

    def test_many_domains_and_models(self):
        from auto_engineering.prismscan.schemas import (
            AnalysisResult, ArchitectureInfo, ApiSurfaceInfo,
            BusinessDomainInfo, DataModelInfo,
            SecurityInfo, DeploymentInfo, ScheduledTaskInfo,
        )

        domains = [
            BusinessDomainInfo(
                name=f"domain_{i}", type="core",
                key_classes=[f"Class_{i}_{j}" for j in range(5)],
                description=f"Domain {i} description",
            )
            for i in range(50)
        ]
        models = [
            DataModelInfo(
                entity=f"Entity_{i}", table=f"table_{i}",
                fields=[f"field_{j}" for j in range(10)],
                relationships=[f"has_many: Entity_{(i+1) % 50}"],
            )
            for i in range(50)
        ]
        tasks = [
            ScheduledTaskInfo(name=f"task_{i}", schedule=f"0 {i % 24} * * *",
                            file=f"src/tasks/task_{i}.py")
            for i in range(25)
        ]

        result = AnalysisResult(
            architecture=ArchitectureInfo(pattern="microservices",
                                         description="Complex system", layers=["api", "service", "data"]),
            business_domains=domains,
            api_surface=ApiSurfaceInfo(total_endpoints=200,
                                       grouped_by_resource={f"res_{i}": i * 3 for i in range(30)}),
            data_models=models,
            security=SecurityInfo(auth_mechanism="OAuth2", permission_model="RBAC"),
            scheduled_tasks=tasks,
            deployment=DeploymentInfo(has_docker=True, has_k8s=True,
                                     ci_platform="jenkins", env_files=[".env.prod"]),
        )
        d = result.to_dict()
        restored = AnalysisResult.from_dict(d)
        assert len(restored.business_domains) == 50
        assert len(restored.data_models) == 50
        assert len(restored.scheduled_tasks) == 25


class TestLargeSymbolIndex:
    """S6.5: 大型符号索引 — 序列化/反序列化."""

    def test_large_symbol_index_round_trip(self):
        from auto_engineering.prismscan.schemas import SymbolIndex, SymbolInfo

        symbols = [
            SymbolInfo(name=f"symbol_{i}", kind="function", file=f"src/module_{i % 20}.py",
                       line=i * 10, signature=f"def symbol_{i}()")
            for i in range(500)
        ]
        graph = {f"symbol_{i}": [f"symbol_{(i+1) % 500}"] for i in range(500)}
        idx = SymbolIndex(symbols=symbols, dependency_graph=graph)

        d = idx.to_dict()
        restored = SymbolIndex.from_dict(d)
        assert len(restored.symbols) == 500
        assert len(restored.dependency_graph) == 500
        assert restored.symbols[0].name == "symbol_0"
        assert restored.symbols[499].name == "symbol_499"
