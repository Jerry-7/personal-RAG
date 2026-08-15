"""Task complexity routing and Agent capability registration.

The router is intentionally side-effect free.  It produces a validated
decision that a future supervisor/orchestrator can execute without coupling
complexity detection to the existing ReAct ``AgentLoop``.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Literal


AgentTier = Literal["fast", "standard", "expert"]
ChatMode = Literal["auto", "local", "web"]


@dataclass(frozen=True)
class AgentProfile:
    """Capabilities and guardrails for one executable Agent role."""

    name: str
    tier: AgentTier
    role: str
    capabilities: frozenset[str] = field(default_factory=frozenset)
    max_iterations: int = 3
    tool_call_budget: int = 5
    max_children: int = 0
    max_depth: int = 0
    allowed_tool_sources: frozenset[str] = field(default_factory=frozenset)
    model_key: str | None = None


@dataclass(frozen=True)
class RouteDecision:
    """A deterministic, serializable routing result."""

    tier: AgentTier
    route: str
    score: int
    reasons: tuple[str, ...] = ()
    requires_decomposition: bool = False
    max_children: int = 0
    max_depth: int = 0

    def to_dict(self) -> dict[str, object]:
        return {
            "tier": self.tier,
            "route": self.route,
            "score": self.score,
            "reasons": list(self.reasons),
            "requires_decomposition": self.requires_decomposition,
            "max_children": self.max_children,
            "max_depth": self.max_depth,
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

    def route(
        self,
        question: str,
        *,
        mode: ChatMode = "auto",
        history: list[dict[str, str]] | None = None,
    ) -> RouteDecision:
        normalized = (question or "").strip().lower()
        if not normalized:
            return RouteDecision("fast", "direct", 0, ("empty_request",))

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

        if score >= 4:
            tier: AgentTier = "expert"
            route = "supervisor"
            requires_decomposition = True
            max_children, max_depth = 4, 2
        elif score >= 2:
            tier = "standard"
            route = "tool_agent"
            requires_decomposition = False
            max_children, max_depth = 1, 1
        else:
            tier = "fast"
            route = "direct"
            requires_decomposition = False
            max_children, max_depth = 0, 0

        return RouteDecision(
            tier=tier,
            route=route,
            score=score,
            reasons=tuple(reasons),
            requires_decomposition=requires_decomposition,
            max_children=max_children,
            max_depth=max_depth,
        )


def build_default_agent_registry() -> AgentRegistry:
    """Create the initial role registry used by the future supervisor."""
    return AgentRegistry([
        AgentProfile(
            name="fast_general",
            tier="fast",
            role="general",
            capabilities=frozenset({"conversation", "direct_answer"}),
            max_iterations=1,
            tool_call_budget=2,
            allowed_tool_sources=frozenset({"builtin", "skill", "web"}),
            model_key="fast",
        ),
        AgentProfile(
            name="standard_research",
            tier="standard",
            role="researcher",
            capabilities=frozenset({"conversation", "local_retrieval", "web_research", "tool_calling"}),
            max_iterations=5,
            tool_call_budget=5,
            max_children=1,
            max_depth=1,
            allowed_tool_sources=frozenset({"builtin", "skill", "web"}),
            model_key="standard",
        ),
        AgentProfile(
            name="expert_supervisor",
            tier="expert",
            role="supervisor",
            capabilities=frozenset({"planning", "parallel_agents", "evidence_synthesis", "tool_calling"}),
            max_iterations=8,
            tool_call_budget=10,
            max_children=4,
            max_depth=2,
            allowed_tool_sources=frozenset({"builtin", "skill", "web"}),
            model_key="expert",
        ),
        AgentProfile(
            name="local_retriever",
            tier="standard",
            role="retriever",
            capabilities=frozenset({"local_retrieval", "tool_calling"}),
            max_iterations=3,
            tool_call_budget=4,
            allowed_tool_sources=frozenset({"builtin", "skill", "web"}),
            model_key="standard",
        ),
        AgentProfile(
            name="web_researcher",
            tier="standard",
            role="web_researcher",
            capabilities=frozenset({"web_research", "tool_calling"}),
            max_iterations=4,
            tool_call_budget=6,
            allowed_tool_sources=frozenset({"builtin", "skill", "web"}),
            model_key="standard",
        ),
        AgentProfile(
            name="expert_synthesizer",
            tier="expert",
            role="synthesizer",
            capabilities=frozenset({"evidence_synthesis", "tool_calling"}),
            max_iterations=3,
            tool_call_budget=3,
            allowed_tool_sources=frozenset({"builtin", "skill", "web"}),
            model_key="expert",
        ),
    ])
