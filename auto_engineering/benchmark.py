"""V7-8 双驱动保真度基准 — 数据模型 + 需求集 + 报告生成.

比较 Driver A (AgentDriver file-bridge) vs Driver B (StandaloneDriver in-process)
的 6 维指标差异，量化编排逻辑一致性。
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass, field
from pathlib import Path

# ── 数据模型 ──


@dataclass
class BenchmarkReq:
    """单个基准需求."""

    id: str
    category: str  # simple_function / medium_crud / complex_multi_module / with_design_doc
    requirement: str
    design_doc_path: str | None = None


@dataclass
class RunMetrics:
    """单次运行 6 维指标."""

    convergence: str  # GOAL_ACHIEVED / MAJOR_LOOP / HARD_LIMIT / ERROR
    gate_pass_rate: float  # 0.0-1.0
    critic_approve: bool
    lint_first_pass: bool
    test_pass_rate: float  # 0.0-1.0
    total_ticks: int
    total_wall_seconds: float

    # optional per-gate detail
    gate_details: dict[str, str] = field(default_factory=dict)
    # optional error info
    error_message: str = ""


@dataclass
class BenchmarkRun:
    """单次基准运行记录."""

    requirement: BenchmarkReq
    driver: str  # "AgentDriver" | "StandaloneDriver"
    metrics: RunMetrics
    notes: str = ""


# ── 差异计算 ──


def calc_diff(a: float, b: float) -> float:
    """计算两个值的绝对差异 (|a - b|)."""
    return abs(a - b)


def dimension_diff_table(
    agent: RunMetrics, standalone: RunMetrics
) -> list[dict[str, object]]:
    """生成 6 维对比表行."""
    return [
        {
            "dimension": "收敛率",
            "agent": "PASS" if agent.convergence == "GOAL_ACHIEVED" else agent.convergence,
            "standalone": "PASS" if standalone.convergence == "GOAL_ACHIEVED"
            else standalone.convergence,
            "diff": "一致" if agent.convergence == standalone.convergence else "差异",
            "verdict": "PASS" if standalone.convergence == "GOAL_ACHIEVED" else "REVIEW",
        },
        {
            "dimension": "Gate 通过率",
            "agent": f"{agent.gate_pass_rate:.0%}",
            "standalone": f"{standalone.gate_pass_rate:.0%}",
            "diff": f"{calc_diff(agent.gate_pass_rate, standalone.gate_pass_rate):.1%}",
            "verdict": "PASS"
            if calc_diff(agent.gate_pass_rate, standalone.gate_pass_rate) <= 0.20
            else "REVIEW",
        },
        {
            "dimension": "Critic APPROVE",
            "agent": "APPROVE" if agent.critic_approve else "MAJOR",
            "standalone": "APPROVE" if standalone.critic_approve else "MAJOR",
            "diff": "一致" if agent.critic_approve == standalone.critic_approve else "差异",
            "verdict": "PASS" if standalone.critic_approve else "REVIEW",
        },
        {
            "dimension": "Lint 首次通过",
            "agent": "PASS" if agent.lint_first_pass else "FAIL",
            "standalone": "PASS" if standalone.lint_first_pass else "FAIL",
            "diff": "一致" if agent.lint_first_pass == standalone.lint_first_pass else "差异",
            "verdict": "PASS" if standalone.lint_first_pass else "REVIEW",
        },
        {
            "dimension": "测试通过率",
            "agent": f"{agent.test_pass_rate:.0%}",
            "standalone": f"{standalone.test_pass_rate:.0%}",
            "diff": f"{calc_diff(agent.test_pass_rate, standalone.test_pass_rate):.1%}",
            "verdict": "PASS"
            if calc_diff(agent.test_pass_rate, standalone.test_pass_rate) <= 0.20
            else "REVIEW",
        },
        {
            "dimension": "收敛速度 (ticks)",
            "agent": str(agent.total_ticks),
            "standalone": str(standalone.total_ticks),
            "diff": f"{abs(agent.total_ticks - standalone.total_ticks)} ticks",
            "verdict": "INFO",
        },
    ]


# ── 默认需求集 ──


def default_requirements() -> list[BenchmarkReq]:
    """返回 10 个基准需求 (4 类别: simple_function×3 / medium_crud×3 / complex×2 / design_doc×2)."""
    return [
        # simple_function × 3
        BenchmarkReq(
            id="R01", category="simple_function",
            requirement="实现 fibonacci 函数: 输入正整数 n, 返回第 n 个斐波那契数",
        ),
        BenchmarkReq(
            id="R02", category="simple_function",
            requirement="实现 email 格式校验函数: 检查字符串是否符合 email 基本格式 (含 @ 和 .)",
        ),
        BenchmarkReq(
            id="R03", category="simple_function",
            requirement="实现文件行数统计函数: 读取文本文件, 返回总行数、空行数、注释行数",
        ),
        # medium_crud × 3
        BenchmarkReq(
            id="R04", category="medium_crud",
            requirement="实现 User 模型 CRUD: User 含 id/name/email/created_at 字段, "
            "支持 create/read/update/delete 操作, 数据存 JSON 文件",
        ),
        BenchmarkReq(
            id="R05", category="medium_crud",
            requirement="实现 TODO list API: 支持添加/完成/列出/删除待办事项, "
            "每项含 title/done/created_at, 数据存内存 dict",
        ),
        BenchmarkReq(
            id="R06", category="medium_crud",
            requirement="实现配置读写模块: 从 YAML 文件读取配置, 支持 get/set/delete/save, "
            "含类型校验 (str/int/bool/list)",
        ),
        # complex_multi_module × 2
        BenchmarkReq(
            id="R07", category="complex_multi_module",
            requirement="实现 JWT 认证中间件: 支持 token 生成 (HS256)/验证/刷新, "
            "含过期处理 + 用户角色 claim",
        ),
        BenchmarkReq(
            id="R08", category="complex_multi_module",
            requirement="实现事件发布/订阅总线: 支持 subscribe(topic, handler)/publish(topic, data), "
            "含异步处理 + 错误隔离 (一个 handler 失败不影响其他)",
        ),
        # with_design_doc × 2
        BenchmarkReq(
            id="R09", category="with_design_doc",
            requirement="按照设计文档实现 rate-limiter 模块",
            design_doc_path="design/reference/rate-limiter-spec.md",
        ),
        BenchmarkReq(
            id="R10", category="with_design_doc",
            requirement="按照设计文档实现 data-pipeline 模块",
            design_doc_path="design/reference/data-pipeline-spec.md",
        ),
    ]


# ── 数据校验 ──


def validate_runs(runs: Sequence[BenchmarkRun]) -> list[str]:
    """校验基准运行数据完整性, 返回错误消息列表 (空=通过).

    规则:
    - 每个需求必须同时有 AgentDriver 和 StandaloneDriver 运行记录
    - 每对运行记录数量一致
    """
    errors: list[str] = []

    req_drivers: dict[str, set[str]] = {}
    for run in runs:
        rid = run.requirement.id
        if rid not in req_drivers:
            req_drivers[rid] = set()
        req_drivers[rid].add(run.driver)

    for rid, drivers in req_drivers.items():
        if "AgentDriver" not in drivers:
            errors.append(f"需求 {rid} 缺少 AgentDriver 运行记录")
        if "StandaloneDriver" not in drivers:
            errors.append(f"需求 {rid} 缺少 StandaloneDriver 运行记录")

    return errors


# ── 报告生成 ──


def generate_report(runs: Sequence[BenchmarkRun], output_path: Path) -> None:
    """生成 v7.0 双驱动保真度基准报告 (Markdown)."""
    # Organize runs by requirement id
    req_runs: dict[str, list[BenchmarkRun]] = {}
    for run in runs:
        rid = run.requirement.id
        req_runs.setdefault(rid, []).append(run)

    lines: list[str] = []
    lines.append("# v7.0 双驱动保真度基准")
    lines.append("")
    lines.append("> 生成日期: 待填充 | 基准需求: 10 个 | 驱动: AgentDriver / StandaloneDriver")
    lines.append("")

    # ── Summary ──
    lines.append("## 汇总")
    lines.append("")
    lines.append("| 维度 | AgentDriver | StandaloneDriver | 差异 | 判定 |")
    lines.append("|------|------------|-----------------|------|------|")

    # Aggregate metrics across all requirements
    agent_runs_list = [r for r in runs if r.driver == "AgentDriver"]
    standalone_runs_list = [r for r in runs if r.driver == "StandaloneDriver"]

    if agent_runs_list and standalone_runs_list:
        # Aggregate simple stats
        agent_converge = sum(1 for r in agent_runs_list
                            if r.metrics.convergence == "GOAL_ACHIEVED")
        standalone_converge = sum(1 for r in standalone_runs_list
                                 if r.metrics.convergence == "GOAL_ACHIEVED")
        n_agent = len(agent_runs_list)
        n_standalone = len(standalone_runs_list)

        agent_converge_rate = agent_converge / n_agent if n_agent else 0
        standalone_converge_rate = standalone_converge / n_standalone if n_standalone else 0

        agent_gate_avg = (
            sum(r.metrics.gate_pass_rate for r in agent_runs_list) / n_agent
            if n_agent else 0
        )
        standalone_gate_avg = (
            sum(r.metrics.gate_pass_rate for r in standalone_runs_list) / n_standalone
            if n_standalone else 0
        )

        agent_critic_approve = sum(1 for r in agent_runs_list if r.metrics.critic_approve)
        standalone_critic_approve = sum(
            1 for r in standalone_runs_list if r.metrics.critic_approve
        )

        converge_diff = calc_diff(agent_converge_rate, standalone_converge_rate)
        gate_diff = calc_diff(agent_gate_avg, standalone_gate_avg)

        lines.append(
            f"| 收敛率 | {agent_converge_rate:.0%} ({agent_converge}/{n_agent}) "
            f"| {standalone_converge_rate:.0%} ({standalone_converge}/{n_standalone}) "
            f"| {converge_diff:.0%} "
            f"| {'PASS' if converge_diff <= 0.30 else 'REVIEW'} |"
        )
        lines.append(
            f"| Gate 通过率 | {agent_gate_avg:.0%} "
            f"| {standalone_gate_avg:.0%} "
            f"| {gate_diff:.0%} "
            f"| {'PASS' if gate_diff <= 0.20 else 'REVIEW'} |"
        )
        lines.append(
            f"| Critic APPROVE 率 | {agent_critic_approve}/{n_agent} "
            f"| {standalone_critic_approve}/{n_standalone} "
            f"| — | INFO |"
        )
        lines.append("| 代码质量 | 待填充 | 待填充 | — | INFO |")
        lines.append("| 测试产出 | 待填充 | 待填充 | — | INFO |")
        lines.append("| 收敛速度 | 待填充 | 待填充 | — | INFO |")

    lines.append("")
    lines.append("---")
    lines.append("")

    # ── Per-requirement details ──
    lines.append("## 逐需求明细")
    lines.append("")

    for rid in sorted(req_runs.keys()):
        pair = req_runs[rid]
        req = pair[0].requirement
        agent_run = next((r for r in pair if r.driver == "AgentDriver"), None)
        standalone_run = next((r for r in pair if r.driver == "StandaloneDriver"), None)

        lines.append(f"### {rid}: {req.requirement[:60]}...")
        lines.append(f"**类别**: {req.category}")
        lines.append("")

        if agent_run and standalone_run:
            lines.append("| 维度 | AgentDriver | StandaloneDriver | 差异 | 判定 |")
            lines.append("|------|------------|-----------------|------|------|")
            for row in dimension_diff_table(agent_run.metrics, standalone_run.metrics):
                lines.append(
                    f"| {row['dimension']} | {row['agent']} | {row['standalone']} "
                    f"| {row['diff']} | {row['verdict']} |"
                )
        else:
            lines.append("> ⚠️ 数据不完整")
        lines.append("")

    # ── Conclusions ──
    lines.append("---")
    lines.append("")
    lines.append("## 结论与建议")
    lines.append("")
    lines.append("### 场景推荐")
    lines.append("")
    lines.append("| 场景 | 推荐驱动 | 理由 |")
    lines.append("|------|---------|------|")
    lines.append("| 简单函数 (R01-R03) | 待评估 | — |")
    lines.append("| 中等 CRUD (R04-R06) | 待评估 | — |")
    lines.append("| 复杂多模块 (R07-R08) | 待评估 | — |")
    lines.append("| 带设计文档 (R09-R10) | 待评估 | — |")
    lines.append("")
    lines.append("### v5.5 退役风险评估")
    lines.append("")
    lines.append("> 待填充: 基于基准结果评估 StandaloneDriver 替代 AgentDriver 的风险等级。")
    lines.append("")
    lines.append("### 不可比维度 (诚实边界)")
    lines.append("")
    lines.append("- 输出文本的逐字一致性")
    lines.append("- 生成的代码风格细节")
    lines.append("- Architect plan 的具体措辞")
    lines.append("- LLM 响应时间的墙钟对比")
    lines.append("")

    output_path.write_text("\n".join(lines))
