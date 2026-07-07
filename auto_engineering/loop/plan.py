"""v2.0 Phase 03 — Task DAG + Plan 构建 + 文件隔离检查.

设计来源: design/v2.0-Analysis-Loop.md §4.3 文件隔离 + §4.5 多 Agent 并发.

核心组件:
    Task           — 单个任务 (id / role / target_files / depends_on)
    TaskDAG        — DAG 容器 + 拓扑排序 (Kahn 算法)
    Plan           — 完整计划 (task list + validate + parallelism_groups)
    ConflictError  — 文件冲突异常
    check_file_isolation — 任意两个并行 task 的 target_files 无交集

任务拆分五原则(§4.8):
    1. 文件隔离    — Plan.validate() 调用 check_file_isolation 强制保证
    2. 契约优先    — 跨 Agent 协作的 task 先产契约文件(由 Orchestrator 调度)
    3. 依赖最小化  — 每个 task 的 deps ≤ 2(由人工拆分阶段保证)
    4. 粒度均衡    — 每个 task 预估 20-45 分钟(由人工拆分阶段保证)
    5. 闭环        — 每个 task 产出可独立验证(由 TaskValidation 保证)
"""

from __future__ import annotations

from collections import defaultdict, deque
from collections.abc import Iterable
from dataclasses import dataclass, field
from enum import StrEnum
from typing import Any


class TaskStatus(StrEnum):
    """Task 生命周期状态."""

    PENDING = "pending"
    IN_PROGRESS = "in_progress"
    COMPLETED = "completed"
    FAILED = "failed"
    BLOCKED = "blocked"


# Task 合法角色枚举 (v2.0-D 加 contract 校验)
VALID_TASK_ROLES = frozenset({"developer", "critic", "reviewer", "architect"})


class ConflictError(Exception):
    """文件冲突异常 — Orchestrator 拆分失败时抛."""

    def __init__(self, conflicts: list[str], suggestion: str = "") -> None:
        self.conflicts = conflicts
        self.suggestion = suggestion or (
            "将冲突文件合并到同一个 Task 顺序执行, "
            "或拆分到不同的源文件以消除冲突"
        )
        super().__init__(
            f"文件冲突 ({len(conflicts)} 处):\n  - "
            + "\n  - ".join(conflicts)
            + f"\n建议: {self.suggestion}"
        )


@dataclass
class TaskValidation:
    """Task 验证规则 (v2.0-D 新增).

    Attributes:
        required_files: 必须存在的文件列表 (Gate 子集)
        required_outputs: 必须输出的内容列表 (字符串 pattern)
        max_minutes: 最大耗时 (超过算失败)
    """

    required_files: list[str] = field(default_factory=list)
    required_outputs: list[str] = field(default_factory=list)
    max_minutes: int | None = None


@dataclass
class Task:
    """单个任务单元 (v2.0-D 字段补全: 设计文档 §3.2).

    Attributes:
        id: 唯一标识 (由 Orchestrator 拆分时分配)
        title: 人读任务标题 (新字段, v2.0-D)
        description: 四段式指令 (目标/边界/验收标准/禁止项)
        expected_output: 期望输出 (新字段, contract 的一部分)
        role: 执行 Agent 角色 developer|critic|reviewer|architect (新字段)
        target_files: 涉及的文件路径集合 (用于文件隔离检查)
        context_files: 上下文文件列表 (只读, 新字段)
        validation: 验证规则 (Gate 子集, 新字段)
        depends_on: 前置 Task ID 列表 (v5.5 audit P0-6: 统一字段, 废弃 deps)
        estimated_minutes: 预估耗时 (供 Round Close 监控)
        status: 任务状态
        output: 任务输出 (新字段, 完成后赋值)
        agent_type: Deprecated property, delegates to role (v5.5 P1-7)
    """

    id: str
    title: str = ""
    description: str = ""
    expected_output: str = ""
    role: str = "developer"
    target_files: frozenset[str] = field(default_factory=frozenset)
    context_files: list[str] = field(default_factory=list)
    validation: TaskValidation | None = None
    depends_on: list[str] = field(default_factory=list)
    estimated_minutes: int = 30
    status: TaskStatus = TaskStatus.PENDING
    output: Any = None
    # v5.5 Phase 3: batch_plan 扩展字段 (verification + steps)
    verification: str | None = None
    steps: list[str] | None = None

    def __post_init__(self) -> None:
        """归一化 target_files 为 frozenset[str] (允许 list/set 输入)."""
        if not isinstance(self.target_files, frozenset):
            self.target_files = frozenset(self.target_files)
        self.depends_on = list(self.depends_on)
        self.context_files = list(self.context_files)

    # v5.5 P1-7: agent_type → role 统一, agent_type 作为 deprecated property
    @property
    def agent_type(self) -> str:
        """Deprecated: use role instead."""
        return self.role

    @agent_type.setter
    def agent_type(self, value: str) -> None:
        """Deprecated: set role instead."""
        self.role = value


