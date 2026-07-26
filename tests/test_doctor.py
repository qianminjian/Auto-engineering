"""doctor CLI 回归测试 (P1-5 重复输出 bug, 2026-07-25 独立审计)."""

from __future__ import annotations


class TestRenderOptionalFeaturesNoDuplicate:
    """P1-5: render_optional_features 不应输出重复的特性/板块行."""

    def test_no_duplicate_lines_when_metrics_active(
        self, monkeypatch, tmp_path
    ) -> None:
        """AE_METRICS 激活时特性列表 + 贝叶斯阈值学习块只应输出一次.

        历史 bug(T206 合并遗留): 函数内有一组简单版 FEATURE_MANIFEST
        遍历循环 + "贝叶斯阈值学习"块, 与下方 T206 增强版(含 OTLP 探测)
        完全重复, `ae doctor` 特性面板整体输出两遍。
        """
        monkeypatch.chdir(tmp_path)  # 无 ae.toml
        from auto_engineering.config import feature_flags
        from auto_engineering.config.feature_flags import FEATURE_MANIFEST
        import auto_engineering.cli.doctor as doctor_mod

        status = {
            f.key: {"active": True, "agent_mode": "both",
                    "activation": f"{f.key}=1"}
            for f in FEATURE_MANIFEST
        }
        monkeypatch.setattr(
            feature_flags, "get_feature_status", lambda: status)
        monkeypatch.setattr(
            feature_flags, "_count_requirements", lambda: 10)
        monkeypatch.setattr(
            doctor_mod, "_check_otlp_connectivity", lambda: "disabled")

        lines = doctor_mod.render_optional_features()
        texts = [text for _, text in lines]
        dupes = sorted({t for t in texts if texts.count(t) > 1})
        assert not dupes, (
            f"检测到重复输出 {len(dupes)} 种行 (P1-5 回归): {dupes}"
        )

    def test_feature_list_and_bayesian_block_present(
        self, monkeypatch, tmp_path
    ) -> None:
        """修复后特性列表与贝叶斯块仍应各输出一次(不能删过头)."""
        monkeypatch.chdir(tmp_path)
        from auto_engineering.config import feature_flags
        from auto_engineering.config.feature_flags import FEATURE_MANIFEST
        import auto_engineering.cli.doctor as doctor_mod

        status = {
            f.key: {"active": True, "agent_mode": "both",
                    "activation": f"{f.key}=1"}
            for f in FEATURE_MANIFEST
        }
        monkeypatch.setattr(
            feature_flags, "get_feature_status", lambda: status)
        monkeypatch.setattr(
            feature_flags, "_count_requirements", lambda: 10)
        monkeypatch.setattr(
            doctor_mod, "_check_otlp_connectivity", lambda: "disabled")

        lines = doctor_mod.render_optional_features()
        texts = [text for _, text in lines]
        assert any("贝叶斯阈值学习" in t for t in texts), (
            "贝叶斯阈值学习块不应被误删"
        )
        # 每个 FEATURE_MANIFEST 条目应恰好出现一次
        for f in FEATURE_MANIFEST:
            occurrences = [t for t in texts if f.description in t]
            assert len(occurrences) == 1, (
                f"特性 {f.key} 应输出 1 次, 实际 {len(occurrences)} 次"
            )
