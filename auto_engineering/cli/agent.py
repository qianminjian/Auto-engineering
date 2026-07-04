"""CLI agent 命令 — 单 Agent 调用, 输出 TaskOutcome JSON (v5.0 §PE.6).

用法:
    ae agent architect "分析需求并出 plan"
    ae agent developer "实现 foo 函数"
    ae agent critic "评估本轮产出"

输出 (单行 JSON):
    {
      "task_id": "agent-<uuid>",
      "role": "architect",
      "status": "completed" | "failed",
      "output": "...",
      "error": null,
      "duration": 0.42,
      "task_role": "architect"
    }

Exit codes:
    0 = 成功
    1 = 调用失败 (Agent 异常)
"""

from __future__ import annotations

import asyncio
import json
import os
import time
import uuid
from pathlib import Path

import click


VALID_ROLES = ("architect", "developer", "critic")


def _build_role_system_prompt(role: str) -> str:
    """获取 role 对应 system prompt (从 agents/prompts.py)."""
    try:
        from auto_engineering.agents.prompts import (
            ARCHITECT_SYSTEM_PROMPT,
            CRITIC_SYSTEM_PROMPT,
            DEVELOPER_SYSTEM_PROMPT,
        )

        if role == "architect":
            return ARCHITECT_SYSTEM_PROMPT
        if role == "developer":
            return DEVELOPER_SYSTEM_PROMPT
        if role == "critic":
            return CRITIC_SYSTEM_PROMPT
    except ImportError:
        pass
    return f"You are a {role} agent. Process the user request and produce a structured response."


def _build_runtime_for_role(role: str, project_root: Path) -> object:
    """构造单 Agent 用的最小 runtime (含 6 个常用工具)."""
    from auto_engineering.agents.base import Agent
    from auto_engineering.llm.anthropic_provider import AnthropicProvider
    from auto_engineering.runtime.runtime import AgentRuntime
    from auto_engineering.tools.bash_tools import RunBashTool
    from auto_engineering.tools.file_tools import (
        EditFileTool,
        ListDirTool,
        ReadFileTool,
        SearchCodeTool,
        WriteFileTool,
    )
    from auto_engineering.tools.git_tools import GitStatusTool

    llm = AnthropicProvider()  # SDK 自动从 ANTHROPIC_API_KEY / ANTHROPIC_AUTH_TOKEN 读
    tools = [
        WriteFileTool(project_root=project_root),
        EditFileTool(project_root=project_root),
        SearchCodeTool(project_root=project_root),
        ReadFileTool(project_root=project_root),
        ListDirTool(),
        RunBashTool(),
        GitStatusTool(),
    ]
    runtime = AgentRuntime()
    runtime.register(
        role,
        lambda: Agent(
            llm=llm,
            role=role,
            system_prompt=_build_role_system_prompt(role),
            tools=tools,
        ),
    )
    return runtime


def run_agent(role: str, instruction: str, project_root: Path) -> dict:
    """单 Agent 调用入口.

    Returns:
        dict 形式承载 TaskOutcome 字段: task_id/role/status/output/error/duration/task_role.

    2026-07-04 修复 (Issue #8, 90 分): 失败 error message 已含
    ANTHROPIC_API_KEY/ANTHROPIC_AUTH_TOKEN (plugin mode OAuth 注入),
    不再仅 ANTHROPIC_API_KEY.
    """
    task_id = f"agent-{uuid.uuid4().hex[:8]}"
    started = time.monotonic()
    # 无 LLM key → 返回失败结果
    # 2026-07-04 修复 (prismscan 真实 bug): 4 级 fallback plugin_mode 检测
    # (CLAUDE_CODE / CLAUDE_CODE_ENTRYPOINT / ANTHROPIC_CLI / ANTHROPIC_AUTH_TOKEN)
    # 2026-07-04 修复 (v5.0 深度审计 + Bug 4 prismscan 集成):
    # - 原 if False bug 已修
    # - in_llm_agent 用 detect_plugin_mode() 共用函数 (Bug 4)
    from auto_engineering.utils.plugin_mode import detect_plugin_mode, has_llm_credentials
    in_llm_agent = detect_plugin_mode()
    if not has_llm_credentials() and not in_llm_agent:
        return {
            "task_id": task_id,
            "role": role,
            "status": "failed",
            "output": None,
            "error": "ANTHROPIC_API_KEY/ANTHROPIC_AUTH_TOKEN 未设置 (Plugin mode 应零配置, Claude Code OAuth 自动注入 ANTHROPIC_AUTH_TOKEN)",
            "error": "ANTHROPIC_API_KEY/ANTHROPIC_AUTH_TOKEN 未设置 (Claude Code Plugin 模式应通过 ANTHROPIC_AUTH_TOKEN/OAuth 透传; CLI 调试模式需手动 export)",
            "duration": time.monotonic() - started,
            "task_role": role,
        }
    # 真实调用
    try:
        runtime = _build_runtime_for_role(role, project_root)
        agent = runtime.get(role)

        async def _exec():
            # 用 .execute 走真实 LLM 路径; mock-friendly: 无 api_key 时仍构造
            try:
                return await agent.execute(
                    task={"id": task_id, "title": instruction[:50], "description": instruction},
                    ctx=None,
                )
            except TypeError:
                # 兼容旧接口
                return agent.execute(instruction)

        result = asyncio.run(_exec())
        duration = time.monotonic() - started
        # 兼容 Agent.execute 返回 dict / TaskOutcome
        if isinstance(result, dict):
            output = result.get("output", result)
            err = result.get("error")
            status = "completed" if not err else "failed"
        else:
            output = getattr(result, "output", str(result))
            err = getattr(result, "error", None)
            status = getattr(result, "status", "completed")
        return {
            "task_id": task_id,
            "role": role,
            "status": status,
            "output": output,
            "error": err,
            "duration": duration,
            "task_role": role,
        }
    except Exception as e:  # noqa: BLE001
        return {
            "task_id": task_id,
            "role": role,
            "status": "failed",
            "output": None,
            "error": f"{type(e).__name__}: {e}",
            "duration": time.monotonic() - started,
            "task_role": role,
        }


def register_agent_command(main: click.Group) -> None:
    """向 main Click Group 注册 ae agent 子命令."""

    @main.command()
    @click.argument("role", type=click.Choice(VALID_ROLES))
    @click.argument("instruction")
    @click.option(
        "--project-root",
        type=click.Path(exists=True),
        default=None,
        help="项目根目录 (默认 cwd)",
    )
    def agent(role: str, instruction: str, project_root: str) -> None:
        """单 Agent 调用 (architect/developer/critic), 输出 TaskOutcome JSON."""
        root = Path(project_root).resolve() if project_root else Path.cwd()
        result = run_agent(role, instruction, root)
        click.echo(json.dumps(result, ensure_ascii=False, indent=2))
        if result["status"] != "completed":
            raise SystemExit(1)
