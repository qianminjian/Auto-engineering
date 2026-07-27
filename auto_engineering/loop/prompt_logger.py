"""Action/prompt 调试日志写入器。"""

from __future__ import annotations

import json
import logging
from pathlib import Path

_logger = logging.getLogger(__name__)


def write_action_prompt_log(project_root: Path, action: dict) -> None:
    """将 action JSON 与人类可读 prompt 写入 `_scratch/prompt-log/`。"""

    stage = action.get("stage", action.get("action", "unknown"))
    try:
        log_dir = project_root / "_scratch" / "prompt-log"
        log_dir.mkdir(parents=True, exist_ok=True)
        tick = action.get("tick", 0)
        stem = f"tick-{tick:04d}-{stage}"
        (log_dir / f"{stem}-action.json").write_text(
            json.dumps(action, indent=2, ensure_ascii=False),
            encoding="utf-8",
        )

        instruction = action.get("instruction", "")
        subagent_prompt = action.get("subagent_prompt", "")
        expected_format = action.get("expected_format", {})
        spawn = action.get("spawn", {})
        lines = [
            f"# Tick {tick} — {stage}",
            "",
            f"- action: `{action.get('action', '?')}`",
            f"- spawn stage: {bool(spawn)}",
        ]
        if spawn:
            lines.extend([
                f"- spawn count: {spawn.get('count', 1)}",
                f"- spawn parallel: {spawn.get('parallel', False)}",
                f"- proof token: `{action.get('spawn_proof_token', 'N/A')}`",
                f"- effort: `{spawn.get('effort', 'high')}`",
            ])
        lines.extend([
            "",
            "---",
            "## Part 1 — Instruction（Team Lead 收到的命令）",
            "",
            "```",
            instruction or "(no instruction — inline stage)",
            "```",
            "",
        ])

        agents = spawn.get("agents", [])
        if agents:
            lines.extend([
                "---",
                "## Part 2a — Merge Instructions（Team Lead 合并指引）",
                "",
                "```",
                subagent_prompt.strip() or "(empty)",
                "```",
                "",
                f"## Part 2b — Agent Prompts（{len(agents)} 个 agent）",
            ])
            for agent in agents:
                prompt = agent.get("prompt", "")
                lines.extend([
                    "",
                    f"### Agent [{agent['index']}] — {len(prompt)} chars",
                    "",
                    "```markdown",
                    prompt.strip(),
                    "```",
                ])
        elif subagent_prompt:
            lines.extend([
                "---",
                "## Part 2 — Subagent Prompt",
                "",
                "```",
                subagent_prompt.strip(),
                "```",
            ])

        if expected_format:
            lines.extend([
                "",
                "---",
                "## Part 3 — Expected Format",
                "",
                "```json",
                json.dumps(expected_format, indent=2, ensure_ascii=False),
                "```",
            ])

        gate_summary = action.get("gate_summary", {})
        if gate_summary:
            lines.extend(["", "---", "## Part 4 — Gate Results", ""])
            for name, verdict in sorted(gate_summary.items()):
                if not isinstance(verdict, dict):
                    continue
                mark = (
                    "⊘ SKIPPED" if verdict.get("skipped")
                    else "✓" if verdict.get("passed")
                    else "✗"
                )
                lines.append(
                    f"- {name}: {mark} — {verdict.get('message', '')[:120]}"
                )

        (log_dir / f"{stem}-prompt.md").write_text(
            "\n".join(lines),
            encoding="utf-8",
        )
    except (OSError, UnicodeError):
        _logger.warning(
            "prompt log write failed for stage=%s",
            stage,
            exc_info=True,
        )
