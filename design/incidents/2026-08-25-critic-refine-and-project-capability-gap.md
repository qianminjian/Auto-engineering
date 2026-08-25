# 2026-08-25 Critic 回源与 ProjectProfile 能力误判事故

## 结论

Voice Clone 真跑没有停在业务实现，而是暴露两条 Loop 内核缺口：Critic 的阻断 findings
在切换 Architect 时丢失；ProjectProfile 把可运行的 lint 命令和空 ESLint 配置误判为有效
静态检查能力。外部报告是证据输入，本项目不修改测试项目。

## 可复核事实

- Thread `21872757-0fc5-4bae-94c8-22f1d46fbd29` 的 `CriticStateUpdated` 保存 3 个 P1。
- 随后的 Architect Action 却携带 `source=critic, gaps=[]`。
- Architect 输出空 `plan_patch.add_batches` 后被既有 schema 正确拒绝；该拒绝不是根因。
- 初始 `package.json` 使用 `eslint: latest`；旧探测器只识别显式数字 9，漏报 flat config。
- 后续 `eslint.config.js` 为 `export default [{}]`，文件存在但没有有效规则。

## 根因与设计偏差

1. `CriticHandler` 正确写入 `open_findings` 并选择 `refine_source=critic`，但
   `build_refine_request` 只支持四个 verifier/audit 来源；状态路由与归一契约演进不同步。
2. Architect 结果校验只要求 patch 非空，没有要求 Critic finding 与修复任务建立可追踪关系。
3. ProjectProfile 用版本字符串和文件存在性代替能力语义，`latest` 与空配置落在盲区。
4. Setup 完成只重新探测声明，没有执行 Profile Gate；若改成终止性 error，又会让产品自动续作停止。
5. 报告中的 Finalizer、Action-scoped work files、恢复 `result_ref` 和 Prompt SHA 原样传递，
   当前代码已有产品路径与回归；本事故不再新增平行提交机制。

## 修复不变量

- 五类 refine 来源进入 Architect 前必须生成至少一个 gap；否则返回
  `REFINE_INPUT_EMPTY`，保持原阶段且不消耗预算。
- Critic P0/P1 逐项生成稳定 `source_ref`；Architect 必须为每项 obligation 同时绑定
  implementation 与 test/contract_test，缺失时在状态变更前拒绝。
- ESLint 9/`latest`/`next` 必须有 flat config；空数组或仅空对象配置不构成 lint 能力。
- Setup 只有在实际 Profile Gate 全部通过后才能推进；可修复失败必须生成新 CONTINUE Action，
  不得终止 Product Driver，也不得复用旧 Action identity。
- schema 对空 `plan_patch.add_batches` 的 fail-closed 行为保持不变。

## 任务与关闭标准

| ID | 任务 | 关闭标准 |
|---|---|---|
| T546 | Critic finding 无损回源与 obligation 覆盖 | 单元与轨迹测试证明 finding、位置、建议和稳定身份不丢失，缺少双目标映射被拒绝 |
| T547 | ProjectProfile lint 语义能力 | `latest` 缺配置与空 flat config 均保持 setup_required |
| T548 | 自动与真实产品复验 | 同形 3-P1→修复 Batch 轨迹及自动门禁已通过：2640 passed/1 skipped、coverage 90%、Ruff/mypy/sync、双宿主 hermetic archive smoke；仍须用新 Build 完成真实 terminal，此前不得发布 |
| T549 | Setup 实证门禁与自动续作 | 七类 Profile Gate 实际执行；失败保持 setup 并生成新 CONTINUE Action，专项回归通过 |

## 原报告七项改进闭环

| 原建议 | 当前实现证据 | 结论 |
|---|---|:---:|
| 统一 Action Result Builder | Finalizer/Assembler 独占身份、proof、attestation 与 Result 写入；Action-scoped work files | 已闭合 |
| Prompt SHA 禁止人工拼接 | Host Invocation 从 Core invocation 生成 launcher，校验 Prompt digest 与 worker receipt | 已闭合 |
| Critic 自动形成修复 Batch | 五源 RefineRequest、非空 gap 不变量、同形 3-P1→repair batch 轨迹 | 本轮闭合 |
| finding 映射实现与验证任务 | `source_ref` obligation 强制双目标且在状态变化前校验 | 本轮闭合 |
| Setup 验证 test/type/build/lint | Profile 七 Gate 实际执行，零测试、缺命令和非零退出 fail-closed | 本轮闭合 |
| MAJOR 不得被“无设计变更”覆盖 | P0/P1 结构化事实优先，空 patch 拒绝，失败发新修复 Action | 本轮闭合 |
| 终止自动生成报告 | Stop Report 从 Action、Execution Control、最近 Receipt 生成原因与下一步；禁止复制 Prompt、transcript 与业务正文 | 已闭合 |

## 原始证据

外部只读报告：`voice_clone_for_auto_CC_Design/_scratch/loop-engineering-problem-report.md`。
完整项目路径和临时 Action 文件不复制进仓库；事件与 outcome 的摘要已在本报告固化。
