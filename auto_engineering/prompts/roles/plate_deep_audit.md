---
role: plate_deep_audit
fragments: [severity_rubric, letter_vs_spirit]
---
think hard

对当前板块执行深度审计。你分三步：先用 bash 快速扫描基本面 → 再并行 spawn 3 个 Agent 做深度分析 → 最后汇总去重。

## Phase 1 — 快速扫描（你自己执行 bash，不用 spawn）

### 1.1 板块探测
```bash
echo "=== 板块 ==="
echo "Components: $(ls <组件文件> | wc -l)"
echo "Language: $(ls *.py 2>/dev/null && echo Python || ls *.ts 2>/dev/null && echo TypeScript || ls *.go 2>/dev/null && echo Go || echo Unknown)"
```

### 1.2 通用反模式（根据语言选择对应命令）
```bash
# === 静默吞异常/空 catch ===
# Python
grep -rn "except\b" <组件文件> | grep -v "logger\|logging\|exc_info\|# noqa\|raise" | head -20 || true
# TypeScript
grep -rn "catch\b" <组件文件> | grep -v "console\.\|logger\." | head -20 || true

# === TODO/FIXME/HACK ===
grep -rn "TODO\|FIXME\|HACK\|XXX" <组件文件> | head -20 || echo "PASS"

# === 注释掉的代码 ===
grep -rn "^[[:space:]]*//.*\(function\|def \|class \|const \|let \)" <组件文件> | head -10 || true
grep -rn "^[[:space:]]*#.*\(def \|class \)" <组件文件> | head -10 || true

# === 硬编码密钥/密码 ===
grep -rn "api_key\|API_KEY\|password\|PASSWORD\|token\|TOKEN\|secret\|SECRET" <组件文件> | grep "= *[\"'][a-zA-Z0-9_-]\{16,\}" | grep -v "example\|test\|mock\|TODO\|\.example\|\.test\." | head -10 || echo "PASS"

# === 大文件 (>300 行) ===
wc -l <组件文件> | awk '$1 > 300 {print $0}' | sort -rn | head -10
```

### 1.3 语言特定 linter（如可用）
```bash
# Python: ruff check --select F401,F811,F821 .
# TypeScript: npx eslint --rule 'no-unused-vars: error' .
(run only if linter is installed, skip with "no linter available" if not)
```

### 1.4 测试覆盖率缺口
```bash
for f in <组件源文件>; do
  dir=$(dirname "$f"); name=$(basename "$f" | sed 's/\.[^.]*$//')
  [ ! -f "tests/test_${name}.*" ] && [ ! -f "${dir}/test_${name}.*" ] && echo "  ✗ $f → 无对应测试"
done | head -20
```

## Phase 2 — 并行 spawn 3 个 Agent

**在一个消息中发 3 个 Agent tool call 并行运行。**

---

**Agent 1: 跨组件契约 + 数据流**

```
think hard

审计板块内跨组件接口契约和数据流。

## 检查清单
- [ ] 列出板块内所有跨组件 import 关系（grep ^import/^from）
- [ ] 逐对检查 A→B：参数类型匹配？返回值被正确消费？可选参数一致？
- [ ] 追踪数据生产点 → 传递链(onChange/callback/setState) → 消费点
- [ ] 逐字段对比生产端输出 vs 消费端输入
- [ ] 检查错误传播: 子组件异常 → 父组件？try-catch 吞噬？
- [ ] 语言特定: Python grep `\.\w+(` 找被调签名；TS grep `<ComponentName` 找 Props；Go grep 接收者方法签名

对每条 diverged 记录 caller_file:line + callee_file:line + evidence + impact (WILL BREAK / LIKELY AFFECTED)。

## 输出
## 契约 + 数据流审计 — <板块名>
### P0 (阻断)
| # | 调用关系 | 状态 | caller:line | callee:line | 证据 | 影响 |
### P1 (应修复)
### P2 (建议)
### PASS
- 逐项列出所有通过的检查
```

---

**Agent 2: 架构退化**

```
think hard

检测板块内架构退化。

## 检查清单
- [ ] 逐文件 grep import → 画文本依赖图 → 标注方向
- [ ] 标记所有反向依赖（组件层 import 了不应引用的底层）
- [ ] 对每对组件 A、B：双向 grep → 双向命中 = 循环依赖
- [ ] grep fetch/axios/http → UI 组件自己调了 API？（职责越界）
- [ ] grep localStorage/sessionStorage/Cookie → 数据持久化在非数据层？
- [ ] 每个组件列出"做了但设计没声明的事"
- [ ] 语言特定: Python grep `from module import _internal`；TS grep `import { InternalType }`；Go grep 跨包 unexported 引用

## 输出
## 架构审计 — <板块名>
### 依赖图
A → B → C
### P0 (阻断)
| # | 类型 | 问题 | file:line | 依赖链 | 修复建议 |
### P1/P2
### PASS
```

---

**Agent 3: 代码质量 + 虚化度**

```
think hard

审计板块内代码质量和虚化度。

## 检查清单
- [ ] grep except/catch → 空 catch 吞噬错误？有注释说明原因？
- [ ] 边界条件: null/undefined/空数组/0 是否处理？
- [ ] grep 资源创建(new/connect/open) → 对应 close/disconnect？
- [ ] 异步三态(loading/success/error)完整？
- [ ] grep 导出符号 → 搜调用方 → 零调用 = 虚化（P1: 导出函数零调用, P2: 内部函数零调用）
- [ ] grep interface/type/Protocol → 搜 implements/使用 → 从未使用 = P1
- [ ] grep 配置文件字段 → 搜代码消费 → 无消费 = P2
- [ ] 语言特定: Python grep `^def [^_]`；TS grep `^export`；Go grep `^func [A-Z]`

## 输出
## 代码质量 + 虚化度审计 — <板块名>
### P0 (阻断)
| # | 问题 | file:line | 证据 | 修复建议 |
### P1/P2
### 虚化清单
| 符号 | file:line | 类型(导出/接口/配置) | 为什么虚化 |
### PASS
```

---

## Phase 3 — 汇总报告

1. 收集 Phase 1 扫描结果 + 3 个 Agent 输出
2. **合并去重**: key=(file, line, description[:40]), 同一 key 保留最高 severity + 合并 agent_source
3. **重新统计** p0/p1/p2 count（不信任 agent 自报）
4. 判定: 0 P0 + 0 P1 → 通过 → system_verifier。有 P0/P1 → Architect(plan_refine)
5. 输出 result JSON

{
  "stage": "plate_deep_audit",
  "plate": "<板块名>",
  "findings": [
    {"severity":"P0|P1|P2","dimension":"contract|architecture|code-quality|virtualization",
     "agent_source":"phase1|agent1|agent2|agent3","file":"...","line":0,
     "description":"...","suggested_fix":"..."}
  ],
  "p0_count": 0, "p1_count": 0, "p2_count": 0,
  "cross_component_issues": [],
  "total_audited_files": 0
}
