# CHANGELOG

> 从 `design/BEACON.md` 设计决策 + 演进日志回溯关键变更。
> 详细设计决策见 BEACON 决策表（93 项），本文件仅列里程碑级变更。

---

## v5.6 — Tick-Based Discrete Invocation (2026-07)

### v5.6.3 — 全量深度审计修复 (2026-07-23)
- **审计**: 3 Agent 并行深度审计（架构+虚化度/代码质量+工程化/协作友好度），50 项发现
- **FeatureManifest 清理**: AE_LANGSMITH + AE_SUPPRESS_DEPRECATION 虚假 FeatureFlag 移除
- **Git 安全加固**: standalone_driver `_auto_commit` 返回码检查 + escalation gate 不自动通过 + `git add -A`→`.`
- **虚化消除**: DiagnosticRuleDiscoverer + RatchetController 闭环 + ThresholdLearner 接入生产路径
- **God Class 拆分**: EscalationHandler 委托类提取（~220行），TickOrchestrator 1929→~1750行
- **新能力**: AE_PRODUCTION 接入 REDGuardrail + GateRunner, GateExecutionError 异常契约
- **代码清理**: dead import os ×5 + PRBackend 删除 + guardrail_base shim 删除 + `_compute_loc_added` 删除 + TaskDAG 死代码移除
- **工具**: JSON 安全读写工具 `utils/file_utils.py`（safe_json_load/save）
- 2324 tests PASS

### v5.6.2 — 5 层验证提示词增强 + Subagent Spawn (2026-07-22~23)
- Subagent Spawn 强制执行: PromptRegistry 接线到 Tick 路径 + action JSON 注入自然语言指令
- 5 层验证提示词重构: critic/verifier/audit 搬用 Claude Code + Superpowers + gitnexus 标杆
- plate_deep_audit 拆为 3 agent prompt（契约/数据流/架构）+ system_deep_audit 拆为 5 agent prompt
- Gate 多语言适配: TypeCheckGate 按 type_checker_bin 路由配置检测
- 2327 tests PASS

### v5.6.1 — God Class 拆分 + RuntimeConfig 集中化 (2026-07-21)
- **P0-1**: ActionBuilder 委托类（~400行）+ TickGateRunner 委托类（~130行），TickOrchestrator 2321→1885行
- **P0-6**: RuntimeConfig frozen dataclass 替换 49 处 `os.environ` 调用
- **P0-5**: 31 处裸 except Exception 窄化为 10 种具体异常类型
- 虚化代码 ~533→0 行（Phase 30 第二轮审计修复）
- 2358 tests PASS

### v5.6.0 — 初始版本 (2026-06~07)
- Tick-Based Discrete Invocation 协议: Python 每次 tick 独立进程，文件桥接
- 5 层验证架构: critic → component_verifier → plate_deep_audit → system_verifier → system_deep_audit
- 7+1 Gate 体系: safety/lint/type_check/audit/contract/test/build + deep_audit
- 12 Guardrail: pass/block/retry 三态 + REDGuardrail/FreshGuardrail/RegressionGuardrail
- ConvergenceJudge: 4 级收敛判定（hard/quality/stagnant/semantic）
- SQLite Checkpoint: WAL 持久化 + 跨进程恢复
- Init-Loop 接口契约: 消费 Init 项目 `.ae-state/init-manifest.json`
- Init Engineering 拆分独立项目（BEACON #30）

---

## v7.0 — 双驱动架构 (2026-07)

- **AgentDriver** (Driver A): Agent 工具调用 ae CLI，文件桥接
- **StandaloneDriver** (Driver B): 进程内 AgentRuntime 自带 key 调 LLM，回喂同一 tick 循环
- 双驱动共享: 引擎层 TickOrchestrator + 5 层验证 + 7+1 Gates + 12 Guardrail
- 能力覆盖矩阵: 15+ 模块双驱动状态标注（架构固有/设计替代/未实现）
- 国产 Provider 适配: GLM/通义/文心 + Ollama（仅 StandaloneDriver 可达）

---

## v5.0 — Plugin + Loop + Init 合订 (2026-06~07)

- Claude Code Plugin 形态: Bash 委托 `ae <subcommand>`，控制流在 Python
- 三阶段 Agent 循环: Architect → Developer → Critic
- StageRouter T1-T22 转换表 + MAJOR 计数 + refine_allowed
- PII 四层防护: L1 init 扫描 + L2 outbound redact + L3 inbound scan + L4 file guardrail
- AI Coding 度量与自进化体系: M1-M5 5 核心指标 + SignalDetector + RatchetController
- OTLP 分布式追踪 + AuditLogger 审计日志

---

## 破坏性变更

| 版本 | 变更 | 迁移 |
|------|------|------|
| v5.6 | v5.5 Orchestrator 连续 while 循环退役 | BEACON #53, 30 天过渡期至 2026-08-18 |
| v5.6 | RuntimeConfig 集中式 env 访问（49→1 入口） | BEACON #87 |
| v5.6 | ErrorCode 枚举精简（14→13→14） | P2-40 GATE_EXECUTION_ERROR 新增 |
| v5.6 | `Verdict`→`GateVerdict` 别名废弃 | BEACON P2-15, v6.0 移除 |
| v5.6 | 参考源码迁出项目根（96GB 内存事故后） | 路径 `$AE_REFS_DIR/` |

---

_完整设计决策见 `design/BEACON.md`（93 项决策 + 演进日志）。_
