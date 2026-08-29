"""ae.toml 配置读取器 + 模板生成器契约测试.

2026-07-26 真跑验证发现: doctor._init_config 生成的模板用 AE_UPPER key,
但 AeConfig._load_toml 只读 kebab-case key → 模板不可用、开关假启用。
修复后两者同源于 SECTION_KEY_MAP。本测试锁定该契约, 防止再漂移。
"""

from __future__ import annotations

import re


class TestSectionKeyMapSSOT:
    """SECTION_KEY_MAP 是读取器与生成器的唯一权威 key 映射。"""

    def test_covers_full_feature_manifest(self) -> None:
        """SECTION_KEY_MAP 必须覆盖 FEATURE_MANIFEST 全部 key (防漏配).

        历史 bug: AE_AUDIT_LOG_DIR 不在映射中 →
        即使写进 ae.toml 也读不到。
        """
        from auto_engineering.config.ae_config import SECTION_KEY_MAP
        from auto_engineering.config.feature_flags import FEATURE_MANIFEST

        mapped = {
            ae_key
            for mapping in SECTION_KEY_MAP.values()
            for ae_key in mapping.values()
        }
        manifest = {f.key for f in FEATURE_MANIFEST}
        missing = manifest - mapped
        assert not missing, (
            f"SECTION_KEY_MAP 缺少 FEATURE_MANIFEST key (ae.toml 将不可配): {missing}"
        )


class TestInitConfigTemplateContract:
    """ae doctor --init-config 生成的模板必须被 AeConfig 真实读取。"""

    def test_template_has_no_ae_upper_keys(self, tmp_path) -> None:
        """模板不得含 AE_UPPER 形式的 key 行 (读取器不识别 = bug 形态)。"""
        from auto_engineering.cli.doctor import _init_config

        _init_config(tmp_path)
        text = (tmp_path / "ae.toml").read_text(encoding="utf-8")
        bad = re.findall(r"^\s*#?\s*AE_[A-Z_]+\s*=", text, re.MULTILINE)
        assert not bad, f"模板含 AE_UPPER key (读取器不识别): {bad}"

    def test_standard_profile_emits_expected_kebab_keys(self, tmp_path) -> None:
        """标准 Profile 含可读键、推荐治理值且不暴露退役配置。"""
        from auto_engineering.cli.doctor import _init_config

        _init_config(tmp_path)
        text = (tmp_path / "ae.toml").read_text(encoding="utf-8")
        for kebab in (
            "audit-log", "metrics", "otlp-endpoint", "token-tracking",
            "debug", "pii-enabled", "max-tool-calls", "gate-timeout",
            "audit-log-dir",
        ):
            assert re.search(rf"^#? ?{re.escape(kebab)} = ", text, re.MULTILINE), (
                f"标准 Profile 缺少 kebab key: {kebab}"
            )
        assert re.search(r'^metrics = "1"', text, re.MULTILINE)
        assert re.search(r'^audit-log = "1"', text, re.MULTILINE)
        assert re.search(r'^token-tracking = "1"', text, re.MULTILINE)
        assert not re.search(r'^session-max-ticks = ', text, re.MULTILINE)
        assert "llm-provider" not in text

    def test_retired_llm_provider_is_not_configurable(self) -> None:
        """宿主负责模型选择，Core 不再声明 AE_LLM_PROVIDER。"""
        from auto_engineering.config.ae_config import SECTION_KEY_MAP
        from auto_engineering.config.feature_flags import FEATURE_MANIFEST

        assert all(
            ae_key != "AE_LLM_PROVIDER"
            for mapping in SECTION_KEY_MAP.values()
            for ae_key in mapping.values()
        )
        assert all(flag.key != "AE_LLM_PROVIDER" for flag in FEATURE_MANIFEST)

    def test_standard_profile_roundtrip_readable(self, tmp_path) -> None:
        """生成值必须被 AeConfig 逐项无损读回。"""
        from auto_engineering.cli.doctor import _init_config
        from auto_engineering.config.ae_config import AeConfig, standard_profile_values

        _init_config(tmp_path)
        cfg = AeConfig(tmp_path)
        assert cfg.is_configured
        for ae_key, expected in standard_profile_values().items():
            assert cfg.get(ae_key) == expected

    def test_empty_and_commented_files_are_not_configured(self, tmp_path) -> None:
        from auto_engineering.config.ae_config import AeConfig

        (tmp_path / "ae.toml").write_text("# only comments\n", encoding="utf-8")
        assert not AeConfig(tmp_path).is_configured

    def test_parse_error_is_exposed(self, tmp_path) -> None:
        from auto_engineering.config.ae_config import AeConfig

        (tmp_path / "ae.toml").write_text("[broken\n", encoding="utf-8")
        cfg = AeConfig(tmp_path)
        assert cfg.load_error
        assert not cfg.is_configured

    def test_deprecated_session_thresholds_emit_migration_warning(
        self, tmp_path
    ) -> None:
        from auto_engineering.config.ae_config import AeConfig

        (tmp_path / "ae.toml").write_text(
            '[threshold]\nsession-max-ticks = "8"\n',
            encoding="utf-8",
        )
        cfg = AeConfig(tmp_path)
        assert cfg.migration_warnings
        assert "不再控制正常续跑" in cfg.migration_warnings[0]


