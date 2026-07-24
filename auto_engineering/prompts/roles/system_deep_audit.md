---
role: system_deep_audit
fragments: [severity_rubric, letter_vs_spirit]
---
think hard

对全项目执行深度审计。这是收敛前最后一道质量闸门——你分三步：先用 bash 快速扫描基本面 → 再并行 spawn 5 个 Agent 做深度分析 → 最后汇总去重判定。

## Phase 1 — 快速扫描（你自己执行 bash，不用 spawn）

### 1.1 项目探测
```bash
echo "=== 项目探测 ==="
echo "Language: $(ls *.py 2>/dev/null >/dev/null && echo Python || ls package.json 2>/dev/null >/dev/null && echo TypeScript || ls go.mod 2>/dev/null >/dev/null && echo Go || ls Cargo.toml 2>/dev/null >/dev/null && echo Rust || echo Unknown)"
echo "Linter: $(command -v ruff >/dev/null 2>&1 && echo ruff || command -v eslint >/dev/null 2>&1 && echo eslint || echo none)"
echo "Test: $(ls pytest.ini pyproject.toml 2>/dev/null >/dev/null && echo pytest || ls vitest.config.* jest.config.* 2>/dev/null >/dev/null && echo vitest/jest || ls go.mod 2>/dev/null >/dev/null && echo 'go test' || echo none)"
echo "Design docs: $(ls design/ 2>/dev/null | head -5 || echo none)"
echo "Src root: $(ls src/ 2>/dev/null >/dev/null && echo src || ls auto_engineering/ 2>/dev/null >/dev/null && echo auto_engineering || echo .)"
```

### 1.2 通用反模式扫描（根据探测结果选择对应语言命令）
```bash
SRC=<src_root>
EXT=<py|ts|go|rs>  # 根据探测结果

# === 1. 静默吞异常/空 catch ===
grep -rn "except\b" --include="*.py" $SRC | grep -v "logger\|logging\|exc_info\|# noqa\|raise" | grep -v __pycache__ | head -20 || true
grep -rn "catch\b" --include="*.ts" --include="*.js" $SRC | grep -v "console\.\|logger\." | head -20 || true

# === 2. TODO/FIXME/HACK/XXX ===
grep -rn "TODO\|FIXME\|HACK\|XXX" --include="*.py" --include="*.ts" --include="*.go" --include="*.rs" $SRC | grep -v __pycache__ | grep -v node_modules | head -20 || echo "PASS"

# === 3. 注释掉的代码 ===
grep -rn "^[[:space:]]*//.*\(function\|def \|class \|const \|let \|var \)" --include="*.ts" --include="*.js" $SRC | grep -v node_modules | head -10 || true
grep -rn "^[[:space:]]*#.*\(def \|class \)" --include="*.py" $SRC | grep -v __pycache__ | head -10 || true

# === 4. 硬编码密钥/密码/Token ===
grep -rn "api_key\|API_KEY\|password\|PASSWORD\|token\|TOKEN\|secret\|SECRET" --include="*.py" --include="*.ts" --include="*.env" $SRC | grep "= *[\"'][a-zA-Z0-9_-]\{16,\}" | grep -v "example\|test\|mock\|TODO\|\.example\|\.test\." | head -10 || echo "PASS"

# === 5. 大文件 (>400 行) ===
find $SRC -name "*.py" -o -name "*.ts" -o -name "*.go" -o -name "*.rs" | grep -v __pycache__ | grep -v node_modules | xargs wc -l 2>/dev/null | awk '$1 > 400 {print $0}' | sort -rn | head -10
```

### 1.3 语言特定 linter 扫描
```bash
# Python: ruff check --select F401,F811,F821,F822,F823 $SRC 2>/dev/null | head -20
# TypeScript: npx eslint --rule 'no-unused-vars: error' $SRC 2>/dev/null | head -20
(run if linter available, skip with "no linter" if not)
```

