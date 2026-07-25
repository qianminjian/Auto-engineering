"""T67: SignalDetector — 5 种信号检测 (F.4)."""

from auto_engineering.metrics.signals import Signal, SignalDetector


class TestSignalDetectorTrend:
    """Trend detection — Mann-Kendall simple or stat-based."""

    def test_detects_upward_trend(self):
        detector = SignalDetector(min_samples=5)
        history = [5, 6, 7, 8, 9, 10, 11, 12]  # clear upward
        signals = detector._detect_trend(history, "M1_loop_efficiency")
        assert any(s.name == "m1_increasing_trend" for s in signals)

    def test_detects_downward_trend(self):
        detector = SignalDetector(min_samples=5)
        history = [12, 11, 10, 9, 8, 7, 6, 5]
        signals = detector._detect_trend(history, "M2_critic_major_rate")
        assert any(s.name == "m2_decreasing_trend" for s in signals)

    def test_insufficient_data_no_signal(self):
        detector = SignalDetector(min_samples=10)
        history = [1, 2, 3]
        signals = detector._detect_trend(history, "M1_loop_efficiency")
        assert signals == []

    def test_flat_trend_no_signal(self):
        detector = SignalDetector(min_samples=5)
        history = [7, 7, 7, 7, 7, 7]
        signals = detector._detect_trend(history, "M1_loop_efficiency")
        assert len(signals) == 0  # flat = no trend


class TestSignalDetectorMutation:
    """Mutation detection — IQR outlier / sudden change."""

    def test_detects_sudden_spike(self):
        detector = SignalDetector(min_samples=5)
        baseline = [5.0, 5.0, 4.0, 6.0, 5.0]
        latest = 20.0  # 4x spike
        signals = detector._detect_mutation(latest, baseline, "M1_loop_efficiency")
        assert len(signals) > 0

    def test_normal_value_no_mutation(self):
        detector = SignalDetector(min_samples=5)
        baseline = [5.0, 5.0, 4.0, 6.0, 5.0]
        latest = 5.0
        signals = detector._detect_mutation(latest, baseline, "M1_loop_efficiency")
        assert len(signals) == 0


class TestSignalDetectorRatioAnomaly:
    """Ratio anomaly — M2 > threshold."""

    def test_high_major_rate_triggers(self):
        detector = SignalDetector(major_rate_threshold=0.5)
        signals = detector._detect_ratio_anomaly(
            major_rate=0.8, plan_refine_count=0
        )
        assert any(s.name == "high_critic_major_rate" for s in signals)

    def test_normal_rate_no_signal(self):
        detector = SignalDetector(major_rate_threshold=0.5)
        signals = detector._detect_ratio_anomaly(
            major_rate=0.2, plan_refine_count=0
        )
        assert len(signals) == 0

    def test_high_refine_rate_triggers(self):
        detector = SignalDetector(refine_rate_threshold=3)
        signals = detector._detect_ratio_anomaly(
            major_rate=0.0, plan_refine_count=5
        )
        assert any(s.name == "high_plan_refine_frequency" for s in signals)


class TestSignalDetectorCostAlert:
    """Cost alert — token budget threshold."""

    def test_token_budget_exceeded_triggers(self):
        detector = SignalDetector(token_budget=100000)
        signals = detector._detect_cost_alert(total_tokens=150000)
        assert any(s.name == "token_budget_exceeded" for s in signals)

    def test_token_within_budget_no_signal(self):
        detector = SignalDetector(token_budget=100000)
        signals = detector._detect_cost_alert(total_tokens=50000)
        assert len(signals) == 0


class TestSignalDetectorColdStartM5:
    """Cold-start M5 efficiency detection — hardcoded threshold < COLD_START_MIN_SAMPLES."""

    def test_cold_start_m5_drop_triggers_warn(self):
        detector = SignalDetector(
            cold_start_min_samples=10,
            cold_start_token_threshold=200000,
        )
        signals = detector._detect_token_budget_internal(
            latest_tokens=250000,
            history=[],  # < 10 requirements → cold start
            baseline={},
            use_stat=False,
        )
        assert any(
            s.name == "token_efficiency_drop" and s.severity == "WARN"
            for s in signals
        )

    def test_cold_start_normal_no_signal(self):
        detector = SignalDetector(
            cold_start_min_samples=10,
            cold_start_token_threshold=200000,
        )
        signals = detector._detect_token_budget_internal(
            latest_tokens=50000, history=[], baseline={}, use_stat=False
        )
        assert len(signals) == 0


class TestSignalDetectorAnalyze:
    """Full analyze() method — runs all 5 design-aligned detectors."""

    def test_analyze_returns_list_of_signals(self):
        detector = SignalDetector(min_samples=5)
        requirement_history = [
            {"M1_loop_efficiency": i, "M2_critic_major_rate": 0.0,
             "M4_plan_refine_count": 0,
             "M3_verification_trigger_rate": {},
             "M5_token_efficiency": {"total_tokens": 40000, "efficiency_ratio": 5.0}}
            for i in range(1, 12)
        ]
        baseline = None
        signals = detector.analyze(requirement_history, baseline)
        assert isinstance(signals, list)
        for s in signals:
            assert isinstance(s, Signal)

    def test_analyze_cold_start_detects_slow_convergence(self):
        detector = SignalDetector(min_samples=5)
        # Last requirement has very high tick count → slow_convergence
        requirement_history = [
            {"M1_loop_efficiency": i, "M2_critic_major_rate": 0.0,
             "M4_plan_refine_count": 0,
             "M3_verification_trigger_rate": {},
             "M5_token_efficiency": {"total_tokens": 10000, "efficiency_ratio": 1.0}}
            for i in range(1, 11)
        ] + [
            {"M1_loop_efficiency": 25, "M2_critic_major_rate": 0.0,
             "M4_plan_refine_count": 0,
             "M3_verification_trigger_rate": {},
             "M5_token_efficiency": {"total_tokens": 10000, "efficiency_ratio": 1.0}},
        ]
        signals = detector.analyze(requirement_history, None)
        assert any(s.name == "slow_convergence" for s in signals)

    def test_analyze_detects_major_trend(self):
        detector = SignalDetector(min_samples=5)
        # M2 rates increasing: 0.1, 0.2, 0.3, 0.4, 0.5 → 4 increases
        requirement_history = [
            {"M1_loop_efficiency": 5, "M2_critic_major_rate": rate,
             "M4_plan_refine_count": 0,
             "M3_verification_trigger_rate": {},
             "M5_token_efficiency": {"total_tokens": 10000, "efficiency_ratio": 1.0}}
            for rate in [0.1, 0.2, 0.3, 0.4, 0.5]
        ]
        signals = detector.analyze(requirement_history, None)
        assert any(s.name == "critic_major_increasing" for s in signals)
