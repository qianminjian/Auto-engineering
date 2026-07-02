# Makefile — Auto-Engineering 本地 CI
#
# 安装 (3 步):
#   git clone git@github.com:qianminjian/Auto-engineering.git ~/.claude/plugins/auto-engineering
#   cd ~/.claude/plugins/auto-engineering
#   make install    # uv tool install 全局, ae 命令可用
#
# 升级: cd ~/.claude/plugins/auto-engineering && make update
#
# 用法:
#   make help      — 显示所有目标
#   make install   — uv tool install (全局 ae 命令)
#   make update     — uv sync + 重新 uv tool install
#   make ci        — 完整 CI: ruff lint + pytest(覆盖率)
#   make test      — pytest + coverage
#   make lint      — ruff 检查
#   make format    — ruff 自动修复 + 格式化
#   make clean     — 清理 build 产物

.PHONY: help install update ci test test-fast lint lint-fix format clean

help:  ## 显示帮助
	@grep -E '^[a-zA-Z_-]+:.*?## .*$$' $(MAKEFILE_LIST) | sort | awk 'BEGIN {FS = ":.*?## "}; {printf "\033[36m%-15s\033[0m %s\n", $$1, $$2}'

install:  ## uv tool install 全局 (ae 命令在 PATH 可用)
	@echo "=== uv tool install . ==="
	uv tool install .
	@echo ""
	@echo "=== 验证 ==="
	which ae
	ae doctor
	@echo ""
	@echo "安装完成. 重启 Claude Code, 所有项目可用:"
	@echo "  /dev-loop /status /checkpoint /project-tdd /project-worktree /project-agent /project-ci"

update:  ## 升级: uv sync + uv tool install --force
	uv sync
	uv tool install --force .

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
