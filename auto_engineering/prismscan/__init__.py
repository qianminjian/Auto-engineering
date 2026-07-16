"""PrismScan V5.1 — 代码库反向工程管道.

Phase 1 最小闭环 (B1 DONE):
  discover(project_root) → ProjectShape
  extract(project_shape) → SymbolIndex
  → Agent analyze subagent (JSONL 桥接)
  → check_result(analysis_json) → 校验 + 持久化

Phase 2 (B2 pending):
  Plan Agent + Generate Agent (JSONL LLM 阶段)

Phase 3 (B3 pending):
  Index + Cache + Checkpoint (确定性阶段)

公开 API:
  PrismScanOrchestrator - 主编排器 (orchestrator.py)
  discover              - 目录扫描 (discover.py)
  extract               - 符号提取 (extract.py)
  jsonl_protocol        - JSONL 文件桥接 (jsonl_protocol.py)
  schemas               - 数据模型 (schemas.py)
"""

from auto_engineering.prismscan.discover import discover
from auto_engineering.prismscan.extract import extract
from auto_engineering.prismscan.jsonl import JSONLProtocol
from auto_engineering.prismscan.jsonl_protocol import (
    JSONLErrorCode,
    JSONLProtocolError,
    JSONLTimeoutError,
    read_request,
    read_response,
    write_request,
    write_response,
)
from auto_engineering.prismscan.orchestrator import PrismScanOrchestrator
from auto_engineering.prismscan.schemas import (
    AnalysisResult,
    ApiSurfaceInfo,
    ArchitectureInfo,
    BusinessDomainInfo,
    DataModelInfo,
    DeploymentInfo,
    ModuleInfo,
    ProjectShape,
    ScheduledTaskInfo,
    SecurityInfo,
    SymbolIndex,
    SymbolInfo,
    jsonschema_validate,
)

__all__ = [
    "AnalysisResult",
    "ApiSurfaceInfo",
    "ArchitectureInfo",
    "BusinessDomainInfo",
    "DataModelInfo",
    "DeploymentInfo",
    "JSONLErrorCode",
    "JSONLProtocol",
    "JSONLProtocolError",
    "JSONLTimeoutError",
    "ModuleInfo",
    "PrismScanOrchestrator",
    "ProjectShape",
    "ScheduledTaskInfo",
    "SecurityInfo",
    "SymbolIndex",
    "SymbolInfo",
    "discover",
    "extract",
    "jsonschema_validate",
    "read_request",
    "read_response",
    "write_request",
    "write_response",
]
