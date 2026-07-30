"""同 fixture/宿主/模型的上下文成本回归比较。"""

from __future__ import annotations

from dataclasses import dataclass

from auto_engineering.metrics.usage_ledger import UsageLedger


class CostBaselineError(ValueError):
    """成本样本不可比较或测量不完整。"""


@dataclass(frozen=True, slots=True)
class CostSnapshot:
    fixture: str
    host: str
    model: str
    completed_work_units: int
    input_units: int
    cache_read_units: int
    cache_write_units: int
    output_units: int
    core_payload_bytes: int
    duplicate_block_bytes: int
    measurement_complete: bool

    @classmethod
    def from_ledger(
        cls,
        ledger: UsageLedger,
        *,
        thread_id: str,
        fixture: str,
        host: str,
        model: str,
        completed_work_units: int,
    ) -> CostSnapshot:
        totals = ledger.aggregate(thread_id)
        if completed_work_units <= 0:
            raise CostBaselineError("completed_work_units 必须为正整数")
        return cls(
            fixture=fixture,
            host=host,
            model=model,
            completed_work_units=completed_work_units,
            input_units=int(totals["input_units"]),
            cache_read_units=int(totals["cache_read_units"]),
            cache_write_units=int(totals["cache_write_units"]),
            output_units=int(totals["output_units"]),
            core_payload_bytes=int(totals["core_payload_bytes"]),
            duplicate_block_bytes=int(totals["duplicate_block_bytes"]),
            measurement_complete=bool(totals["measurement_complete"]),
        )


def compare_costs(
    baseline: CostSnapshot,
    candidate: CostSnapshot,
    *,
    allowed_ratio: float = 1.0,
) -> dict[str, object]:
    """按完成 work unit 归一化比较；不兼容或不完整样本 fail-closed。"""
    if allowed_ratio <= 0:
        raise CostBaselineError("allowed_ratio 必须为正数")
    identity = (baseline.fixture, baseline.host, baseline.model)
    if identity != (candidate.fixture, candidate.host, candidate.model):
        raise CostBaselineError("fixture/host/model 不一致，禁止伪比较")
    if not baseline.measurement_complete or not candidate.measurement_complete:
        raise CostBaselineError("measurement_incomplete")

    fields = (
        "input_units",
        "cache_read_units",
        "cache_write_units",
        "core_payload_bytes",
    )
    ratios: dict[str, float] = {}
    regressions: list[str] = []
    for field in fields:
        before = getattr(baseline, field) / baseline.completed_work_units
        after = getattr(candidate, field) / candidate.completed_work_units
        ratio = after / before if before else (0.0 if after == 0 else float("inf"))
        ratios[field] = ratio
        if ratio > allowed_ratio:
            regressions.append(field)
    if candidate.duplicate_block_bytes != 0:
        regressions.append("duplicate_block_bytes")
    return {
        "passed": not regressions,
        "normalized_ratios": ratios,
        "regressions": regressions,
        "measurement_complete": True,
    }


__all__ = [
    "CostBaselineError",
    "CostSnapshot",
    "compare_costs",
]
