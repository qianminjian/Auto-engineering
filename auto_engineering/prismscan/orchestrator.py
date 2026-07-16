"""PrismScan V5.1 — Orchestrator: 主控制流 + 阶段编排.

Phase 1 最小闭环:
  discover(project_root) → ProjectShape
  extract(project_shape) → SymbolIndex
  → 输出 action JSON (Agent 执行 analyze subagent)
  → check_result(analysis_json) → 校验 + 持久化

复用现有基础设施: GuardrailChain, Gate 模式, JSON Schema 校验.
"""

from __future__ import annotations

import json
import logging
import uuid
from pathlib import Path

from auto_engineering.prismscan.discover import discover
from auto_engineering.prismscan.extract import extract
from auto_engineering.prismscan.jsonl import JSONLProtocol as _JSONL
from auto_engineering.prismscan.schemas import (
    AnalysisResult,
    ProjectShape,
    SymbolIndex,
    jsonschema_validate,
)

_logger = logging.getLogger("ae.prismscan.orchestrator")

_STAGE_SEQUENCE = ["init", "analyze", "complete"]


class PrismScanOrchestrator:
    """PrismScan 管道编排器 — Phase 1 最小闭环.

    与 TickOrchestrator 一致的依赖注入模式.
    """

    def __init__(
        self,
        project_root: str,
        *,
        db_path: str | None = None,
        guardrail = None,
        gate_runner = None,
    ) -> None:
        import os as _os
        self.project_root = _os.path.realpath(str(project_root))
        self._stage = "init"
        self._thread_id = str(uuid.uuid4())
        self._db_path = db_path or str(
            Path(project_root) / "repowiki" / ".state" / "prismscan.db"
        )
        self._guardrail = guardrail
        self._gate_runner = gate_runner
        self._project_shape: ProjectShape | None = None
        self._symbol_index: SymbolIndex | None = None
        self._analysis_result: AnalysisResult | None = None
        self._data_file: str = ""

    def run_discover_extract(self) -> dict:
        """运行 discover + extract 确定性阶段, 输出 action JSON.

        Returns:
            action JSON: {action, stage, thread_id, context, data_file}
            或 error JSON: {action: "error", message}
        """
        try:
            root = Path(self.project_root)
            if not root.exists():
                return {
                    "action": "error",
                    "error_code": "PROJECT_NOT_FOUND",
                    "message": f"项目目录不存在: {self.project_root}",
                    "stage": "init",
                    "thread_id": self._thread_id,
                }

            # Step 1: Discover
            self._project_shape = discover(self.project_root)
            _logger.info(
                "Discover 完成: %s (%d files, %d modules)",
                self._project_shape.project_name,
                self._project_shape.total_files,
                len(self._project_shape.modules),
            )

            # Step 2: Extract
            self._symbol_index = extract(self._project_shape)
            _logger.info(
                "Extract 完成: %d symbols, %d deps",
                len(self._symbol_index.symbols),
                len(self._symbol_index.dependency_graph),
            )

            # Step 3: 通过 JSONL 协议序列化数据到文件 (供 Agent 读取)
            proto = _JSONL(mode="file")
            data_payload = {
                "project_shape": self._project_shape.to_dict(),
                "symbol_index": self._symbol_index.to_dict(),
            }
            data_path = proto.write_request(
                "analyze",
                data_payload,
                Path(self.project_root) / "repowiki" / ".state" / "analyze-request.json",
            )
            self._data_file = str(data_path)

            self._stage = "analyze"

            return {
                "action": "analyze",
                "stage": "analyze",
                "thread_id": self._thread_id,
                "requirement": f"分析项目 {self._project_shape.project_name}",
                "context": {
                    "project_shape": self._project_shape.to_dict(),
                    "symbol_index": self._symbol_index.to_dict(),
                },
                "data_file": self._data_file,
                "expected_format": {
                    "architecture": "{pattern, description, layers[]}",
                    "business_domains": "[{name, type, key_classes[], description}]",
                    "api_surface": "{total_endpoints, grouped_by_resource, auth_required_endpoints}",
                    "data_models": "[{entity, table, fields[], relationships[]}]",
                    "security": "{auth_mechanism, auth_files[], permission_model}",
                    "scheduled_tasks": "[{name, schedule, file}]",
                    "deployment": "{has_docker, has_k8s, ci_platform, env_files[]}",
                },
            }
        except Exception as e:
            _logger.exception("run_discover_extract 失败")
            return {
                "action": "error",
                "error_code": "INTERNAL_ERROR",
                "message": str(e),
                "stage": self._stage,
                "thread_id": self._thread_id,
            }

    def check_result(self, result_file: str) -> dict:
        """校验 Agent 产出的 AnalysisResult JSON.

        Args:
            result_file: Agent 写入的结果 JSON 文件路径.

        Returns:
            校验通过的 AnalysisResult dict (含 stage/thread_id 元信息),
            或 error dict.
        """
        try:
            path = Path(result_file)
            if not path.exists():
                return {
                    "action": "error",
                    "error_code": "RESULT_NOT_FOUND",
                    "message": f"结果文件不存在: {result_file}",
                    "stage": self._stage,
                    "thread_id": self._thread_id,
                }

            data = json.loads(path.read_text())

            # Step 1: JSON Schema 校验
            schema = AnalysisResult.jsonschema()
            if not jsonschema_validate(data, schema):
                return {
                    "action": "error",
                    "error_code": "SCHEMA_VALIDATION_FAILED",
                    "message": "AnalysisResult 不符合 JSON Schema",
                    "stage": self._stage,
                    "thread_id": self._thread_id,
                }

            # Step 2: 构造 AnalysisResult (同时验证字段完整性)
            try:
                result = AnalysisResult.from_dict(data)
            except (KeyError, TypeError) as e:
                return {
                    "action": "error",
                    "error_code": "PARSE_ERROR",
                    "message": f"AnalysisResult 解析失败: {e}",
                    "stage": self._stage,
                    "thread_id": self._thread_id,
                }

            self._analysis_result = result
            self._stage = "complete"

            return {
                "stage": "analyze",
                "thread_id": self._thread_id,
                "status": "valid",
                "analysis_result": result.to_dict(),
            }
        except json.JSONDecodeError as e:
            return {
                "action": "error",
                "error_code": "MALFORMED_JSON",
                "message": f"结果文件不是有效 JSON: {e}",
                "stage": self._stage,
                "thread_id": self._thread_id,
            }
        except Exception as e:
            _logger.exception("check_result 失败")
            return {
                "action": "error",
                "error_code": "INTERNAL_ERROR",
                "message": str(e),
                "stage": self._stage,
                "thread_id": self._thread_id,
            }