class TestAeConfigKebabContract:
    """AeConfig 读取 kebab-case key 的基础契约。"""

    def test_reads_kebab_not_ae_upper(self, tmp_path) -> None:
        """ae.toml 用 kebab-case 才被读取; AE_UPPER key 不生效 (文档化契约)。"""
        from auto_engineering.config.ae_config import AeConfig

        (tmp_path / "ae.toml").write_text(
            '[observability]\naudit-log = "1"\n', encoding="utf-8")
        assert AeConfig(tmp_path).get("AE_AUDIT_LOG") == "1"

        (tmp_path / "ae.toml").write_text(
            '[observability]\nAE_AUDIT_LOG = "1"\n', encoding="utf-8")
        # AE_UPPER 不被识别 → 回退默认值 "0"
        assert AeConfig(tmp_path).get("AE_AUDIT_LOG") == "0"

    def test_boolean_true_maps_to_one(self, tmp_path) -> None:
        """TOML boolean true → '1' (docstring 示例契约)。"""
        from auto_engineering.config.ae_config import AeConfig

        (tmp_path / "ae.toml").write_text(
            "[observability]\naudit-log = true\n", encoding="utf-8")
        assert AeConfig(tmp_path).get("AE_AUDIT_LOG") == "1"

    def test_env_overrides_toml(self, tmp_path, monkeypatch) -> None:
        """优先级: 环境变量 > ae.toml。"""
        from auto_engineering.config.ae_config import AeConfig

        (tmp_path / "ae.toml").write_text(
            '[observability]\naudit-log = "1"\n', encoding="utf-8")
        monkeypatch.setenv("AE_AUDIT_LOG", "0")
        assert AeConfig(tmp_path).get("AE_AUDIT_LOG") == "0"


