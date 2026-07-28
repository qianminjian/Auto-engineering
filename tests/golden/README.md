# 黄金轨迹 Fixture

每个 fixture 必须包含 `events`、`projection`、`action` 和 `verdict` 四个区段。
比较器只忽略随机消息/事件 ID、时间字段及 `extensions.host` 展示信息；其他字段
均视为业务语义并进行精确比较。

后续轨迹按一个场景一个 JSON 文件存放，文件名使用行为名称，不使用测试编号。

`critical-trajectories.json` 固化十类关键路径；对应的真实 Core 行为仍由 Tick、
事务、Guardrail、Checkpoint 与重放测试覆盖，黄金层负责跨版本语义快照比较。