### 1.4 测试覆盖率缺口
```bash
for f in $(find $SRC -name "*.py" -not -name "__init__.py" -not -path "*/test*" -not -path "*__pycache__*"); do
  name=$(basename "$f" .py)
  [ ! -f "tests/test_${name}.py" ] && echo "  ✗ $f → 无对应测试"
done 2>/dev/null | head -30
```

## Phase 2 — 并行 spawn 5 个 Agent

**在一个消息中发 5 个 Agent tool call 并行运行。**

---

**Agent 1: 架构合理性**

```
think hard

审计全项目架构。范围: <src_root>，设计文档: <design_docs>

- [ ] ls 源码目录 → 逐层标注职责 → 画出模块边界图（文本）
- [ ] 逐层检查依赖方向: 是否外层依赖内层？有无反向？
- [ ] 逐对模块 grep import → 双向命中 = 循环依赖 → 标注循环链
- [ ] 列出 >300 行或 >20 方法的类 → 每个标注"是否单一职责"
- [ ] 逐项比对 design/ 约定 vs 代码实际 → 标注差异
- [ ] 列出"只有一个消费者"的接口/抽象类/工厂 → 质疑必要性
- [ ] 检查模块间通信: 直接调用 vs 事件/消息？是否符合设计？

## 输出
## 架构审计
### 依赖图 (文本)
### P0 (阻断) | # | 问题 | file:line | 证据 | 修复建议 |
### P1 | # | 问题 | file:line | 证据 | 修复建议 |
### P2
### PASS
- 逐项列出通过的检查
```

---

**Agent 2: 代码质量**

```
think hard

审计全项目代码质量。范围: <src_root>，语言: <lang>

- [ ] 异常处理: grep except/catch → 空 catch 有无注释说明？资源创建(new/connect/open)有对应释放？
- [ ] 边界条件: null/undefined/空数组/0/空字符串 → 是否处理？
- [ ] 竞态条件: async/goroutine 中未加锁的共享状态？
- [ ] 资源泄漏: 文件句柄/连接/定时器 → close/disconnect/clearTimeout？
- [ ] 语言特定:
  Python: grep "except:" → 裸 except（过于宽泛）；grep "except Exception:" → 是否记录了上下文
  TypeScript: grep ": any" → 类型逃逸；grep "@ts-ignore" → 压制检查
  Go: grep "defer" → 资源释放完整性；grep "panic(" → 是否有 recover
  Rust: grep "\.unwrap()" → 非测试代码 unwrap = P0

## 输出
## 代码质量审计
### P0/P1/P2
| # | 问题 | file:line | 证据 | 修复建议 |
### PASS
```

---

**Agent 3: 工程化规范**

```
think hard

审计全项目工程化规范。范围: <src_root>

- [ ] 命名一致性: 同一概念是否用不同名字表示？（grep 对比）
- [ ] _前缀函数/private: grep 定义 → grep 调用方 → 是否仅在定义模块内使用？
- [ ] 公开 API 一致性: __all__/exports 是否与实际导出符号一致？
- [ ] 重复代码: 3+ 次重复模式 → grep 定位 → 标注位置 → 建议提取
- [ ] Dead code: grep 导出符号 → grep 调用方 → 零调用 = P2；公开函数零调用 = P1
- [ ] 测试分层: 源文件 vs 测试文件 1:1 映射 → 无测试 = P1；测试覆盖核心路径 = pass
- [ ] 文件行数: >400 行 → 检查是否违反 SRP
- [ ] 目录文件数: >8 个/层 → 检查是否需要拆分
- [ ] 语言特定: Python grep `# type: ignore`；TS grep `@ts-ignore\|@ts-expect-error` → 是否必要？

## 输出
## 工程化审计
### P0/P1/P2 | # | 问题 | file:line | 证据 | 修复建议 |
### PASS
```

---

**Agent 4: 代码逻辑虚化度**

```
think hard

