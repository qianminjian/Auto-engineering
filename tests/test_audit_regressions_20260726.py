"""2026-07-26 独立审计 + Phase 47 修复的回归测试集."""

from __future__ import annotations


def test_parse_summary_response_continuation_lines() -> None:
    """回归: 非前缀行应续接到上一条 DECISION/ISSUE 之后.

    历史 bug (2026-07-26 T118 mypy 揭示): 原代码 decisions[-1]["raw"] 对
    list[str] 元素做 dict 索引 → 必抛 TypeError 被 except 静默吞噬,
    T54 SessionSummarizer 的多行 decision 续接逻辑从未生效。
    """
    from auto_engineering.context.summarization import _parse_summary_response

    # DECISION 续接: 非前缀行归属上一条 DECISION
    text_decision = (
        "DECISION: 金额计算使用 Decimal\n"
        "避免浮点精度误差\n"
    )
    decisions, files, majors, issues = _parse_summary_response(text_decision)
    assert decisions == ["金额计算使用 Decimal 避免浮点精度误差"], (
        f"DECISION 续接失效 (T118 回归): {decisions}"
    )
    assert issues == []

    # ISSUE 续接 (无 DECISION 时): 非前缀行归属上一条 ISSUE
    text_issue = (
        "ISSUE: 批量插入需性能评估\n"
        "建议增加 profiling 机制\n"
    )
    decisions2, _, _, issues2 = _parse_summary_response(text_issue)
    assert decisions2 == []
    assert issues2 == ["批量插入需性能评估 建议增加 profiling 机制"], (
        f"ISSUE 续接失效 (T118 回归): {issues2}"
    )
    assert files == {}
    assert majors == []
