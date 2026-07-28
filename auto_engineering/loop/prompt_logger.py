"""Action/prompt 调试日志写入器。"""

from __future__ import annotations

import hashlib
import json
import logging
import re
from pathlib import Path

_logger = logging.getLogger(__name__)


def _safe_segment(value: object, fallback: str) -> str:
    text = str(value or fallback)
    return re.sub(r"[^A-Za-z0-9_.-]+", "-", text)[:80]


def _unique_stem(log_dir: Path, stem: str) -> str:
    candidate = stem
    suffix = 2
    while (
        (log_dir / f"{candidate}.json").exists()
        or (log_dir / f"{candidate}.md").exists()
    ):
        candidate = f"{stem}-{suffix}"
        suffix += 1
    return candidate


def write_action_prompt_log(project_root: Path, action: dict) -> None:
    """记录内核渲染的 Action/Prompt；该日志不代表宿主已经投递。"""

    stage = action.get("stage", action.get("action", "unknown"))
    try:
        log_dir = project_root / "_scratch" / "prompt-log"
        log_dir.mkdir(parents=True, exist_ok=True)
        tick = action.get("tick", 0)
        action_json = json.dumps(
            action, indent=2, ensure_ascii=False, sort_keys=True
        )
        action_hash = hashlib.sha256(
            action_json.encode("utf-8")
        ).hexdigest()[:12]
        base_stem = (
            f"{_safe_segment(action.get('thread_id'), 'no-thread')}-"
            f"tick-{tick:04d}-{_safe_segment(stage, 'unknown')}-"
            f"{_safe_segment(action.get('message_id'), 'no-message')}-"
            f"rendered-{action_hash}"
        )
        stem = _unique_stem(log_dir, base_stem)
        (log_dir / f"{stem}.json").write_text(
            action_json,
            encoding="utf-8",
        )

        instruction = action.get("instruction", "")
        subagent_prompt = action.get("subagent_prompt", "")
        expected_format = action.get("expected_format", {})
        spawn = action.get("spawn", {})
        lines = [
            f"# 内核渲染提示词 — Tick {tick} — {stage}",
            "",
            "> 这是 Core 生成的 rendered 诊断记录，未证明宿主已投递或 LLM 已接收。",
            "",
            f"- action: `{action.get('action', '?')}`",
            f"- message id: `{action.get('message_id', 'N/A')}`",
            f"- rendered hash: `{action_hash}`",
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
                    (
                        f"### Agent [{agent['index']}]"
                        f" — role `{agent.get('role', 'unspecified')}`"
                        f" — hash `{agent.get('prompt_hash', 'N/A')}`"
                        f" — {len(prompt)} chars"
                    ),
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

        (log_dir / f"{stem}.md").write_text(
            "\n".join(lines),
            encoding="utf-8",
        )
    except (OSError, UnicodeError):
        _logger.warning(
            "prompt log write failed for stage=%s",
            stage,
            exc_info=True,
        )
