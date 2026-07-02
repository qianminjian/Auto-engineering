# Makefile — Auto-Engineering 本地 CI
#
# 安装:
#   git clone git@github.com:qianminjian/Auto-engineering.git ~/.auto-engineering
#   cd ~/.auto-engineering && make install
#
# 用法:
#   make help      — 显示所有目标
#   make ci        — 完整 CI: ruff lint + pytest(覆盖率)
#   make test      — pytest + coverage
#   make lint      — ruff 检查
#   make format    — ruff 自动修复 + 格式化
#   make install   — 用户级全局安装 (uv sync + plugin 注册 + ae doctor 验证)
#   make clean     — 清理 build 产物

.PHONY: help ci test test-fast lint lint-fix format install clean

help:  ## 显示帮助
	@grep -E '^[a-zA-Z_-]+:.*?## .*$$' $(MAKEFILE_LIST) | sort | awk 'BEGIN {FS = ":.*?## "}; {printf "\033[36m%-15s\033[0m %s\n", $$1, $$2}'

install:  ## 用户级全局安装 (uv sync + Claude Code plugin 注册 + 验证)
	@echo "=== Auto-Engineering v5.0 用户级安装 ==="
	@echo ""
	@echo "[1/3] uv sync..."
	uv sync
	@echo ""
	@echo "[2/3] 注册 plugin (用户级, 所有 Claude Code 项目可用)..."
	mkdir -p ~/.claude/plugins
	ln -sfn $(PWD) ~/.claude/plugins/auto-engineering
	@echo "  ~/.claude/plugins/auto-engineering -> $(PWD)"
	@echo ""
	@echo "[3/3] ae doctor 验证..."
	uv run ae doctor
	@echo ""
	@echo "安装完成。重启 Claude Code 后所有项目可用:"
	@echo "  /dev-loop /status /checkpoint /project-tdd /project-worktree /project-agent /project-ci"

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
