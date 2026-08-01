# Makefile — Auto-Engineering 项目级 CI (只项目内任务, 不写用户 home 目录)
#
# 用户级安装 (跨系统敏感: 写 ~/.claude/, 写用户 PATH) 用 install.sh, 见项目根目录.
# 用法:
#   make help      — 显示所有目标
#   make ci        — 完整 CI: ruff lint + pytest(覆盖率)
#   make test      — pytest + coverage
#   make lint      — ruff 检查
#   make format    — ruff 自动修复 + 格式化
#   make clean     — 清理 build 产物

.PHONY: help ci test test-fast lint lint-fix format clean check-gate audit-silent-except audit-dead-imports audit-line-count audit-test-gap

help:  ## 显示帮助
	@grep -E '^[a-zA-Z_-]+:.*?## .*$$' $(MAKEFILE_LIST) | sort | awk 'BEGIN {FS = ":.*?## "}; {printf "\033[36m%-15s\033[0m %s\n", $$1, $$2}'

ci: lint test  ## 完整 CI: lint + test

test:  ## pytest + 覆盖率(默认带 cov 报告)
	uv run pytest

test-fast:  ## pytest 不带覆盖率(快速)
	uv run pytest --no-cov

lint:  ## ruff lint 检查
	uv run ruff check .

lint-fix:  ## ruff 自动修复
	uv run ruff check --fix .

format:  ## ruff 格式化
	uv run ruff format .

clean:  ## 清理 build/cache 产物
	rm -rf .pytest_cache .ruff_cache htmlcov .coverage
	find . -type d -name __pycache__ -exec rm -rf {} + 2>/dev/null || true

# ============================================================
# 审计闸门 (v5.4 审计 r2 — 防同类问题再生)
# ============================================================

audit-silent-except:  ## 扫描静默吞异常 (裸 except Exception 无日志)
	@echo "=== 静默吞异常扫描 ==="
	@uv run python scripts/audit_static.py silent-except \
		|| { echo "❌ 发现静默吞异常" >&2; exit 1; }
	@echo "✓ 无静默吞异常"

audit-dead-imports:  ## 扫描 dead import (F401)
	@echo "=== Dead Import 扫描 ==="
	@uv run ruff check --select F401 auto_engineering/ 2>&1 \
		|| { echo "❌ 发现 dead import" >&2; exit 1; }
	@echo "✓ 无 dead import"

audit-line-count:  ## 扫描超 400 行文件
	@echo "=== 文件行数扫描 ==="
	@uv run python scripts/audit_static.py line-count \
		|| { echo "❌ 发现超 400 行文件" >&2; exit 1; }
	@echo "✓ 无新增或增长的超限文件"

audit-test-gap:  ## 扫描测试覆盖率缺口
	@echo "=== 测试缺口快速扫描 ==="
	@uv run pytest tests/ --collect-only -q >/dev/null \
		|| { echo "❌ 测试收集失败或没有可运行测试" >&2; exit 1; }
	@echo "✓ 测试可正常收集；覆盖率由 CI ≥90% 门禁判定"

check-gate: audit-silent-except audit-dead-imports audit-line-count audit-test-gap  ## 快速闸门检查 (合入前必跑)
	@echo ""
	@echo "=== check-gate: 全部通过 ==="
