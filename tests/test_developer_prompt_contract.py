"""Developer Prompt 明确区分异常类型断言与吞异常。"""

from pathlib import Path


def test_developer_prompt_requires_structured_type_error_assertions() -> None:
    prompt = Path("auto_engineering/prompts/roles/developer.md").read_text(
        encoding="utf-8"
    )

    assert "pytest.raises(TypeError)" in prompt
    assert "不得写 `except TypeError: pass`" in prompt
    assert "不检查消息文本”不等于“不检查" in prompt


def test_developer_prompt_defines_new_file_patch_contract() -> None:
    prompt = Path("auto_engineering/prompts/roles/developer.md").read_text(
        encoding="utf-8"
    )

    assert "目标文件已经存在" in prompt
    assert "*** Add File:" in prompt
    assert "*** Update File:" in prompt
    assert "不得把 JSON、自然语言" in prompt
