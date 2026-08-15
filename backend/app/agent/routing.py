"""Task complexity routing and executable Agent capability registration.

The deterministic router remains side-effect free. Its validated decision is
consumed by the adaptive classifier gate and the Supervisor orchestration path.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Literal


AgentTier = Literal["fast", "standard", "expert"]
AgentTierPreference = Literal["auto", "fast", "standard", "expert"]
ChatMode = Literal["auto", "local", "web"]
RouteDecisionSource = Literal["heuristic", "manual", "model", "heuristic_fallback"]


@dataclass(frozen=True)
class RoutingPolicy:
    """Versioned score thresholds used for automatic tier selection."""

    version: int = 0
    standard_min_score: int = 2
    expert_min_score: int = 4

    def __post_init__(self) -> None:
        if self.version < 0:
            raise ValueError("policy version cannot be negative")
        if not 1 <= self.standard_min_score < self.expert_min_score <= 10:
            raise ValueError(
                "routing thresholds must satisfy 1 <= standard < expert <= 10"
            )


def classify_route_tier(
    score: int,
    policy: RoutingPolicy | None = None,
    *,
    mode: ChatMode = "auto",
) -> AgentTier:
    """Map a complexity score to a tier while retaining hard web constraints."""
    active_policy = policy or RoutingPolicy()
    if score >= active_policy.expert_min_score:
        tier: AgentTier = "expert"
    elif score >= active_policy.standard_min_score:
        tier = "standard"
    else:
        tier = "fast"
    if mode == "web" and tier == "fast":
        return "standard"
    return tier


@dataclass(frozen=True)
class AgentProfile:
    """Capabilities and guardrails for one executable Agent role."""

    name: str
    tier: AgentTier
    role: str
    capabilities: frozenset[str] = field(default_factory=frozenset)
    max_iterations: int = 3
    tool_call_budget: int = 5
    tool_repeat_limit: int = 2
    max_attempts: int = 1
    max_children: int = 0
    max_depth: int = 0
    model_key: str | None = None


@dataclass(frozen=True)
class RouteDecision:
    """A bounded, serializable routing result with decision provenance."""

    tier: AgentTier
    route: str
    score: int
    reasons: tuple[str, ...] = ()
    requires_decomposition: bool = False
    max_children: int = 0
    max_depth: int = 0
    tier_preference: AgentTierPreference = "auto"
    policy_version: int = 0
    decision_source: RouteDecisionSource = "heuristic"
    confidence: float = 1.0
    classifier_model: str = ""
    classifier_original_tokens: int = 0
    classifier_compressed_tokens: int = 0
    classifier_calls: int = 0

    def to_dict(self) -> dict[str, object]:
        return {
            "tier": self.tier,
            "route": self.route,
            "score": self.score,
            "reasons": list(self.reasons),
            "requires_decomposition": self.requires_decomposition,
            "max_children": self.max_children,
            "max_depth": self.max_depth,
            "tier_preference": self.tier_preference,
            "policy_version": self.policy_version,
            "decision_source": self.decision_source,
            "confidence": self.confidence,
            "classifier_model": self.classifier_model,
            "classifier_original_tokens": self.classifier_original_tokens,
            "classifier_compressed_tokens": self.classifier_compressed_tokens,
            "classifier_calls": self.classifier_calls,
        }


class AgentRegistry:
    """Registry for Agent roles and their execution guardrails."""

    def __init__(self, profiles: list[AgentProfile] | None = None) -> None:
        self._profiles: dict[str, AgentProfile] = {}
        for profile in profiles or []:
            self.register(profile)

    def register(self, profile: AgentProfile) -> None:
        if profile.name in self._profiles:
            raise ValueError(f"Agent profile already registered: {profile.name}")
        if profile.max_iterations < 1:
            raise ValueError("max_iterations must be positive")
        if profile.tool_call_budget < 1:
            raise ValueError("tool_call_budget must be positive")
        if profile.tool_repeat_limit < 1:
            raise ValueError("tool_repeat_limit must be positive")
        if profile.max_attempts < 1:
            raise ValueError("max_attempts must be positive")
        if profile.max_children < 0 or profile.max_depth < 0:
            raise ValueError("Agent child/depth limits cannot be negative")
        self._profiles[profile.name] = profile

    def get(self, name: str) -> AgentProfile | None:
        return self._profiles.get(name)

    def list(self, *, tier: AgentTier | None = None) -> list[AgentProfile]:
        profiles = list(self._profiles.values())
        if tier is not None:
            profiles = [profile for profile in profiles if profile.tier == tier]
        return profiles

    def require(self, name: str) -> AgentProfile:
        profile = self.get(name)
        if profile is None:
            raise KeyError(f"Unknown Agent profile: {name}")
        return profile

    def for_decision(self, decision: RouteDecision) -> AgentProfile:
        """Return the first registered profile suitable for a route decision."""
        candidates = self.list(tier=decision.tier)
        if not candidates:
            raise LookupError(f"No Agent registered for tier: {decision.tier}")
        return candidates[0]

    def for_role(self, role: str) -> AgentProfile:
        candidates = [profile for profile in self._profiles.values() if profile.role == role]
        if not candidates:
            raise LookupError(f"No Agent registered for role: {role}")
        return candidates[0]


class ComplexityRouter:
    """Classify a request into a bounded Agent tier.

    This first version uses explicit, explainable signals.  An LLM-based
    classifier can be added later, but must still return this same decision
    shape and remain subject to the hard limits below.
    """

    _complex_markers = (
        "研究", "调研", "分析", "比较", "对比", "综合", "规划", "方案",
        "报告", "评估", "论证", "research", "analy", "compare", "report",
        "plan", "evaluate", "synthesize",
    )
    _multi_source_markers = ("多个", "多份", "跨文档", "来源", "引用", "sources", "documents")
    _simple_markers = ("多少", "是什么", "是否", "有几", "how many", "what is", "is there")

    def __init__(self, policy: RoutingPolicy | None = None) -> None:
        self.policy = policy or RoutingPolicy()

    def route(
        self,
        question: str,
        *,
        mode: ChatMode = "auto",
        history: list[dict[str, str]] | None = None,
        tier_preference: AgentTierPreference = "auto",
    ) -> RouteDecision:
        if tier_preference not in {"auto", "fast", "standard", "expert"}:
            raise ValueError("tier_preference must be auto, fast, standard, or expert")
        if tier_preference != "auto":
            return self._decision_for_tier(
                tier_preference,
                reason="manual_tier_override",
                tier_preference=tier_preference,
                policy_version=self.policy.version,
                decision_source="manual",
                confidence=1.0,
            )

        normalized = (question or "").strip().lower()
        if not normalized:
            return RouteDecision(
                "fast",
                "direct",
                0,
                ("empty_request",),
                policy_version=self.policy.version,
                decision_source="heuristic",
                confidence=1.0,
            )

        score = 0
        reasons: list[str] = []
        if len(normalized) > 240:
            score += 1
            reasons.append("long_request")
        if len(normalized) > 800:
            score += 1
            reasons.append("very_long_request")
        if any(marker in normalized for marker in self._complex_markers):
            score += 2
            reasons.append("complex_intent")
        if any(marker in normalized for marker in self._multi_source_markers):
            score += 2
            reasons.append("multiple_sources")
        if normalized.count("?") + normalized.count("？") > 1:
            score += 1
            reasons.append("multiple_questions")
        if mode == "web":
            score += 1
            reasons.append("web_mode")
        if history and len(history) > 6:
            score += 1
            reasons.append("long_context")
        if any(marker in normalized for marker in self._simple_markers) and score < 3:
            score = max(0, score - 1)
            reasons.append("simple_fact_intent")

        # Explicit web mode requires a research-capable execution path.  Keep
        # this as a hard routing constraint rather than a soft semantic signal.
        if mode == "web" and score < 2:
            score = 2
            reasons.append("tool_access_required")

        return self.decision_for_score(
            score,
            mode=mode,
            reasons=tuple(reasons),
            confidence=self._heuristic_confidence(score, reasons),
        )

    def decision_for_score(
        self,
        score: int,
        *,
        mode: ChatMode,
        reasons: tuple[str, ...],
        confidence: float,
        decision_source: RouteDecisionSource = "heuristic",
        classifier_model: str = "",
        classifier_original_tokens: int = 0,
        classifier_compressed_tokens: int = 0,
        classifier_calls: int = 0,
    ) -> RouteDecision:
        """Apply versioned tier thresholds to a validated complexity score."""
        if not 0 <= score <= 10:
            raise ValueError("complexity score must be between 0 and 10")
        if not 0 <= confidence <= 1:
            raise ValueError("routing confidence must be between 0 and 1")
        tier = classify_route_tier(score, self.policy, mode=mode)
        decision = self._decision_for_tier(tier, policy_version=self.policy.version)
        return RouteDecision(
            tier=decision.tier,
            route=decision.route,
            score=score,
            reasons=reasons,
            requires_decomposition=decision.requires_decomposition,
            max_children=decision.max_children,
            max_depth=decision.max_depth,
            policy_version=self.policy.version,
            decision_source=decision_source,
            confidence=round(confidence, 3),
            classifier_model=classifier_model,
            classifier_original_tokens=classifier_original_tokens,
            classifier_compressed_tokens=classifier_compressed_tokens,
            classifier_calls=classifier_calls,
        )

    def _heuristic_confidence(self, score: int, reasons: list[str]) -> float:
        if "simple_fact_intent" in reasons:
            return 0.9
        if "tool_access_required" in reasons:
            return 0.95
        if "complex_intent" in reasons and "multiple_sources" in reasons:
            return 0.92
        boundary_distance = min(
            abs(score - self.policy.standard_min_score),
            abs(score - self.policy.expert_min_score),
        )
        if boundary_distance == 0:
            return 0.55
        if boundary_distance == 1:
            return 0.65
        return 0.85

    @staticmethod
    def _decision_for_tier(
        tier: AgentTier,
        *,
        reason: str | None = None,
        tier_preference: AgentTierPreference = "auto",
        policy_version: int = 0,
        decision_source: RouteDecisionSource = "heuristic",
        confidence: float = 1.0,
    ) -> RouteDecision:
        route, score, decomposition, max_children, max_depth = {
            "fast": ("direct", 0, False, 0, 0),
            "standard": ("tool_agent", 2, False, 1, 1),
            "expert": ("supervisor", 4, True, 4, 2),
        }[tier]
        return RouteDecision(
            tier=tier,
            route=route,
            score=score,
            reasons=(reason,) if reason else (),
            requires_decomposition=decomposition,
            max_children=max_children,
            max_depth=max_depth,
            tier_preference=tier_preference,
            policy_version=policy_version,
            decision_source=decision_source,
            confidence=confidence,
        )


def build_default_agent_registry() -> AgentRegistry:
    """Create the role registry used by direct and Supervisor execution."""
    return AgentRegistry([
        AgentProfile(
            name="fast_general",
            tier="fast",
            role="general",
            capabilities=frozenset({"conversation", "direct_answer"}),
            max_iterations=1,
            tool_call_budget=2,
            tool_repeat_limit=1,
            model_key="fast",
        ),
        AgentProfile(
            name="standard_research",
            tier="standard",
            role="researcher",
            capabilities=frozenset({"conversation", "local_retrieval", "web_research", "tool_calling"}),
            max_iterations=5,
            tool_call_budget=5,
            tool_repeat_limit=3,
            max_children=1,
            max_depth=1,
            model_key="standard",
        ),
        AgentProfile(
            name="expert_supervisor",
            tier="expert",
            role="supervisor",
            capabilities=frozenset({"planning", "parallel_agents", "evidence_synthesis", "tool_calling"}),
            max_iterations=8,
            tool_call_budget=10,
            tool_repeat_limit=5,
            max_children=4,
            max_depth=2,
            model_key="expert",
        ),
        AgentProfile(
            name="local_retriever",
            tier="standard",
            role="retriever",
            capabilities=frozenset({"local_retrieval", "tool_calling"}),
            max_iterations=3,
            tool_call_budget=4,
            tool_repeat_limit=3,
            max_attempts=2,
            model_key="standard",
        ),
        AgentProfile(
            name="web_researcher",
            tier="standard",
            role="web_researcher",
            capabilities=frozenset({"web_research", "tool_calling"}),
            max_iterations=4,
            tool_call_budget=6,
            tool_repeat_limit=4,
            max_attempts=2,
            model_key="standard",
        ),
        AgentProfile(
            name="expert_synthesizer",
            tier="expert",
            role="synthesizer",
            capabilities=frozenset({"evidence_synthesis", "tool_calling"}),
            max_iterations=3,
            tool_call_budget=3,
            tool_repeat_limit=2,
            model_key="expert",
        ),
    ])
