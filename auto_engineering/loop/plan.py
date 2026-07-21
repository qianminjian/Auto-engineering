"""Re-export shim — Task/Plan data models moved to engine/models.py (P0-2, 2026-07-21).

Break engine → loop → engine cycle: engine/batch_state.py now imports Plan/Task
directly from engine/models.py. All other consumers continue importing from
loop/plan.py via this shim for backward compatibility.
"""

from auto_engineering.engine.models import (
    VALID_TASK_ROLES,
    ConflictError,
    Plan,
    PlanValidationError,
    Task,
    TaskDAG,
    TaskOutcome,
    TaskStatus,
    TaskValidation,
    _topological_levels,
    check_file_isolation,
    topological_sort,
)

__all__ = [
    "VALID_TASK_ROLES",
    "ConflictError",
    "Plan",
    "PlanValidationError",
    "Task",
    "TaskDAG",
    "TaskOutcome",
    "TaskStatus",
    "TaskValidation",
    "check_file_isolation",
    "topological_sort",
]
