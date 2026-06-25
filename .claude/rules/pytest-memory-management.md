---
name: pytest-memory-management
description: pytest 内存管理规范 — 16G 物理内存约束下的子进程资源控制
type: project
---

# pytest 内存管理规则

> 创建：2026-06-25 | 来源：@~/.claude/projects/-Users-minjianq-Documents-06-Mi-Model-Rule-Auto-engineering/memory/subprocess-memory-management.md
> 约束：本机 16G 物理内存 — pytest + coverage + fixture 容易撑爆

## 核心约束

- 物理内存上限 **16G**
- pytest + coverage instrumentation 内存叠加约 **2x**
- conftest hook 写入 `/tmp/_ae_test_failures.json` 跨 session 累积
- `.pytest_cache` 跨项目累积

## 禁止的反模式

1. 全量跑 `pytest tests/` — 加载所有 fixture，~30-60s 且内存叠加
2. `run_in_background: true` 跑 pytest — 会 hang 无人收尸
3. 并发跑多个 pytest 进程 — 内存叠加 ~200MB/进程
4. 跑完不清理 — `/tmp/_ae_test_failures.json` + `.pytest_cache` 累积
5. 不带 `--timeout` 的长跑 — hang 时无法终止

## 推荐调用方式

### 单文件测试（最高频）
```bash
.venv/bin/pytest tests/test_xxx.py -v --no-cov --timeout=60
```

### 关键字过滤
```bash
.venv/bin/pytest -k "test_execute" --no-cov --timeout=60
```

### 全量验证（开发节点，少用）
```bash
.venv/bin/pytest tests/ --no-cov --timeout=120 -q
```

### 跑覆盖率（独立 opt-in，需显式指定）
```bash
.venv/bin/pytest tests/ --cov=auto_engineering --cov-report=term-missing --timeout=120
```

## 清理协议（每次 pytest 后必做）

```bash
rm -f /tmp/_ae_test_failures.json   # conftest hook 累积
rm -rf .pytest_cache                 # 测试 cache（含 tests/.pytest_cache）
```

或统一：`make clean`（如存在 Makefile）

## 当前 pyproject.toml 配置（2026-06-25 起生效）

```toml
[tool.pytest.ini_options]
testpaths = ["tests"]
addopts = ["--timeout=60", "-p no:cacheprovider"]  # 删除了默认 --cov
```

- `--timeout=60`：单测试最多 60s，超时强制 fail（防 hang）
- `-p no:cacheprovider`：禁用 pytest cache（省内存 + 避免脏读）
- **cov 默认关闭**：跑覆盖率需显式 `--cov=auto_engineering`

## 紧急处理（已爆内存时）

```bash
# 1. 找 pytest 进程
ps aux | grep -E "pytest|python" | grep -v grep

# 2. 强杀具体 PID（不要 kill -9 全 python）
kill -9 <PID>

# 3. 清残留
rm -f /tmp/_ae_test_failures.json
rm -rf .pytest_cache tests/.pytest_cache

# 4. 验证释放
free -h
```

## 与项目规则的衔接

- `CLAUDE.md` §⚠️ 启动服务红线 — lsof 检查端口（pytest 不涉及端口，但同属资源控制）
- `engineering-practices.md` §1 测试规范 — 单测/集成/回归（覆盖**策略层**：写什么测试）
- 本规则 — **调用方式层**（怎么跑测试不爆内存）

## Why

2026-06-24 会话，用户反馈"你跑会跑爆内存，我主动杀了进程"。同时 `pyproject.toml` 默认开 `--cov` 导致每次跑都 ~2x 内存。本规则固化此教训为项目级硬约束，AI 与人类协作者均须遵守。