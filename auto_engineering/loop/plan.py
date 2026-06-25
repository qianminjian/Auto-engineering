"""v2.0 Phase 03 — Task DAG + Plan 构建 + 文件隔离检查.

设计来源: design/v2.0-Analysis-Loop.md §4.3 文件隔离 + §4.5 多 Agent 并发.

核心组件:
    Task           — 单个任务 (id / agent_type / target_files / depends_on)
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


class TaskStatus(StrEnum):
    """Task 生命周期状态."""

    PENDING = "pending"
    IN_PROGRESS = "in_progress"
    COMPLETED = "completed"
    FAILED = "failed"
    BLOCKED = "blocked"


class ConflictError(Exception):
    """文件冲突异常 — Orchestrator 拆分失败时抛."""

    def __init__(self, conflicts: list[str]) -> None:
        self.conflicts = conflicts
        super().__init__(
            f"文件冲突 ({len(conflicts)} 处):\n  - " + "\n  - ".join(conflicts)
        )


@dataclass
class Task:
    """单个任务单元.

    Attributes:
        id: 唯一标识 (由 Orchestrator 拆分时分配)
        agent_type: 执行 Agent 角色 (developer | critic | reviewer ...)
        description: 四段式指令 (目标/边界/验收标准/禁止项)
        target_files: 涉及的文件路径集合 (用于文件隔离检查)
        depends_on: 前置 Task ID 列表
        estimated_minutes: 预估耗时 (供 Round Close 监控)
    """

    id: str
    agent_type: str
    description: str
    target_files: frozenset[str] = field(default_factory=frozenset)
    depends_on: list[str] = field(default_factory=list)
    estimated_minutes: int = 30
    status: TaskStatus = TaskStatus.PENDING

    def __post_init__(self) -> None:
        """归一化 target_files 为 frozenset[str] (允许 list/set 输入)."""
        if not isinstance(self.target_files, frozenset):
            object.__setattr__(self, "target_files", frozenset(self.target_files))
        # depends_on 拷贝避免外部修改
        object.__setattr__(self, "depends_on", list(self.depends_on))


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

    Args:
        tasks: Task 列表 (迭代器, 可以是列表/生成器)
        raise_on_conflict: True 时若发现冲突抛 ConflictError

    Returns:
        冲突描述列表, 空列表表示无冲突

    Note:
        串行的两个 task (有 depends_on 关系) 即使共享文件也不算冲突
        因为它们不会并行执行
    """
    task_list = list(tasks)
    if not task_list:
        return []

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
    """按拓扑层级分组: 同一层的 task 可并行.

    Returns:
        list[list[Task]]: 外层按层序, 内层同层 task
    """
    if not tasks:
        return []

    task_map = {t.id: t for t in tasks}
    # 计算每个 task 的层级 (最长依赖链长度)
    level_cache: dict[str, int] = {}

    def get_level(task_id: str, visiting: set[str] | None = None) -> int:
        if task_id in level_cache:
            return level_cache[task_id]
        visiting = visiting or set()
        if task_id in visiting:
            raise ValueError(f"Cycle detected at {task_id}")
        visiting.add(task_id)
        task = task_map[task_id]
        if not task.depends_on:
            level_cache[task_id] = 0
            return 0
        max_dep_level = max(
            get_level(dep, visiting) for dep in task.depends_on
        )
        level = max_dep_level + 1
        level_cache[task_id] = level
        return level

    # 计算所有 task 的 level
    for task in tasks:
        get_level(task.id)

    # 按 level 分组
    grouped: dict[int, list[Task]] = defaultdict(list)
    for task in tasks:
        grouped[level_cache[task.id]].append(task)

    # 按 level 升序返回
    max_level = max(level_cache.values())
    return [grouped[i] for i in range(max_level + 1)]


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
        """
        if not self.tasks:
            return  # 空 plan 不报错
        # topological_sort 会检查循环
        topological_sort(self.tasks)
        # 文件隔离检查
        check_file_isolation(self.tasks, raise_on_conflict=True)

    def parallelism_groups(self) -> list[list[str]]:
        """返回并行组列表: 外层按层序, 内层是同层 task id 列表.

        用法:
            groups = plan.parallelism_groups()
            for group in groups:
                await asyncio.gather(*[run_task(tid) for tid in group])
        """
        if not self.tasks:
            return []
        levels = _topological_levels(self.tasks)
        return [[t.id for t in level] for level in levels]

    def get_task(self, task_id: str) -> Task | None:
        """按 id 查找 Task."""
        for task in self.tasks:
            if task.id == task_id:
                return task
        return None


__all__ = [
    "ConflictError",
    "Plan",
    "Task",
    "TaskDAG",
    "TaskStatus",
    "check_file_isolation",
    "topological_sort",
]