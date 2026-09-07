"""Critic 原生 Worker 必须返回可解析的机器业务结果。"""

from pathlib import Path


def test_critic_prompt_requires_json_only_native_response() -> None:
    prompt = Path("auto_engineering/prompts/roles/critic.md").read_text(
        encoding="utf-8"
    )

    assert "json.loads" in prompt
    assert "禁止 Markdown、表格、代码围栏" in prompt
    assert "不要把审查" in prompt
    assert "正文写成报告后再附加 JSON" in prompt
    assert "assurance_bundle" in prompt
