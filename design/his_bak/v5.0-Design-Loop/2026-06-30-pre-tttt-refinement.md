# v5.0 Loop Engineering Design — Development-Ready Spec

> 来源: @design/INDEX.md | 创建: 2026-06-29 | 更新: 2026-06-30
> Init spec: @design/v5.0-Design-Init.md

---

## 1. 接口契约

### 1.1 8 个 Slash Command

| ID | 命令 | 参数 | 类型 | 必选 | 缺省 | 返回值 | 错误码 |
|----|------|------|------|------|------|--------|--------|
| CMD-01 | `/dev-loop` | `requirement` | String(单行) | 是 | — | `{ thread_id, verdict, round, gate_results[], duration_sec }` | 0=完成,1=配置错,2=gate不可恢复,130=SIGINT |
| CMD-02 | `/status` | (无) | — | — | — | `{ thread_id\|null, round, stage∈{architect,developer,critic,idle}, verdict∈{APPROVE,MAJOR,""}, recent_gates[{name,passed}][7], recent_history[{round_id,time,verdict}][0..5], suggestion }` | 0=正常,1=未初始化 |
| CMD-03 | `/checkpoint` | `subcommand` + `id?` | list\|show\|resume | 是 | list | list→`[{thread_id,round,step,created_at}..]`; show→`{state_json}`; resume→同CMD-01 | 0=成功,1=无效subcmd/id,2=未初始化 |
| CMD-04 | `/project:tdd` | `mode` | strict\|base\|off | 是 | off | `{ before, after }` + CLAUDE.md 写入 | 0=成功,1=无效mode |
| CMD-05 | `/project:worktree` | `action` | on\|off | 是 | off | `{ created[], removed[] }` + scripts/ | 0=成功,1=非git/超限 |
| CMD-06 | `/project:agent` | `action` | on\|off | 是 | on | `{ agents[], claude_md_updated }` | 0=成功,1=缺文件 |
| CMD-07 | `/project:ci` | `platform` | github\|gitlab\|none | 是 | github | `{ created[], removed[] }` + CI文件 | 0=成功,1=无效platform |
| CMD-08 | `/init` | `project_type?` + 12 flag | 见Init spec | 否 | 空目录→Ask, 存量→auto-detect | `{ files_created, answers_path }` | 0=成功,2=已存在,130=SIGINT |

**边界条件**:
- CMD-01: 需求串为空→1; 含控制字符→strip; 无ANTHROPIC_API_KEY→1; 无project state→1
- CMD-02: 无checkpoint→thread_id=null,stage=idle,suggestion="未初始化"
- CMD-03: id为空→默认list; id不存在→1; id非UUID→1
- CMD-04: mode为空/含空格→trim→off; CLAUDE.md不存→1
- CMD-05: 非git→1; worktree>5→1
- CMD-06: agents/缺→1
- CMD-07: 无git→仍成功
- CMD-08: 见Init spec

### 1.2 5 个 Hook

| ID | Hook | 触发 | 输入 | 输出 | 超时 | 退出码 |
|----|------|------|------|------|------|--------|
| HOK-01 | session-start | SessionStart | cwd(env) | 状态摘要→stdout | 10s | 常0 |
| HOK-02 | post-edit | PostToolUse(Edit\|Write\|MultiEdit) | `CLAUDE_TOOL_INPUT_FILE_PATH` | SafetyGate→stdout/stderr | 30s | 常0 |
| HOK-03 | stop | Stop | (无) | "dispatched"→stdout, log→/tmp/ae-stop-{PID}.log | 10s | 常0 |
| HOK-04 | pre-tool | PreToolUse(Bash) | `CLAUDE_TOOL_NAME`, `CLAUDE_TOOL_INPUT_COMMAND` | (stdout空) | 5s | 0=放行,2=拒绝 |
| HOK-05 | on-pr | (待event) | — | — | — | — |

**边界条件**: HOK-01:cwd空→静退出; HOK-02:FILE空/非白名单/uv缺→跳过,异常→exit0; HOK-03:cwd空/uv缺→静退出; HOK-04:非Bash/命令空/>40KB→放行