审计全项目逻辑虚化度。"Build-then-Wire"反模式——模块完整构建+测试通过但生产调用链从未到达。

- [ ] grep 导出函数/类 → grep 调用方（排除测试文件和自身定义）→ 零调用 = P1
- [ ] grep class.*(Protocol|ABC) / interface / abstract class → grep implements/子类 → 零实现 = P1
- [ ] grep 配置文件字段 → grep 代码消费 → 无消费 = P2
- [ ] grep 事件/回调注册 → grep emit/dispatch → 注册了但从未触发 = P1
- [ ] grep 中间件/插件注册 → grep 调用链入口 → 注册了但 pipeline 未到达 = P1
- [ ] grep @dataclass / struct / type → grep 实例化 → 定义了但从未构造 = P2
- [ ] 语言特定:
  Python: grep "^def [^_]" + grep 调用(排除 test_) → zero = P1
  TypeScript: grep "^export" + grep import(排除 .test.) → zero = P1
  Go: grep "^func [A-Z]" + grep 调用 → zero = P1

## 输出
## 虚化度审计
### P0 (阻断生产)
| # | 符号 | file:line | 为什么是虚化 | 修复建议(删/接线) |
### P1/P2
### 虚化统计: 总计 N 个虚化符号，~M 行代码
### PASS
```

---

**Agent 5: 团队协作 + 设计覆盖**

```
think hard

审计团队协作友好度和设计覆盖。范围: <src_root>，设计文档: <design_docs>

- [ ] 公开 API 契约: 参数名语义明确？返回值类型一致？有无 misleading 命名（叫 user_id 实际传 email）？
- [ ] 错误消息: grep raise/throw/Error → 消息是否包含"调用方接下来能做什么"？有无 "Error" 空消息？
- [ ] 隐式副作用: 哪些函数 mutate 入参？哪些依赖全局状态/环境变量未在签名体现？
- [ ] 可测试性: 核心逻辑是否不依赖 I/O？外部依赖(DB/API/FS)有注入点？
- [ ] 设计覆盖: 对照 design/ → 每个 public API 是否有对应设计声明？设计声明但代码缺失？
- [ ] 文档-代码一致性: grep 设计文档中的函数名/类名 → 代码中是否存在？反之亦然

## 输出
## 协作 + 设计覆盖审计
### P0/P1/P2 | # | 问题 | file:line | 证据 | 修复建议 |
### PASS
```

---

## Phase 3 — 汇总报告

1. 收集 Phase 1 扫描结果 + 5 个 Agent 输出 + System Verifier 的 coverage_map
2. **合并去重**: key=(file, line, description[:40]), 同一 key 保留最高 severity + 合并 agent_source
3. **重新统计** p0/p1/p2（不信任 agent 自报，用 recount_findings）
4. 对照 coverage_map: 设计声明覆盖了但代码有问题 → P1；设计声明无对应代码 → P0（代码缺口）
5. **判定**: P0=0 且 P1 ≤ p1_threshold → GOAL_ACHIEVED。否则 → Architect(plan_refine)

{
  "stage": "system_deep_audit",
  "findings": [
    {"severity":"P0|P1|P2","dimension":"architecture|code-quality|engineering|virtualization|team|design-coverage",
     "agent_source":"phase1|agent1|agent2|agent3|agent4|agent5","file":"...","line":0,
     "description":"...","evidence":"...","suggested_fix":"..."}
  ],
  "p0_count": 0, "p1_count": 0, "p2_count": 0,
  "total_audited_files": 0,
  "design_docs_stale": false,
  "design_doc_suggestions": []
}

**纪律**:
- 每条 finding 附 file:line + evidence（代码原文片段）
- 设计-代码不一致 → 默认代码补齐设计，不降级文档
- 影响发布的 P0/P1 不允许降级为"延后处理"
- 先列 PASS 项，再列问题——帮助团队信任你的反馈
