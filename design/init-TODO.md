# init 子系统后续待办任务计划

> 创建：2026-06-24 | 来源：本会话 §1.3 接口规范 100% 落地审计
> 关联：`design/BEACON.md` 当前阶段 / `design/init-PLAN.md` 已完成 Phase 4.1-5 / `design/v1.0-INIT.md` §1.3 接口规范

---

## 背景

`init-PLAN.md` 已记录并完成 Phase 4.1-5（P0 断路修复 / P1 行为纠正 / P2 健壮性增强 / P3 大功能 / 测试补全），commit `dd3e5bf` 落地。但对照 `v1.0-INIT.md` §1.3 接口规范深入审计（§1.3.1-§1.3.10 共 10 个小节），仍发现 7 个设计-实现偏差未修复，加上验证缺口和测试覆盖缺口，形成本待办。

**唯一 P0 项**：A1 增量模式（scaffold.py + CLI 完全未实现）。

---

## Phase 1: §1.3 接口规范 100% 落地（7 gap）

- A1 增量模式完整实现（P0，~150 行，§1.3.10）— scaffold.py 新增 incremental / _created_files / _mode 字段；Phase 3.5 MERGE 逐文件合并逻辑；目标目录非空自动检测增量；跳过 .git/ 和已存在文件；cli.py 暴露 --incremental 标志
- A2 _phase_tasks 传递 current_phase 给 TaskRunner（P1，~3 行，§1.3.8）— 当前 `TaskRunner(tmpdir)` 缺第二个参数
- A3 _run_builtin_hooks 中 git commit 失败改为非阻塞（P1，~3 行，§1.3.8）— 设计允许静默，当前 raise TaskExecutionError
- A4 symlink 文件处理（P1，~8 行，§1.3.5）— `is_symlink()` → `shutil.copy2` 保留链接或复制目标
- A5 `ProjectEnvironment._warn_undetectable(root)` 方法实现（P2，~5 行，§1.3.9）— CLI 层提示不可判定项不一致
- A6 `FRAMEWORK_SIGNATURES` spec-doc 加 `design/v*.md` 通配（P2，~1 行，§1.3.7）— 当前只匹配 `design/BEACON.md`
- A7 `_from_detection` `package_manager` 默认值改 `"npm"`（P3，~1 行，§1.3.9）— 设计 `"npm"` / 实现 `""`

---

## Phase 2: 验证

- B1 端到端实跑 `ae init my-project --type app-service --defaults`（依赖：无）
- B2 8 种项目类型 E2E 验证（app-service / library / cli-tool / skill / hook / mcp-server / spec-doc / monorepo，依赖：B1）
- B3 存量项目增量模式 E2E（`ae init . --incremental`，验证只增不改语义，依赖：A1）

---

## Phase 3: 测试覆盖

- C1 补 detector / hooks / config / renderer / errors 单元测试（目标：覆盖率从 ~40% → ≥80%）
- C2 scaffold.py 端到端 E2E 测试（5 阶段流水线 + 失败清理 + 增量模式）

---

## Phase 4: 文档维护

- D1 修复 A1-A7 后同步更新 `v1.0-INIT.md` §1.8 待办状态表（触发条件：A1-A7 完成后）
- D2 更新 `BEACON.md` 当前状态（A1-A7 完成后 init 阶段 → "§1.3 100% 完成"）

---

## Phase 5: 培训材料（已完成）

- E1 `docs/参考/INIT-TRAINING.md` v1（296 行，与 TRAINING.md 同等层次）✅ 已完成（2026-06-24）

---

## 建议执行顺序

1. A1（P0，~150 行）— 唯一阻塞项，先解决
2. A2-A4（P1，~14 行）— 3 个小修改，可一次性处理
3. A5-A6（P2，~6 行）— 2 个小修改
4. A7（P3，~1 行）— 1 行修复
5. B1 → B2 串行（验证链，B1 通过后跑 8 类型）
6. B3 在 A1 完成后做
7. C1 / C2 可与 A 任务并行
8. D1 / D2 在 A 全部完成后统一更新

---

## 引用文件

- `@design/v1.0-INIT.md §1.3` — 接口规范
- `@design/v1.0-INIT.md §1.7` — 上轮偏差审计（21 项，已完成 R1-R21）
- `@design/v1.0-INIT.md §1.8` — 后续优化待办（P0-P4 四档）
- `@design/init-PLAN.md` — 已完成的 Phase 4.1-5 执行计划
- `@design/BEACON.md` — 当前阶段指针
- `@docs/参考/INIT-TRAINING.md` — v1 培训材料