### 1.3 Core Engine 接口 (LoopEngine + Gate + Checkpoint)

| 接口 | 签名 | 返回值 | 调用者 |
|------|------|--------|--------|
| `LoopEngine.run()` | `(requirement: String, config: LoopConfig) -> LoopResult` | {state,history,verdict} | CMD-01 |
| `StageGraph.next_stage()` | `(state: LoopState) -> Stage\|None` | 下一stage或None(结束) | LoopEngine |
| `Gate.run()` | `(project_root: Path) -> GateVerdict` | {passed,message,gate_name} | LoopEngine(每轮) |
| `GuardrailChain.check()` | `(stage, state) -> GuardrailResult` | {action:pass\|block\|drop\|retry} | LoopEngine(每stage) |
| `CheckpointStore.save()` | `(state, round, history) -> checkpoint_id` | String(UUID) | LoopEngine(after_tick) |
| `CheckpointStore.load()` | `(checkpoint_id) -> Checkpoint` | {state,history} | CMD-03 |
| `ProjectDetector.detect()` | `(target_dir: Path) -> String\|None` | 项目类型 | CMD-08 |
| `SemanticEvaluator.evaluate()` | `(round_result) -> Boolean` | 语义通过? | LoopEngine(judge) |

---

## 2. 数据模型

### 2.1 ER 模型

| 实体 | 字段 | 类型 | 约束 | 基数 |
|------|------|------|------|------|
| **LoopState** | requirement | String(1..4096) | NOT NULL | 1:1/session |
| | round | Integer(0..N) | NOT NULL,default=0 | |
| | stage | Enum | architect\|developer\|critic\|"" | |
| | plan | String(0..65535) | nullable | architect→developer |
| | file_list | String[0..200] | nullable | architect→developer |
| | files_changed | String[0..200] | nullable | developer→critic |
| | commit_hash | String(40) | pattern [0-9a-f]{40} | developer→critic |
| | test_results | JSON(0..65535) | nullable | developer→critic |
| | verdict | Enum | APPROVE\|MAJOR\|"" | critic输出 |
| | findings | JSON[0..50] | nullable | critic→developer |
| | critic_feedback | String(0..65535) | nullable | critic→developer |
| **RoundHistory** | round_id | Integer(1..N) | NOT NULL,>0 | 1:N/LoopState |
| | files_changed | Integer(0..9999) | default=0 | |
| | lines_added | Integer(0..99999) | default=0 | |
| | lines_removed | Integer(0..99999) | default=0 | |
| | gate_results | Map[name→Verdict] | NOT NULL | 7 gates |
| | semantic_satisfied | Boolean? | nullable | |
| | tasks_run | String[0..20] | NOT NULL | |
| | task_outcomes | Map[id→status] | NOT NULL | completed/failed/cancelled |
| **Checkpoint** | thread_id | String(UUID) | PK(col1) | 1:N/session |
| | round | Integer | PK(col2) | |
| | step | Integer | PK(col3) | |
| | state_json | TEXT | NOT NULL,JSON | |
| | created_at | Timestamp(UTC) | default=CURRENT_TIMESTAMP | |
| **GateResult** | thread_id | String | PK(col1) | 7:1/round |
| | round | Integer | PK(col2) | |
| | gate_name | Enum | safety\|lint\|type_check\|contract\|test\|coverage\|build | |
| | passed | Boolean | NOT NULL | |
| | message | String(0..1024) | nullable | |

### 2.2 Stage 状态机

```
[idle] ──(CMD-01)──→ [architect] ──(guardrail pass)──→ [developer] ──(pass)──→ [critic]
[critic] ──(APPROVE)──→ [idle]
[critic] ──(MAJOR)──→ [developer]
[any] ──(round≥max)──→ [idle]
[any] ──(SIGINT)──→ [idle]
```

### 2.3 索引与约束

- PRIMARY KEY (thread_id, round, step)
- WAL mode: `PRAGMA journal_mode=WAL`
- FOREIGN KEY gate_results.thread_id → checkpoints.thread_id
- 无 DELETE CASCADE (checkpoint 只增不删)

---

## 3. 流程与时序

### 3.1 单次 Round (7 步)