class TestRuntimeConfigAeTomlWiring:
    """BEACON #99: RuntimeConfig.from_project 必须 honoring ae.toml.

    2026-07-26 真跑 P0: CLI 入口曾用 RuntimeConfig()（仅 os.environ），
    ae.toml 从未注入 → 项目配置的开关在引擎运行时全部静默失效
    （审计/度量/OTLP/调试/Token 全 ✗，仅默认开启的 PII ✓）。
    """

    def test_ae_toml_switches_active_via_from_project(
        self, tmp_path, monkeypatch
    ) -> None:
        """ae.toml 设的开关经 from_project 后在 RuntimeConfig 真实生效。"""
        for k in ("AE_METRICS", "AE_AUDIT_LOG", "AE_TOKEN_TRACKING",
                  "AE_DEBUG", "AE_OTLP_ENDPOINT"):
            monkeypatch.delenv(k, raising=False)
        (tmp_path / "ae.toml").write_text(
            "[observability]\n"
            'metrics = "1"\n'
            'audit-log = "1"\n'
            'token-tracking = "1"\n'
            'otlp-endpoint = "http://localhost:4317"\n'
            "[debugging]\n"
            'debug = "1"\n',
            encoding="utf-8")
        from auto_engineering.config.runtime_config import RuntimeConfig
        cfg = RuntimeConfig.from_project(tmp_path)
        assert cfg.metrics_enabled is True
        assert cfg.token_tracking_enabled is True
        assert cfg.get("AE_AUDIT_LOG") == "1"
        assert cfg.get("AE_DEBUG") == "1"
        assert cfg.otlp_endpoint == "http://localhost:4317"

    def test_env_overrides_ae_toml_in_from_project(
        self, tmp_path, monkeypatch
    ) -> None:
        """os.environ 优先于 ae.toml（SSOT 优先级）。"""
        (tmp_path / "ae.toml").write_text(
            '[observability]\nmetrics = "1"\n', encoding="utf-8")
        monkeypatch.setenv("AE_METRICS", "0")
        from auto_engineering.config.runtime_config import RuntimeConfig
        cfg = RuntimeConfig.from_project(tmp_path)
        assert cfg.metrics_enabled is False

    def test_no_ae_toml_behaves_as_plain_runtime_config(
        self, tmp_path, monkeypatch
    ) -> None:
        """ae.toml 缺失时 from_project 等价于 RuntimeConfig()（行为不变）。"""
        monkeypatch.delenv("AE_METRICS", raising=False)
        from auto_engineering.config.runtime_config import RuntimeConfig
        cfg = RuntimeConfig.from_project(tmp_path)  # 无 ae.toml
        assert cfg.metrics_enabled is False  # FeatureFlag 默认 "0"

    def test_host_runtime_budgets_are_typed_and_overridable(
        self, monkeypatch
    ) -> None:
        from auto_engineering.config.runtime_config import RuntimeConfig

        cfg = RuntimeConfig(environ={
            "AE_HOST_MAX_ELAPSED_SECONDS": "90",
            "AE_HOST_MAX_COST_USD": "12.5",
            "AE_HOST_MAX_OUTPUT_TOKENS": "4000",
        })
        assert cfg.host_max_elapsed_seconds == 90.0
        assert cfg.host_max_cost_usd == 12.5
        assert cfg.host_max_output_tokens == 4000


class TestFeatureStatusActionAeToml:
    """P2#3 (2026-07-26 真跑): action.feature_status 必须反映 ae.toml 开关。

    此前 action_builder 调 feature_status_for_action() 无参 → 读裸 os.environ
    → action JSON 的 feature_status 漏报 ae.toml 激活的开关（仅显默认开的 PII）。
    修复后传 get_default_config().environ（合并 ae.toml）。
    """

    def test_feature_status_for_action_reflects_ae_toml(
        self, tmp_path, monkeypatch
    ) -> None:
        for k in ("AE_METRICS", "AE_DEBUG"):
            monkeypatch.delenv(k, raising=False)
        (tmp_path / "ae.toml").write_text(
            "[observability]\nmetrics = \"1\"\n[debugging]\ndebug = \"1\"\n",
            encoding="utf-8")
        from auto_engineering.config.feature_flags import (
            feature_status_for_action,
        )
        from auto_engineering.config.runtime_config import RuntimeConfig
        cfg = RuntimeConfig.from_project(tmp_path)
        status = feature_status_for_action(cfg.environ)
        assert status.get("AE_METRICS") is True
        assert status.get("AE_DEBUG") is True
