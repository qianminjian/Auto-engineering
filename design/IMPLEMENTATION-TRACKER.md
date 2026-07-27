# Auto-Engineering 当前实施跟踪表

> 更新：2026-07-27｜只记录当前里程碑；完整历史见 `design/archive/INDEX.md`
> 状态：`☐` 未开始｜`◐` 进行中｜`✅` 已验证

## 当前基线

| 里程碑 | 状态 | 证据 |
|---|:---:|---|
| Phase 1-48 | ✅ | `design/archive/legacy/IMPLEMENTATION-TRACKER-pre-phase50.md` |
| Phase 49 Host-neutral Core + Host Adapter | ✅ 22/22 | 双宿主 package/doctor/minimal Tick 基础验收 |
| Phase 50 Codex 迁移全面收口 | ✅ 8/8 | T233-T240 已验证 |

## Phase 50 任务

| 优先级 | ID | 任务 | EARS 验收 | 状态与证据 |
|---:|---|---|---|---|
| P0 | T233 | CI 与测试真实性 | While 测试有失败历史, when 再次收集, the runner shall 仍执行测试而不自动 skip | ✅ 回归测试；全仓 Ruff |
| P0 | T234 | 跨 Agent 规则收口 | While 生成宿主规则, when 执行 sync check, both generated files shall 无漂移且只暴露当前入口 | ✅ 10 tests；sync check |
| P0 | T235 | Host Adapter 契约 | While 新宿主接入, when 实现 Adapter, the implementation shall 不修改 Core 状态机 | ✅ 19 tests；Ruff；mypy |
| P0 | T236 | manifest/依赖/配置 SSOT | While 构建 metadata, when 校验配置, declared values shall 与消费者及 SSOT 一致 | ✅ 85 tests；metadata；Ruff |
| P0 | T237 | Release 双层验收 | While 自动 smoke 完成, when 真实产品安装未执行, the report shall 显示 `not_run` | ✅ JSON 分层报告；6 tests |
| P1 | T238 | 设计资产归档 | While 读取 BEACON, when 定位当前状态, the reader shall 在 80 行内完成并追溯历史 | ✅ 58 行 BEACON；3 tests |
| P1 | T239 | 当前用户文档重写 | While 检索当前文档, when 遇到退役能力, active sections shall 不宣称其可用 | ✅ 20 tests；退役命令零匹配 |
| P0 | T240 | 全量验收与收口 | While Phase 50 收口, when 全部门禁执行, the repository shall 提供新鲜通过证据 | ✅ 1889 tests；coverage 90.15%；SQLite 资源告警清零；静态门禁与双宿主 archive smoke |

## 执行纪律

1. 先把任务标为 `◐`，再修改代码或文档。
2. 功能与缺陷按 Red → Green → Refactor。
3. 验证后记录新鲜命令与结果；不得用历史通过替代。
4. 不通过降低设计标准消除差异。
5. 未经授权不提交、不推送、不发布。

## 本阶段验证索引

| ID | 验证 |
|---|---|
| T233 | `pytest tests/test_test_infrastructure.py`；`ruff check .` |
| T234 | `pytest tests/test_sync_agent_instructions.py`；`sync_agent_instructions.py --check` |
| T235 | `pytest tests/test_host_adapter.py tests/test_codex_hooks.py`；宿主模块 mypy |
| T236 | `pytest tests/test_project_metadata.py ...`；`check_project_metadata.py` |
| T237 | `pytest tests/test_install_acceptance.py tests/test_release_package.py` |
| T238 | `pytest tests/test_design_asset_structure.py` |
| T239 | `pytest tests/test_documentation_contract.py tests/test_project_metadata.py` |
| T240 | 全量 1889 passed / 1 skipped；coverage 90.15%；SQLite 资源告警清零；Claude/Codex archive smoke pass，product install not_run |

## 历史入口

- 完整旧 Tracker：`design/archive/legacy/IMPLEMENTATION-TRACKER-pre-phase50.md`
- 完整旧 BEACON：`design/archive/legacy/BEACON-pre-phase50.md`
- 完整旧设计：`design/archive/legacy/v5.6-Design-Loop-full-history.md`
- 统一索引：`design/archive/INDEX.md`