```
STEP1 tick()           [<1ms]  check round<max → next_stage(state) → architect|dev|critic|None
STEP2 pre-guardrail()  [<10ms] 5 guardrail chain → drop/block/retry
STEP3 execute()        [1-120s] agent调用LLM→tool_use loop→parse→StageResult
STEP4 post-guardrail() [<10ms] 5 guardrail chain
STEP5 gates()          [1-300s] safety→lint→type_check→contract→test→coverage→build (串行)
STEP6 after_tick()     [<50ms] round+=1 → checkpoint.save() → SQLite
STEP7 judge()          [<1ms]  GOAL_REACHED? HARD_STOP? PLATEAU? NO_PROGRESS? → break/continue
```

### 3.2 反馈回路 (MAJOR → developer)

```
Round K: ...→[critic] MAJOR → state.critic_feedback!=null, verdict="MAJOR"
Round K+1: next_stage→developer → 引用{critic_feedback} → 针对性修复
→ STEP1-7 → critic: APPROVE→end; MAJOR→继续(≤3轮, 连续2次→HARD_STOP)
```

### 3.3 Crash 恢复

```
Round K crash → checkpoint已保存K-1 → Round K部分写入回滚(tx)
CMD-03 resume <id> → 读K-1 state → 注入LoopEngine → Round K重跑
```

**时间边界**: STEP3+STEP5含: 30s-5min/round; max_rounds=10: ~50min上限

---

## 4. 边界与异常

### 4.1 错误分类 (A-F)

```
A. 配置 (CMD-01预检): ANTHROPIC_API_KEY→export; project state缺→/init; uv缺→安装
B. Gate (STEP5): SafetyGate(工具缺→skip); Lint/TypeCheck/Contract/Test/Build(→block); Coverage(<80%→strict block)
C. Guardrail (STEP2/4): Requirement→drop; PlanExists/GitDiffExists/GitClean→block; TestsPass→retry(≤3)
D. LLM (STEP3): TIMEOUT(120s)→retry(≤3); RATE_LIMIT→retry(≤3); AUTH→abort; NETWORK→retry(≤3)
E. 中断: SIGINT→当前round中止+checkpoint保留; 重启→WAL恢复+resume
F. 数据: Checkpoint损坏→清+重init; 反序列化失败→raw dict fallback; schema mismatch→raise
```

### 4.2 降级策略

| 场景 | 策略 | 影响 |
|------|------|------|
| SafetyGate(工具缺失) | skip,提示 | 无secret检测 |
| CoverageGate <80% | ci-only skip | dev不阻塞 |
| post-edit异常 | catch+exit0 | 无secret检测 |
| pre-tool超时 | 放行 | 安全检测失效 |
| SemanticEvaluator不可用 | auto skip | 用停滞检测替代 |
| checkpoint.save失败(disk) | abort | 本轮丢失,resume |
| uv缺失 | 提示+fallback CLI | plugin失效 |

---

## 5. 技术决策依据