@dataclass
class TaskDAG:
    """Task DAG 容器 — 节点 + 拓扑排序.

    算法: Kahn's algorithm (BFS 入度消减).
    时间复杂度: O(V + E).
    """

    tasks: dict[str, Task] = field(default_factory=dict)

    def add_task(self, task: Task) -> None:
        """添加 Task, 重复 ID 抛 ValueError."""
        if task.id in self.tasks:
            raise ValueError(f"Task id '{task.id}' already in DAG")
        self.tasks[task.id] = task

    def validate_deps(self) -> None:
        """校验 depends_on 引用真实存在."""
        for task in self.tasks.values():
            for dep in task.depends_on:
                if dep not in self.tasks:
                    raise ValueError(
                        f"Task '{task.id}' depends on missing task '{dep}'"
                    )

    def topological_sort(self) -> list[str]:
        """Kahn 算法拓扑排序.

        Returns:
            拓扑顺序的 task id 列表

        Raises:
            ValueError: 存在循环依赖或缺失依赖
        """
        self.validate_deps()
        # 计算入度
        in_degree: dict[str, int] = dict.fromkeys(self.tasks, 0)
        # 邻接表: task → 依赖它的 task 列表
        dependents: dict[str, list[str]] = defaultdict(list)
        for task in self.tasks.values():
            for dep in task.depends_on:
                dependents[dep].append(task.id)
                in_degree[task.id] += 1

        # 入度为 0 的入队
        queue: deque[str] = deque(
            tid for tid, deg in in_degree.items() if deg == 0
        )
        order: list[str] = []
        while queue:
            current = queue.popleft()
            order.append(current)
            for dependent in dependents[current]:
                in_degree[dependent] -= 1
                if in_degree[dependent] == 0:
                    queue.append(dependent)

        if len(order) != len(self.tasks):
            # 剩余节点的入度 > 0 → 循环依赖
            stuck = [tid for tid, deg in in_degree.items() if deg > 0]
            raise ValueError(
                f"Cycle detected in task DAG: stuck tasks = {stuck}"
            )
        return order


def topological_sort(tasks: Iterable[Task]) -> list[str]:
    """便捷函数: 输入 task 列表, 返回拓扑排序后的 id 列表."""
    dag = TaskDAG()
    for task in tasks:
        dag.add_task(task)
    return dag.topological_sort()


