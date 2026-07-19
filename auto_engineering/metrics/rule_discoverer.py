"""DiagnosticRuleDiscoverer — Spearman correlation rule discovery (T71).

Design spec: v5.6-Design-Loop.md Appendix F.11.
"""
from __future__ import annotations

import json
import math
import time
from dataclasses import dataclass, field
from pathlib import Path


@dataclass
class CandidateRule:
    """Candidate diagnostic rule discovered from production data (F.11)."""

    signal_name: str
    metric: str
    causes: list[str] = field(default_factory=list)
    actions: list[str] = field(default_factory=list)
    auto_params: list[str] = field(default_factory=list)
    human_actions: list[int] = field(default_factory=list)
    correlation_score: float = 0.0
    confidence: float = 0.0
    sample_size: int = 0
    supporting_evidence: str = ""


class DiagnosticRuleDiscoverer:
    """Discovers diagnostic rules from production data via Spearman correlation (F.11).

    Uses offline correlation analysis of accumulated requirements instead of
    online subagent stress testing.
    """

    def __init__(self, metrics_dir: Path) -> None:
        self._metrics_dir = metrics_dir
        self._rules_dir = metrics_dir / "baselines" / "candidate_rules"
        self._rules_dir.mkdir(parents=True, exist_ok=True)

    def discover(self, min_requirements: int = 30) -> list[CandidateRule]:
        reqs_dir = self._metrics_dir / "requirements"
        if not reqs_dir.exists():
            return []

        summaries = []
        for req_path in reqs_dir.iterdir():
            summary_file = req_path / "summary.json"
            if summary_file.exists():
                summaries.append(json.loads(summary_file.read_text()))

        if len(summaries) < min_requirements:
            return []

        candidates: list[CandidateRule] = []
        candidates.extend(self._scan_requirement_fuzziness(summaries))
        candidates.extend(self._scan_design_doc_size(summaries))
        candidates.extend(self._scan_resume_frequency(summaries))
        candidates.extend(self._scan_model_changes(summaries))
        candidates.extend(self._scan_requirement_complexity(summaries))
        candidates.extend(self._scan_cross_component_coupling(summaries))

        candidates.sort(key=lambda r: r.correlation_score, reverse=True)
        self._save_candidates(candidates)
        return candidates

    # ── 6 pressure dimension scans (F.11.2) ──

    def _scan_requirement_fuzziness(self, summaries) -> list[CandidateRule]:
        candidates = []
        fuzzy_reqs = [s for s in summaries if s.get("M4_plan_refine_count", 0) >= 2]
        clear_reqs = [s for s in summaries if s.get("M4_plan_refine_count", 0) == 0]
        if len(fuzzy_reqs) < 5 or len(clear_reqs) < 5:
            return candidates
        # Use Spearman on the combined ranked data
        all_reqs = fuzzy_reqs + clear_reqs
        m4_vals = [float(s.get("M4_plan_refine_count", 0)) for s in all_reqs]
        m2_vals = [float(s.get("M2_critic_major_rate", 0)) for s in all_reqs]
        rho, p_value = self._spearman_r(m4_vals, m2_vals)
        if abs(rho) > 0.5 and p_value < 0.05:
            fuzzy_m2 = [s["M2_critic_major_rate"] for s in fuzzy_reqs]
            clear_m2 = [s["M2_critic_major_rate"] for s in clear_reqs]
            candidates.append(CandidateRule(
                signal_name="fuzziness_causes_major_increase",
                metric="M2",
                causes=[
                    "Requirement ambiguity causes architect/developer misalignment",
                    "Design doc lacks boundary conditions, exposed during implementation",
                ],
                actions=[
                    "Trigger gap_scan review for ambiguous sections",
                    "Suggest adding boundary condition notes in design_doc",
                ],
                correlation_score=abs(rho),
                confidence=1.0 - p_value,
                sample_size=len(all_reqs),
                supporting_evidence=(
                    f"Fuzzy group M2 mean={sum(fuzzy_m2)/len(fuzzy_m2):.2f} "
                    f"vs clear group={sum(clear_m2)/len(clear_m2):.2f}, ρ={rho:.3f}"
                ),
            ))
        return candidates

    def _scan_design_doc_size(self, summaries) -> list[CandidateRule]:
        candidates = []
        sizes = [float(s.get("component_count", s.get("batch_count", 1))) for s in summaries]
        tokens = [float(
            s.get("M5_token_efficiency", {}).get("total_tokens", 0)
            if isinstance(s.get("M5_token_efficiency"), dict) else 0
        ) for s in summaries]
        if len(sizes) < 5:
            return candidates
        rho, p_value = self._spearman_r(sizes, tokens)
        if abs(rho) > 0.5 and p_value < 0.05:
            candidates.append(CandidateRule(
                signal_name="design_doc_size_affects_token_efficiency",
                metric="M5",
                causes=[
                    "Large design documents inflate prompt context",
                    "Component count linearly scales token consumption",
                ],
                actions=[
                    "Consider splitting large design docs by component",
                    "Adjust context offloading threshold for large designs",
                ],
                auto_params=["context_offloading_strategy"],
                human_actions=[0, 1],
                correlation_score=abs(rho),
                confidence=1.0 - p_value,
                sample_size=len(sizes),
                supporting_evidence=(
                    f"Design doc size vs token efficiency: ρ={rho:.3f}, p={p_value:.3f}"
                ),
            ))
        return candidates

    def _scan_resume_frequency(self, summaries) -> list[CandidateRule]:
        candidates = []
        resumes = [float(s.get("resume_count", 0)) for s in summaries]
        m1_vals = [float(s.get("M1_loop_efficiency", 0)) for s in summaries]
        if len(resumes) < 5:
            return candidates
        rho, p_value = self._spearman_r(resumes, m1_vals)
        if abs(rho) > 0.5 and p_value < 0.05:
            candidates.append(CandidateRule(
                signal_name="frequent_resume_slows_convergence",
                metric="M1",
                causes=[
                    "Frequent interruptions break agent context continuity",
                    "Checkpoint restore overhead adds ticks",
                ],
                actions=[
                    "Investigate root cause of frequent --resume",
                    "Consider increasing checkpoint frequency",
                ],
                human_actions=[0, 1],
                correlation_score=abs(rho),
                confidence=1.0 - p_value,
                sample_size=len(resumes),
                supporting_evidence=(
                    f"Resume frequency vs M1 convergence: ρ={rho:.3f}, p={p_value:.3f}"
                ),
            ))
        return candidates

    def _scan_model_changes(self, summaries) -> list[CandidateRule]:
        candidates = []
        groups: dict[str, list[float]] = {}
        for s in summaries:
            mv = s.get("ai_origin", {}).get("model_version", "unknown")
            if isinstance(s.get("ai_origin"), dict):
                mv = s["ai_origin"].get("model_version", "unknown")
            else:
                mv = "unknown"
            if mv not in groups:
                groups[mv] = []
            groups[mv].append(s.get("M2_critic_major_rate", 0))
        if len(groups) < 2:
            return candidates
        versions = list(groups.keys())
        g0 = groups[versions[0]]
        g1 = groups[versions[1]]
        if len(g0) < 5 or len(g1) < 5:
            return candidates
        mean0 = sum(g0) / len(g0)
        mean1 = sum(g1) / len(g1)
        diff = abs(mean1 - mean0)
        if diff > 0.1:
            candidates.append(CandidateRule(
                signal_name="model_version_affects_major_rate",
                metric="M2",
                causes=[
                    f"Model version change: {versions[0]} → {versions[1]}",
                    "Different models have different code generation quality",
                ],
                actions=[
                    f"Compare M2 between {versions[0]} and {versions[1]}",
                    "Consider adjusting MAJOR rate thresholds per model version",
                ],
                human_actions=[0, 1],
                correlation_score=min(diff / 0.3, 1.0),
                confidence=0.95,
                sample_size=len(g0) + len(g1),
                supporting_evidence=(
                    f"{versions[0]} M2={mean0:.3f} vs {versions[1]} M2={mean1:.3f}"
                ),
            ))
        return candidates

    def _scan_requirement_complexity(self, summaries) -> list[CandidateRule]:
        candidates = []
        batch_counts = [float(s.get("batch_count", s.get("task_count", 1))) for s in summaries]
        m4_vals = [float(s.get("M4_plan_refine_count", 0)) for s in summaries]
        if len(batch_counts) < 5:
            return candidates
        rho, p_value = self._spearman_r(batch_counts, m4_vals)
        if abs(rho) > 0.5 and p_value < 0.05:
            candidates.append(CandidateRule(
                signal_name="complexity_causes_plan_refine",
                metric="M4",
                causes=[
                    "High task count increases probability of plan revision",
                    "Complex requirements are harder to estimate upfront",
                ],
                actions=[
                    "Consider splitting complex requirements into phases",
                    "Mark design items as 'phased implementation'",
                ],
                auto_params=["max_refine_per_source"],
                human_actions=[0, 1],
                correlation_score=abs(rho),
                confidence=1.0 - p_value,
                sample_size=len(batch_counts),
                supporting_evidence=(
                    f"Complexity vs M4 plan_refine: ρ={rho:.3f}, p={p_value:.3f}"
                ),
            ))
        return candidates

    def _scan_cross_component_coupling(self, summaries) -> list[CandidateRule]:
        candidates = []
        coupling = [float(s.get("plate_deep_audit_p1", 0)) for s in summaries]
        trigger_rates = [float(
            s.get("M3_verification_trigger_rate", {}).get("plate_deep_audit", 0)
            if isinstance(s.get("M3_verification_trigger_rate"), dict) else 0
        ) for s in summaries]
        if len(coupling) < 5:
            return candidates
        rho, p_value = self._spearman_r(coupling, trigger_rates)
        if abs(rho) > 0.5 and p_value < 0.05:
            candidates.append(CandidateRule(
                signal_name="cross_component_coupling_triggers_deep_audit",
                metric="M3",
                causes=[
                    "High cross-component coupling increases audit findings",
                    "Plate-level interactions are a common failure mode",
                ],
                actions=[
                    "Review component boundary design",
                    "Consider adding integration contract tests",
                ],
                human_actions=[0, 1],
                correlation_score=abs(rho),
                confidence=1.0 - p_value,
                sample_size=len(coupling),
                supporting_evidence=(
                    f"Coupling vs M3 deep_audit trigger: ρ={rho:.3f}, p={p_value:.3f}"
                ),
            ))
        return candidates

    # ── Statistical helpers ──

    @staticmethod
    def _spearman_r(a: list[float], b: list[float]) -> tuple[float, float]:
        n = min(len(a), len(b))
        if n < 3:
            return 0.0, 1.0

        def rank(vals):
            sorted_idx = sorted(range(len(vals)), key=lambda i: vals[i])
            ranks = [0.0] * len(vals)
            for i, idx in enumerate(sorted_idx):
                ranks[idx] = float(i + 1)
            # Handle ties: assign average rank
            j = 0
            while j < len(ranks):
                k = j
                while k + 1 < len(ranks) and vals[sorted_idx[k]] == vals[sorted_idx[k + 1]]:
                    k += 1
                if k > j:
                    avg = sum(ranks[idx] for idx in sorted_idx[j:k+1]) / (k - j + 1)
                    for idx in sorted_idx[j:k+1]:
                        ranks[idx] = avg
                j = k + 1
            return ranks

        ra, rb = rank(a[:n]), rank(b[:n])
        d2 = sum((ra[i] - rb[i]) ** 2 for i in range(n))
        rho = 1.0 - (6.0 * d2) / (n * (n * n - 1))

        if abs(rho) >= 1.0:
            return rho, 0.0
        t = rho * math.sqrt((n - 2) / (1 - rho * rho))
        p_approx = 0.01 if abs(t) > 2.0 else 0.10
        return rho, p_approx

    def _save_candidates(self, candidates: list[CandidateRule]) -> None:
        ts = time.strftime("%Y%m%d-%H%M%S")
        output_path = self._rules_dir / f"candidates-{ts}.json"
        output_path.write_text(json.dumps(
            [{"signal_name": r.signal_name, "metric": r.metric,
              "causes": r.causes, "actions": r.actions,
              "auto_params": r.auto_params, "human_actions": r.human_actions,
              "correlation_score": r.correlation_score,
              "confidence": r.confidence, "sample_size": r.sample_size,
              "supporting_evidence": r.supporting_evidence}
             for r in candidates],
            indent=2, ensure_ascii=False,
        ))
