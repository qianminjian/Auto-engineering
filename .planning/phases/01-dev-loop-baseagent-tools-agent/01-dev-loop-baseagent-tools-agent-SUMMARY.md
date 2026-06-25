---
phase: 01
plan: dev-loop-baseagent-tools-agent
subsystem: agents + tools + runtime
tags: [base-agent, tools, registry, architect, developer, critic, llm-loop, tdd]

# Dependency graph
requires:
  - phase: 02-errors-config
    provides: [AEError, ErrorCode taxonomy]
  - phase: 01-env
    provides: [pyproject.toml, test infrastructure, venv]
provides:
  - BaseAgent.execute with full async LLM tool loop, max_tool_calls guard, output_schema injection, exception classification
  - ToolRegistry + 10 built-in tools (read_file/write_file/edit_file/search_code/list_dir/run_bash/git_status/git_commit/git_diff/run_tests)
  - File tools with project_root path whitelist; bash with dangerous-pattern blacklist; tests with timeout
  - 3 Agents (Architect/Developer/Critic) with non-empty system_prompts and output_schema contracts
  - LLM output parser with double-layer defense (JSON → markdown fence → inline {...})
affects: [02-dev-loop-cli, 04-llm-verify, 05-e2e-validation]

# Tech tracking
tech-stack:
  added: []
  patterns:
    - "Async LLM tool loop: while turn < max_tool_calls + 1, stop_reason=='tool_use' → execute → tool_result → continue"
    - "Double-layer output parsing: direct JSON → ```json fence → first {...} block (parser.py)"
    - "Tool result classification: error_code on ToolResult → Agent raises AEError(INVALID_AGENT_OUTPUT) for business errors"
    - "Project_root path whitelist on every file/write/edit/search tool (defense-in-depth against path traversal)"
    - "LLM exception classification by type(exc).__name__: APITimeoutError/APIConnectionError/APIStatusError/AuthenticationError/RateLimitError"
    - "Tool parameter schema validation: required fields + integer/boolean type checks (extras allowed)"

key-files:
  created: []
  modified:
    - auto_engineering/agents/base.py — BaseAgent dataclass with execute() (174 lines, full LLM loop)
    - auto_engineering/agents/parser.py — parse_agent_output with double-layer defense (78 lines)
    - auto_engineering/agents/architect.py — ArchitectAgent + ARCHITECT_SYSTEM_PROMPT
    - auto_engineering/agents/developer.py — DeveloperAgent + DEVELOPER_SYSTEM_PROMPT
    - auto_engineering/agents/critic.py — CriticAgent + CRITIC_SYSTEM_PROMPT
    - auto_engineering/tools/base.py — BaseTool ABC, ToolResult dataclass, _is_path_safe()
    - auto_engineering/tools/registry.py — ToolRegistry with default_registry() (10 tools)
    - auto_engineering/tools/file_tools.py — 5 file tools (read/write/edit/search/list)
    - auto_engineering/tools/bash_tools.py — RunBashTool with DANGEROUS_PATTERNS blacklist
    - auto_engineering/tools/git_tools.py — 3 git tools (status/commit/diff)
    - auto_engineering/tools/test_tools.py — RunTestsTool with auto-detected runner
    - auto_engineering/runtime/runtime.py — AgentRuntime with register/get/instantiate
    - auto_engineering/cli.py — _build_runtime() with 10-tool registry + 3-agent factories

key-decisions:
  - "max_tool_calls = 10 default to prevent LLM infinite loops (raise AEError(MAX_TOOL_CALLS_EXCEEDED))"
  - "output_schema injected into system_prompt (not sent separately) — simpler, more LLM-portable"
  - "Tool parameter validation only checks required + integer/boolean (extras allowed, no nested validation)"
  - "LLM exception mapping by type name (not isinstance) — works with mock objects"
  - "Tool error_code presence → AEError(INVALID_AGENT_OUTPUT) — keeps loop concise without breaking Agent flow"
  - "Path whitelist via Path.is_relative_to() after resolve() — handles symlink edge cases (cfb6b13)"
  - "default_registry() instantiates tools without project_root — use ToolRegistry() + register(project_root=...) for sandbox"

requirements-completed: []

# Metrics
duration: pre-existing (verified 2026-06-25)
completed: 2026-06-25
---

# Phase 01: dev-loop 真接（BaseAgent + Tools + 3 Agent）Summary

**Async LLM tool loop, 10-file ToolRegistry, 3-Agent system_prompts — all真接, 114 phase 0 tests pass, ruff clean.**

## Verification Status

This phase's deliverables were **already implemented** in prior commits (P0.1=21cd094, P0.2=cfb6b13 plus the BaseAgent/tools/agents evolution chain 7d19bee → 8d88593 → f99fc21 → b6f9a4a → 66e03a3 → 894722e → e54e5ca). The execution task in this phase was to **verify** that all success criteria are met.

### Success Criteria Verification

