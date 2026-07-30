# Auto-Engineering API 参考

> 适用版本：5.6.0｜当前公共契约

## 宿主入口

- Claude Code：`/auto-engineering:dev-loop "需求"`
- Codex：`$auto-engineering`

共同的预检与最小 Tick：

```bash
scripts/ae-run doctor
scripts/ae-run dev-loop --init "需求"
```

## CLI

```bash
scripts/ae-run doctor [--project-root PATH]
scripts/ae-run dev-loop --init "需求"
scripts/ae-run dev-loop --tick --result result.json
scripts/ae-run status --format json
scripts/ae-run dev-loop --resume
```

- `doctor`：检查依赖、宿主、Init manifest 和可选功能。
- `--init`：创建 thread/checkpoint，输出首个 action。
- `--tick`：校验 result 并输出下一 action。
- `status`：读取当前 thread、stage、tick、进度和最近历史。
- `--resume`：从最后有效 checkpoint 恢复。

## Python 宿主 API

```python
from auto_engineering.host import HostPlatform, detect_host
from auto_engineering.host.adapters import adapter_for

detection = detect_host()
adapter = adapter_for(HostPlatform.CODEX)
```

适配器契约：

```python
normalize_event(raw) -> HostEvent | None
resolve_cli(plugin_root) -> tuple[str, ...]
usage_source(project_root) -> UsageSource | None
```

`resolve_cli` 只解析命令候选，不执行 subprocess。Codex 没有可信 transcript usage 时
返回 `None`，不得虚构 Provider。凭据变量不是宿主身份信号。

## Action / Result 文件桥接

Action 是 Core → Agent 的 JSON：

```json
{
  "action": "execute_stage",
  "thread_id": "example",
  "tick": 1,
  "stage": "architect"
}
```

Result 是 Agent → Core 的 JSON，由仓库 schema 约束。消费者必须回传关联标识，
Core 在状态推进前校验 thread、tick 与 stage。

## 配置 API

```python
from auto_engineering.config.runtime_config import RuntimeConfig

config = RuntimeConfig()
```

优先级：进程环境 > `ae.toml` > `FeatureManifest.default_value`。新增 `AE_*` 时先在
`FEATURE_MANIFEST` 注册，再给 `RuntimeConfig` 添加类型化 property。

Provider SDK 可选安装：

```bash
uv sync --extra anthropic
uv sync --extra openai
```

## Release 验收报告

```json
{
  "host": "codex",
  "archive_smoke": {"status": "pass"},
  "product_install": {
    "status": "not_run",
    "reason": "需要在真实宿主产品内执行"
  }
}
```

两个状态独立，不能互相替代。

## 错误与安全

- 用户消息中文，稳定 `error_code` 使用英文。
- 未实现宿主：`HOST_ADAPTER_UNAVAILABLE`。
- CLI 无法解析：`AE_CLI_NOT_FOUND`。
- Git 写操作同时受 capability 与用户授权约束。
- 路径输入必须归一化并执行白名单检查。

当前实现见 `design/v5.6-Design-Loop.md`，已批准目标见
`design/v5.7-Protocol-Kernel-Design.md`，历史摘要见 `design/HISTORY.md`。