def check_file_isolation(
    tasks: Iterable[Task],
    raise_on_conflict: bool = False,
) -> list[str]:
    """检查并行执行的 Task 是否有文件冲突.

    算法:
        1. 按 topological levels 分组 (同一 level 的 task 并行)
        2. 每个 level 内: 检查任意两个 task 的 target_files 是否有交集
        3. workspace 边界校验 (P0-3 安全): 拒绝绝对路径 / ../ / ~ 逃逸

    Args:
        tasks: Task 列表 (迭代器, 可以是列表/生成器)
        raise_on_conflict: True 时若发现冲突抛 ConflictError

    Returns:
        冲突描述列表, 空列表表示无冲突

    Raises:
        ConflictError: 当 raise_on_conflict=True 且:
            - 同 level 内文件冲突, 或
            - target_files 含绝对路径 / ../ / ~ (workspace 逃逸)

    Note:
        串行的两个 task (有 depends_on 关系) 即使共享文件也不算冲突
        因为它们不会并行执行
    """
    task_list = list(tasks)
    if not task_list:
        return []

    # P0-3 workspace 边界校验: 拒绝逃逸出 project_root 的路径
    workspace_violations: list[str] = []
    for task in task_list:
        for file_path in task.target_files:
            if not file_path:
                continue
            # 绝对路径 (Unix / Windows)
            if file_path.startswith("/") or (len(file_path) >= 2 and file_path[1] == ":"):
                workspace_violations.append(
                    f"task '{task.id}': target_files 含绝对路径 '{file_path}' "
                    f"(workspace 逃逸禁止)"
                )
                continue
            # 父目录逃逸
            if ".." in file_path.split("/"):
                workspace_violations.append(
                    f"task '{task.id}': target_files 含 ../ 路径 '{file_path}' "
                    f"(workspace 逃逸禁止)"
                )
                continue
            # 主目录展开 (常见攻击向量)
            if file_path.startswith("~"):
                workspace_violations.append(
                    f"task '{task.id}': target_files 含 ~ 路径 '{file_path}' "
                    f"(workspace 逃逸禁止)"
                )
    if workspace_violations and raise_on_conflict:
        raise ConflictError(workspace_violations)
    if workspace_violations:
        return workspace_violations

    # 按 topological level 分组
    levels = _topological_levels(task_list)

    conflicts: list[str] = []
    for level_idx, level_tasks in enumerate(levels):
        # 该 level 内, file → 持有 task id
        seen: dict[str, str] = {}
        for task in level_tasks:
            for file_path in task.target_files:
                if file_path in seen:
                    owner = seen[file_path]
                    conflicts.append(
                        f"L{level_idx}: 文件 {file_path} 同时被 "
                        f"'{owner}' 和 '{task.id}' 修改 (并行冲突)"
                    )
                else:
                    seen[file_path] = task.id

    if conflicts and raise_on_conflict:
        raise ConflictError(conflicts)
    return conflicts


def _topological_levels(tasks: list[Task]) -> list[list[Task]]:
    """按拓扑层级分组 (Kahn BFS 分层): 同一层的 task 可并行.

    Returns:
        list[list[Task]]: 外层按层序, 内层同层 task (按 id 排序)

    Raises:
        ConflictError: DAG 含循环依赖时
    """
    if not tasks:
        return []

    task_map = {t.id: t for t in tasks}

    # 计算入度 (只统计 batch 内 deps; 外部 dep 不计入)
    in_degree: dict[str, int] = {}
    for t in tasks:
        in_degree[t.id] = sum(1 for d in t.depends_on if d in task_map)

    # Kahn BFS 分层
    current: list[Task] = [t for t in tasks if in_degree[t.id] == 0]
    current.sort(key=lambda t: t.id)
    layers: list[list[Task]] = []
    seen: set[str] = set()

    while current:
        layers.append(current)
        seen.update(t.id for t in current)
        next_level: list[Task] = []
        for task in current:
            for other in tasks:
                if other.id not in seen and task.id in other.depends_on:
                    in_degree[other.id] -= 1
                    if in_degree[other.id] == 0:
                        next_level.append(other)
        next_level.sort(key=lambda t: t.id)
        current = next_level

    # 环检测: 有 task 未被访问 → 存在循环依赖
    if len(seen) < len(tasks):
        remaining = [t.id for t in tasks if t.id not in seen]
        raise ConflictError([f"cycle detected involving: {', '.join(remaining)}"])

    return layers