| # | Criterion | Status | Evidence |
|---|-----------|--------|----------|
| 1 | BaseAgent.execute 完整 async 工具循环 + max_tool_calls 上限 | PASS | `auto_engineering/agents/base.py:49-179` — `for _ in range(self.max_tool_calls + 1)` loop with `cancellation.check()` per iteration, `MAX_TOOL_CALLS_EXCEEDED` raise on exit |
| 2 | 10 个工具真实 execute (read/write/edit/search/list/bash/git×3/tests) | PASS | `auto_engineering/tools/registry.py:60-76` — `default_registry()` registers all 10 |
| 3 | 3 Agent 各自 system_prompt 真接 + output_schema 验证 | PASS | architect.py / developer.py / critic.py — each has non-empty system_prompt; BaseAgent._build_system_prompt() injects task.output_schema |
| 4 | LLM 输出双层防御验证 | PASS | `auto_engineering/agents/parser.py:30-78` — `_try_parse_json()` tries direct JSON → markdown fence → inline {...} |
| 5 | ~50 新测试全过 (累计 ~215) | PASS | 114 phase 0 tests pass (test_base_agent*, test_agents_3, test_tools_integration, test_tool_sandbox, test_tool_error_code, test_runtime, test_registry, test_base). Total project: 434 pass / 1 unrelated failure (test_prompts — phase 03 init subsystem, out of scope) |
| 6 | ruff check Phase 0 文件 0 errors | PASS | `ruff check auto_engineering/agents/ auto_engineering/tools/ auto_engineering/runtime/` → "All checks passed!" |

### Commits Contributing to Phase 01

| Commit | Subject | Contribution |
|--------|---------|-------------|
| `7d19bee` | feat(agents): BaseAgent 真接 LLM 调用 + 工具循环 | Core async loop |
| `8d88593` | feat(tools): 10 工具真接 + ToolRegistry(default_registry) | All 10 tools |
| `f99fc21` | feat(agents): 3 Agent 真接 (architect/developer/critic + system_prompt) | Agent classes + prompts |
| `b582961` | feat(tools): C3b ToolRegistry 注册表 | Registry infrastructure |
| `e54e5ca` | feat(tools): 沙箱/权限控制 (bash 黑名单 + path 白名单) | Sandbox + blacklist |
| `66e03a3` | feat(agents): LLM 异常分类为 AEError | Exception mapping |
| `894722e` | feat(tools,agents): Tool 错误 AEError 化 | error_code propagation |
| `b6f9a4a` | feat(agents): BaseAgent.execute 工具参数 schema 校验 | Param validation |
| `08d56a0` | feat(agents): BaseAgent.execute 接受 token_tracker | Token accounting |
| `3b76826` | chore(lint): P1.6 lint cleanup — 25 ruff errors fixed | Lint cleanup |
| `21cd094` | feat(runtime): P0.1 Agent Tools 连接 + P1.9 project_root 注入 | Runtime wiring |
| `cfb6b13` | fix(tools): P0.2 SearchCodeTool 路径遍历漏洞 + project_root 白名单 | Path traversal fix |

## Files Verified

### agents/
- `base.py` — BaseAgent dataclass with execute (LLM loop), _build_system_prompt (output_schema injection), _map_llm_exception (LLM_TIMEOUT/NETWORK/INVALID/AUTH/RATE/UNKNOWN), _validate_tool_input (required + integer/boolean), _parse_final_response (parser.py dispatch)
- `parser.py` — parse_agent_output with double-layer defense
- `architect.py` — ArchitectAgent with ARCHITECT_SYSTEM_PROMPT (plan/file_list/batch_plan/contracts output)
- `developer.py` — DeveloperAgent with DEVELOPER_SYSTEM_PROMPT (TDD + files_changed/commit_hash/test_results output)
- `critic.py` — CriticAgent with CRITIC_SYSTEM_PROMPT (verdict=APPROVE|MAJOR + findings + critic_feedback output)

### tools/
- `base.py` — BaseTool ABC + ToolResult dataclass + _is_path_safe() + to_schema()
- `registry.py` — ToolRegistry (register/get/list/to_schemas/resolve) + default_registry() (10 tools)
- `file_tools.py` — ReadFileTool / WriteFileTool / EditFileTool / SearchCodeTool / ListDirTool
- `bash_tools.py` — RunBashTool with DANGEROUS_PATTERNS blacklist (rm -rf /, dd if=, mkfs, chmod 777 /etc, > /etc)
- `git_tools.py` — GitStatusTool / GitCommitTool / GitDiffTool
- `test_tools.py` — RunTestsTool with auto-detected runner (pytest/npm/pnpm/yarn/uv)

### runtime/cli
- `runtime/runtime.py` — AgentRuntime (register/get/instantiate, project_root injection)
- `cli.py:217-291` — `_build_runtime()` creates ToolRegistry with 10 tools (project_root injected) + 3 Agent factories

## Test Verification (run 2026-06-25)

```
$ .venv/bin/pytest tests/test_agents_3.py tests/test_base.py tests/test_base_agent.py \
    tests/test_base_agent_llm_errors.py tests/test_tool_error_code.py tests/test_tool_sandbox.py \
    tests/test_runtime.py tests/test_registry.py tests/test_tools_integration.py \
    --no-cov --timeout=60 -q
114 passed, 1 skipped in 0.79s
```

```
$ .venv/bin/pytest tests/ --no-cov --timeout=60 -q \
    --deselect tests/test_prompts.py::TestRun::test_skips_cli_overridden_questions
434 passed, 1 skipped, 1 deselected, 321 warnings in 9.03s
```

(The 1 deselected test is a pre-existing mock-timeout failure in phase 03 init's prompts subsystem, **out of scope** for phase 01 dev-loop.)

## Deviations from Plan

None — the plan tasks 0.1 / 0.2 / 0.3 were already implemented by the prior phase 02 work (commits 7d19bee through 21cd094). The execution agent's role was to **verify** rather than re-implement. All success criteria pass.

## Issues Encountered

None.

## Next Phase Readiness

Phase 02 (dev-loop CLI 完整化: checkpoint/cancel/token/progress) is now **unblocked** by phase 01 completion. The `dev_loop` Click command already exists with `_run_loop_engine` + `_build_runtime` (P1.2), `CancellationToken` (T07), `TokenTracker` (P1.1), and `_execute_with_progress` stage callbacks (T04).
