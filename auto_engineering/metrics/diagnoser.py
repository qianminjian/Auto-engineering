"""Diagnoser — 规则引擎，将信号映射为诊断 (T67, F.5-aligned).

5 条诊断规则，每条含 auto_params + human_actions 显式标注.
"""
from dataclasses import dataclass, field

from auto_engineering.metrics.signals import Signal


@dataclass
class Diagnosis:
    """诊断结果 (F.5-aligned)."""
    signal_name: str
    severity: str = ""
    possible_causes: list[str] = field(default_factory=list)
    suggested_actions: list[str] = field(default_factory=list)
    auto_adjustable: list[str] = field(default_factory=list)
    needs_human: list[str] = field(default_factory=list)


class Diagnoser:
    """信号→诊断映射引擎 (F.5-aligned).

    每条规则定义：
    - actions: 完整 action 列表（含自动和人工）
    - auto_params: 可自动调整参数列表
    - human_actions: 需要人工判断的 action 索引
    """

    def __init__(self) -> None:
        self._rules: dict[str, dict] = {
            "critic_major_increasing": {
                "name": "critic 打回率上升",
                "auto_params": [],
                "possible_causes": [
                    "需求规格模糊 → architect 产出不精确 → developer 实现偏差",
                    "设计文档与代码实现之间的语义 gap 扩大",
                    "developer prompt 漂移或模型版本变更",
                ],
                "actions": [
                    "触发 gap_scan 复审，检查需求/设计文档是否需要细化",
                    "检查最近 5 次的 critic findings 是否集中在特定组件",
                ],
                "human_actions": [0, 1],
            },
            "plan_refine_spike": {
                "name": "计划频繁返工",
                "auto_params": ["max_refine_per_source"],
                "possible_causes": [
                    "设计文档与实现差距累积，非单次问题",
                    "需求本身复杂度被低估",
                ],
                "actions": [
                    "建议拆分需求为多个 Phase",
                    "或在 design_doc 中标注设计项为'分阶段实现'",
                ],
                "human_actions": [0, 1],
            },
            "slow_convergence": {
                "name": "收敛效率下降",
                "auto_params": ["max_iter"],
                "possible_causes": [
                    "batch_plan 粒度过细，tick 数膨胀",
                    "需求复杂度被低估",
                    "context 膨胀导致 LLM 效率下降",
                ],
                "actions": [
                    "检查 batch 拆分策略，考虑合并小 batch",
                    "检查 context offloading 是否正常触发",
                ],
                "human_actions": [0, 1],
            },
            "token_efficiency_drop": {
                "name": "Token 效率下降",
                "auto_params": ["token_budget_warning"],
                "possible_causes": [
                    "上下文膨胀（冗余文件或过长设计文档）",
                    "context offloading 阈值设置不当",
                ],
                "actions": [
                    "检查 context 裁剪策略",
                    "触发 context offloading",
                ],
                "human_actions": [],
            },
            "verification_always_leaf": {
                "name": "验证深度不足",
                "auto_params": [],
                "possible_causes": [
                    "设计文档层次简单（合法场景）",
                    "深层 audit 触发逻辑有 bug",
                ],
                "actions": [
                    "检查验证裁剪逻辑是否正确",
                    "手动触发一次 FULL 验证作为对照",
                ],
                "human_actions": [0, 1],
            },
        }

    def diagnose(self, signal: Signal) -> Diagnosis | None:
        """根据信号查找诊断规则 (F.5-aligned)."""
        rule = self._rules.get(signal.name)
        if rule is None:
            return None
        human_indices = set(rule.get("human_actions", []))
        all_actions: list[str] = rule.get("actions", [])
        suggested = list(all_actions)
        human = [a for i, a in enumerate(all_actions) if i in human_indices]
        return Diagnosis(
            signal_name=signal.name,
            severity=signal.severity,
            possible_causes=list(rule.get("possible_causes", [])),
            suggested_actions=suggested,
            auto_adjustable=list(rule.get("auto_params", [])),
            needs_human=human,
        )
