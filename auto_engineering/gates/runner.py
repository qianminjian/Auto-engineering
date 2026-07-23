"""Gate Runner — 按名称批量跑 Gate, 与 CLI/loop 层解耦.

2026-07-21 P1-5: 从 cli/gate_check.py 提取, 消除 loop→CLI 依赖倒置.
"""

from __future__ import annotations

import logging
from pathlib import Path

from auto_engineering.gates.base import Gate

_logger = logging.getLogger("ae.gates.runner")


def _production_active(project_root: Path) -> bool:
    """Check if AE_PRODUCTION=1 for gate hardening (P1-12)."""
    try:
        from auto_engineering.config.runtime_config import get_default_config
        return get_default_config().production_enabled
    except Exception:
        return False


def _instantiate_gate(name: str, project_root: Path) -> Gate | None:
    """按名称实例化单个 Gate 对象. 不支持的返回 None (skip)."""
    try:
        from auto_engineering.gates.registry import get_gate_by_name

        gate = get_gate_by_name(name)
        if gate is not None:
            return gate
    except (ImportError, TypeError) as e:
        _logger.warning("gate '%s' 实例化失败: %s", name, e, exc_info=True)
        return None
    return None


def run_gates(
    gate_names: tuple[str, ...],
    project_root: Path,
    files_changed: list[str] | None = None,
) -> dict:
    """跑给定名称列表的 Gate, 返回 JSON-ready dict.

    异常安全: 每个 Gate 单独 try, 不会因一个失败影响其他.

    Args:
        files_changed: 变更文件相对路径列表, 用于 Gate 增量扫描
                       (如 AuditGate 仅扫描变更文件而非全项目).
    """
    summary: dict[str, dict] = {}
    passed_count = 0
    failed_count = 0
    skipped_count = 0

    for name in gate_names:
        gate = _instantiate_gate(name, project_root)
        if gate is None:
            summary[name] = {"status": "skipped", "passed": None, "message": "no such gate"}
            skipped_count += 1
            continue
        # 注入 files_changed — 仅对有该属性的 Gate 直接设置, 不污染 contracts
        if files_changed and hasattr(gate, 'files_changed'):
            gate.files_changed = files_changed
        # 跑 Gate
        try:
            verdict = gate.run(project_root)
        except (KeyboardInterrupt, SystemExit):
            raise
        except Exception as e:
            _logger.warning("gate '%s' 执行异常", name, exc_info=True)
            # fail-closed: 崩溃的质量门禁不得静默放行 (区别于"不适用" skipped)
            summary[name] = {"status": "error", "passed": False, "message": f"run error: {e}"}
            failed_count += 1
            continue
        # 解析 verdict
        ok = bool(getattr(verdict, "passed", False))
        message = str(getattr(verdict, "message", "") or "")
        gate_name = getattr(verdict, "gate_name", "") or name
        # P1-12: AE_PRODUCTION=1 → failed gates are hard_fail (不可降级为 warn)
        if not ok and _production_active(project_root):
            status = "hard_fail"
            _logger.critical("Gate '%s' FAILED (production mode — 不可降级)", gate_name)
        else:
            status = "pass" if ok else "fail"
        summary[name] = {
            "status": status,
            "passed": ok,
            "message": message,
            "gate_name": gate_name,
        }
        if ok:
            passed_count += 1
        else:
            failed_count += 1

    return {
        "project_root": str(project_root),
        "gate_names": list(gate_names),
        "passed": passed_count,
        "failed": failed_count,
        "skipped": skipped_count,
        "gate_summary": summary,
    }
