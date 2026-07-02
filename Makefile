# Makefile — Auto-Engineering 本地 CI
#
# 安装 (1 条命令, 不需 make install):
#   git clone git@github.com:qianminjian/Auto-engineering.git ~/.claude/plugins/auto-engineering
#   cd ~/.claude/plugins/auto-engineering && uv sync
#
# 用法:
#   make help      — 显示所有目标
#   make ci        — 完整 CI: ruff lint + pytest(覆盖率)
#   make test      — pytest + coverage
#   make lint      — ruff 检查
#   make format    — ruff 自动修复 + 格式化
#   make clean     — 清理 build 产物

.PHONY: help ci test test-fast lint lint-fix format clean

help:  ## 显示帮助
	@grep -E '^[a-zA-Z_-]+:.*?## .*$$' $(MAKEFILE_LIST) | sort | awk 'BEGIN {FS = ":.*?## "}; {printf "\033[36m%-15s\033[0m %s\n", $$1, $$2}'

ci: lint test  ## 完整 CI: lint + test

test:  ## pytest + 覆盖率(默认带 cov 报告)
	.venv/bin/pytest

test-fast:  ## pytest 不带覆盖率(快速)
	.venv/bin/pytest --no-cov

lint:  ## ruff lint 检查
	.venv/bin/ruff check .

lint-fix:  ## ruff 自动修复
	.venv/bin/ruff check --fix .

format:  ## ruff 格式化
	.venv/bin/ruff format .

clean:  ## 清理 build/cache 产物
	rm -rf .pytest_cache .ruff_cache htmlcov .coverage
	find . -type d -name __pycache__ -exec rm -rf {} + 2>/dev/null || true
