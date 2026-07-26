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

        历史 bug: AE_LLM_PROVIDER / AE_AUDIT_LOG_DIR 不在映射中 →
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

    def test_template_emits_expected_kebab_keys(self, tmp_path) -> None:
        """模板含代表性 kebab-case key (含曾丢失的 llm-provider)。"""
        from auto_engineering.cli.doctor import _init_config

        _init_config(tmp_path)
        text = (tmp_path / "ae.toml").read_text(encoding="utf-8")
        for kebab in (
            "audit-log", "metrics", "otlp-endpoint", "token-tracking",
            "debug", "pii-enabled", "max-tool-calls", "gate-timeout",
            "audit-log-dir", "llm-provider",
        ):
            assert re.search(rf"^# {re.escape(kebab)} = ", text, re.MULTILINE), (
                f"模板缺少 kebab key: {kebab}"
            )

    def test_template_roundtrip_readable(self, tmp_path) -> None:
        """把模板每个 key 取消注释并赋值后, AeConfig 必须全部读到。

        这是核心回归: 模拟用户照模板"取消注释所需功能"的真实路径。
        """
        from auto_engineering.config.ae_config import SECTION_KEY_MAP, AeConfig
        from auto_engineering.cli.doctor import _init_config

        _init_config(tmp_path)
        template = (tmp_path / "ae.toml").read_text(encoding="utf-8")

        # 逐行转换: 保留 [section]; 把 "# key = ..." 转为 'key = "1"'
        active_lines: list[str] = []
        for line in template.splitlines():
            stripped = line.strip()
            if stripped.startswith("["):
                active_lines.append(stripped)
                continue
            m = re.match(r"^# ([a-z][a-z0-9-]*) = ", stripped)
            if m:
                active_lines.append(f'{m.group(1)} = "1"')
        (tmp_path / "ae.toml").write_text(
            "\n".join(active_lines) + "\n", encoding="utf-8")

        cfg = AeConfig(tmp_path)
        for mapping in SECTION_KEY_MAP.values():
            for ae_key in mapping.values():
                assert cfg.get(ae_key) == "1", (
                    f"模板取消注释后 AeConfig 读不到 {ae_key} "
                    f"(实际={cfg.get(ae_key)!r}) — 模板/读取器 key 格式不一致"
                )


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
            feature_status_for_action)
        from auto_engineering.config.runtime_config import RuntimeConfig
        cfg = RuntimeConfig.from_project(tmp_path)
        status = feature_status_for_action(cfg.environ)
        assert status.get("AE_METRICS") is True
        assert status.get("AE_DEBUG") is True