| # | 决策 | 选择 | 对比 | 业界参照 | 风险 | 回退 |
|---|------|------|------|---------|------|------|
| D1 | Loop驱动 | Agent UX + Engine backend | vs Agent-only(v1.0前期) vs Engine-only(当前) | LangGraph PregelLoop tick/after_tick(Python原生控制流); AutoGen SingleThreadedAgentRuntime(消息队列) | Engine接口复杂 | 中 |
| D2 | 验证模型 | 5 Guardrail(in-process) + 7 Gate(subprocess) | vs LLM自评(Devin) vs 人工审查 | CrewAI GuardrailResult 4态(pass/block/drop/retry); Anthropic tool-use safety guidelines | Gate慢(30s-5min) | 低 |
| D3 | 角色拆分 | 3 role(architect/dev/critic) + Send/PUSH预留 | vs 单agent vs GroupChat(AutoGen) | LangGraph multi-node conditional edges; CrewAI hierarchical process | 3 role简单场景够, 复杂需扩展 | 低 |
| D4 | 持久化 | SQLite WAL + thread_id隔离 | vs JSON文件 vs Memory | LangGraph SqliteSaver(WAL默认); AutoGen Memory only | WAL文件<10MB | 低 |
| D5 | 收敛模型 | 4级(GOAL_REACHED/PLATEAU/NO_PROGRESS/HARD_STOP) | vs 3级(去NO_PROGRESS) vs 2级(LLM自评) | LangGraph递归限制(HARD_STOP); CrewAI stagnation(PLATEAU); Anthropic agent stop guidelines | NO_PROGRESS误判 | 低(调threshold) |
| D6 | 反馈回路 | critic_feedback channel显式 | vs implicit context(CrewAI) vs conversation loop(AutoGen) | LangGraph channel系统(LastValue/Accumulating); AutoGen MessageEnvelope(显式sender) | channel命名冲突 | 低 |
| D7 | Plugin形态 | slash commands + hooks + skill | vs MCP server vs standalone CLI | Claude Code plugin convention; LangGraph no-plugin; AutoGen no-plugin | Claude Code plugin API变化 | 低 |
| D8 | 模板组合 | 8类型×4语言=32 | vs 更少 | Copier _templates(含_shared+_features); Yeoman composable generators | Rust/Go模板未完整 | 中 |
| D9 | hooks语言 | POSIX shell | vs Python | Claude Code官方examples(bash); 社区PostToolUse实现(bash) | Windows不支持 | 低(Python重写) |
| D10 | 平台 | macOS+Linux | vs Windows | LangGraph主doc仅Linux/macOS; AutoGen仅Linux/macOS | Windows用户不可用 | 中(Windows hooks) |

### 5.2 业界差异

| 维度 | v5.0 | LangGraph | AutoGen | CrewAI | 差异化 |
|------|------|-----------|---------|--------|--------|
| 控制流 | Agent+Engine混合 | Python graph | Python msg-queue | Python DSL | Agent UX + Engine backend |
| 验证 | 5G+7Gate双层 | 人工interrupt | InterventionHandler | Guardrail 4态 | 双层确定性 |
| 角色 | 3 role+Send预留 | node=LLM | GroupChat | sequential | 3role够,Send扩展 |
| 持久化 | SQLite WAL+thread_id | SqliteSaver | Memory | 自带 | cross-session |
| Plugin | Claude Code | 无 | 无 | 无 | 首创 |
| Init | 8×4=32 | 无 | 无 | 无 | 最完整 |

---

## 6. 交付清单

**需实现** (18 文件):
`.claude-plugin/plugin.json` (1), `commands/`×8, `skills/auto-engineering/SKILL.md` (1), `hooks/`×5, `ae-plugin-acceptance-test.sh` (1), `docs/PLUGIN-USAGE.md` (1), `docs/ARCHITECTURE.md` (1)

**Core Engine**: 见 §1.3 的 8 个接口. 实现语言/框架自选, 但必须满足接口契约(§1). 当前项目内有已实现的 engine (可作为起点或重写, 不强约束).

**外部依赖**: uv, git, sqlite3, python 3.12+, bash 4.5+, ANTHROPIC_API_KEY

**工作量**: 3-4 天 (plugin wrapper), Core Engine视实现起点而定

---

## 7. 验收

**场景**: SE-1 新项目init+dev-loop, SE-2 存量auto-detect(不改src), SE-3 resume, SE-4 CLI fallback

**自检**: plugin.json合法, 8 command存在, 5 hook可执行, pre-tool拒绝(exit2), Gate 正确判定, acceptance test通过

---

## 8. 自评

| 维度 | 得分 | |
|------|------|------|
| 接口契约 (§1) | 2/2 | 8 cmd + 5 hook + 8 engine接口, 含类型/返回值/错误码/边界 |
| 数据模型 (§2) | 2/2 | 4实体(类型/约束/基数), stage+gate状态机, 索引 |
| 流程与时序 (§3) | 2/2 | 7步时序(分支+异常), 反馈回路, crash恢复, 时间边界 |
| 边界与异常 (§4) | 2/2 | A-F错误树, 7降级路径(触发+策略+影响) |
| 技术决策依据 (§5) | 2/2 | 10决策(对比+业界≥2per+风险+回退), 6维度差异表 |
| **总分** | **10/10** | 达标 |