@dataclass
class Plan:
    """完整任务计划.

    Attributes:
        tasks: Task 列表
        requirement: 原始需求描述 (供 Round Close 报告)
        created_at: 创建时间戳 (ISO format)
    """

    tasks: list[Task]
    requirement: str = ""
    created_at: str = ""

    def validate(self) -> None:
        """校验 Plan 合法性:
            1. DAG 无循环 (topological_sort 内部检查)
            2. 并行 task 的 target_files 无交集
            3. contract 校验 (v2.0-D):
               - 每个 task.title 非空
               - 每个 task.expected_output 非空
               - 每个 task.role 在枚举中 (developer/critic/reviewer/architect)
        """
        if not self.tasks:
            return  # 空 plan 不报错
        # topological_sort 会检查循环
        topological_sort(self.tasks)
        # 文件隔离检查
        check_file_isolation(self.tasks, raise_on_conflict=True)
        # contract 校验 (v2.0-D)
        self._validate_contracts()

    def _validate_contracts(self) -> None:
        """校验每个 task 的 contract 字段 (title/expected_output/role).

        设计文档 §3.2: 任务拆分五原则 — 每个 task 必须有明确目标、期望输出、合法角色.
        这是"契约优先"原则 (Orchestrator 调度时知道每个 task 要什么).

        v5.0 §IL.3: tasks.yml 的 init_metadata (template_source / generated_by)
        和 B1.3 Task 模型未定义的其他字段 (如 future 字段) 静默忽略 — 仅
        记录在 __dict__ 扩展属性中, 不参与 contract 校验 (forward-compat).
        """
        for task in self.tasks:
            if not task.title or not task.title.strip():
                raise ValueError(
                    f"Task '{task.id}': title 不能为空 (Plan.validate contract 校验)"
                )
            if not task.expected_output or not task.expected_output.strip():
                raise ValueError(
                    f"Task '{task.id}': expected_output 不能为空 "
                    f"(Plan.validate contract 校验)"
                )
            if task.role not in VALID_TASK_ROLES:
                raise ValueError(
                    f"Task '{task.id}': role '{task.role}' 不合法 "
                    f"(必须为 {sorted(VALID_TASK_ROLES)} 之一)"
                )
            # v5.0 §IL.3: init_metadata / 未知字段静默忽略
            # 仅 dataclass 定义的字段参与校验, __dict__ 扩展属性 (init_metadata
            # + future 字段) 不消费, 不阻断, 保持 forward-compat
            # (无显式 action — dataclass 字段 + B1.3 校验已覆盖)

    def add_tasks(self, new_tasks: list[Task]) -> None:
        """追加 Task 列表并重新校验 (替代直接修改 self.tasks).

        用途: architect 产出 batch_plan 后, 将新 task 动态注入 Plan.
        与直接 self.tasks.extend() 不同, 此方法会重新校验 Plan 合法性
        (DAG 循环 / 文件隔离 / contract), 避免非法 task 进入执行流水线.
        """
        self.tasks.extend(new_tasks)
        self.validate()

    def parallelism_groups(self) -> list[list[str]]:
        """返回并行组列表: 外层按层序, 内层是同层 task id 列表.

        用法:
            groups = plan.parallelism_groups()
            for group in groups:
                await asyncio.gather(*[run_task(tid) for tid in group])

        Raises:
            ConflictError: Plan DAG 含循环依赖时 (_topological_levels ValueError 转换).
        """
        if not self.tasks:
            return []
        levels = _topological_levels(self.tasks)
        return [[t.id for t in level] for level in levels]

    def get_tasks_by_stage(self, stage: str) -> list[Task]:
        """按 stage (= task.role) 过滤本 Plan 中的 Task.

        Args:
            stage: 目标 stage 名 ("architect" | "developer" | "critic").

        Returns:
            role == stage 的 Task 子集; 无匹配或空 Plan 返回 [].

        用法 (Orchestrator v5.0 §B7.1 step 2c):
            tasks = plan.get_tasks_by_stage("architect")
            await run_round(tasks, ...)
        """
        return [t for t in self.tasks if t.role == stage]

    def get_task(self, task_id: str) -> Task | None:
        """按 id 查找 Task."""
        for task in self.tasks:
            if task.id == task_id:
                return task
        return None


__all__ = [
    "VALID_TASK_ROLES",
    "ConflictError",
    "Plan",
    "Task",
    "TaskDAG",
    "TaskStatus",
    "TaskValidation",
    "check_file_isolation",
    "topological_sort",
]