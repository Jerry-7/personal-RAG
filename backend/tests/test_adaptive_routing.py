import json
import unittest

from app.agent.adaptive_routing import AdaptiveComplexityRouter
from app.agent.routing import RoutingPolicy
from app.providers.base import LLMResponse


class ClassifierProvider:
    def __init__(self, payload=None, *, invalid=False) -> None:
        self.payload = payload or {
            "complexity_score": 3,
            "confidence": 0.8,
            "reasons": ["multi_step_reasoning"],
        }
        self.invalid = invalid
        self.calls = []

    async def chat(self, **kwargs):
        self.calls.append(kwargs)
        return LLMResponse(
            content="not-json" if self.invalid else json.dumps(self.payload)
        )


class AdaptiveComplexityRouterTests(unittest.IsolatedAsyncioTestCase):
    async def test_clear_cross_source_request_stays_on_heuristic_path(self):
        provider = ClassifierProvider()
        router = AdaptiveComplexityRouter(
            RoutingPolicy(),
            provider,  # type: ignore[arg-type]
            classifier_model="fast-model",
        )

        decision = await router.route(
            "请比较多个来源，分析差异并生成带引用的研究报告"
        )

        self.assertEqual(decision.tier, "expert")
        self.assertEqual(decision.decision_source, "heuristic")
        self.assertGreaterEqual(decision.confidence, 0.9)
        self.assertEqual(provider.calls, [])

    async def test_ambiguous_boundary_request_uses_model_score(self):
        provider = ClassifierProvider({
            "complexity_score": 5,
            "confidence": 0.86,
            "reasons": ["specialist_reasoning", "multiple_sources"],
        })
        router = AdaptiveComplexityRouter(
            RoutingPolicy(),
            provider,  # type: ignore[arg-type]
            classifier_model="fast-model",
        )

        decision = await router.route("请分析这个方案")

        self.assertEqual(decision.tier, "expert")
        self.assertEqual(decision.score, 5)
        self.assertEqual(decision.decision_source, "model")
        self.assertEqual(decision.confidence, 0.86)
        self.assertEqual(decision.classifier_model, "fast-model")
        self.assertIn("classifier_assessed", decision.reasons)
        self.assertEqual(len(provider.calls), 1)

    async def test_web_mode_cannot_be_downgraded_below_standard(self):
        provider = ClassifierProvider({
            "complexity_score": 0,
            "confidence": 0.9,
            "reasons": ["simple_lookup"],
        })
        router = AdaptiveComplexityRouter(
            RoutingPolicy(),
            provider,  # type: ignore[arg-type]
            classifier_model="fast-model",
        )

        decision = await router.route("请分析这个方案", mode="web")

        self.assertEqual(decision.tier, "standard")
        self.assertEqual(decision.decision_source, "model")
        self.assertIn("tool_required", decision.reasons)

    async def test_manual_override_never_calls_classifier(self):
        provider = ClassifierProvider()
        router = AdaptiveComplexityRouter(
            RoutingPolicy(),
            provider,  # type: ignore[arg-type]
            classifier_model="fast-model",
        )

        decision = await router.route(
            "请分析这个方案",
            tier_preference="fast",
        )

        self.assertEqual(decision.tier, "fast")
        self.assertEqual(decision.decision_source, "manual")
        self.assertEqual(decision.confidence, 1.0)
        self.assertEqual(provider.calls, [])

    async def test_invalid_classifier_response_falls_back_to_heuristic(self):
        provider = ClassifierProvider(invalid=True)
        router = AdaptiveComplexityRouter(
            RoutingPolicy(),
            provider,  # type: ignore[arg-type]
            classifier_model="fast-model",
        )

        decision = await router.route("请分析这个方案")

        self.assertEqual(decision.tier, "standard")
        self.assertEqual(decision.decision_source, "heuristic_fallback")
        self.assertIn("classifier_fallback", decision.reasons)
        self.assertEqual(len(provider.calls), 1)


if __name__ == "__main__":
    unittest.main()
