"""Personal RAG - Agent 主导路由测试

覆盖 AdaptiveComplexityRouter 的三种路由模式:
- model (默认): 模型优先分类, 启发式仅作快通道与失败兜底
- adaptive: 旧混合行为, 启发式为主、低置信度才调模型
- heuristic: 纯启发式, 零模型调用
"""

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
    def test_classifier_request_uses_message_role_tags(self):
        request = AdaptiveComplexityRouter._classifier_request(
            "当前问题",
            [
                {"role": "user", "content": "第一条"},
                {"role": "assistant", "content": "第二条"},
            ],
            "standard",
        )
        self.assertIn('<message index=1 role="user">\n第一条\n</message>', request)
        self.assertIn('<message index=2 role="assistant">\n第二条\n</message>', request)
        self.assertNotIn("<user>", request)

    # ── model 模式 (默认): Agent 主导 ──────────────────────────

    async def test_model_mode_runs_classifier_as_primary(self):
        provider = ClassifierProvider({
            "complexity_score": 5,
            "confidence": 0.86,
            "reasons": ["specialist_reasoning", "multiple_sources"],
        })
        router = AdaptiveComplexityRouter(
            RoutingPolicy(),
            provider,  # type: ignore[arg-type]
            classifier_model="fast-model",
            routing_mode="model",
        )

        decision = await router.route("请分析这个方案")

        self.assertEqual(decision.tier, "expert")
        self.assertEqual(decision.score, 5)
        self.assertEqual(decision.decision_source, "model")
        self.assertEqual(decision.confidence, 0.86)
        self.assertEqual(decision.classifier_model, "fast-model")
        self.assertIn("classifier_assessed", decision.reasons)
        self.assertEqual(len(provider.calls), 1)

    async def test_model_mode_fast_path_skips_model_for_trivial_request(self):
        provider = ClassifierProvider()
        router = AdaptiveComplexityRouter(
            RoutingPolicy(),
            provider,  # type: ignore[arg-type]
            classifier_model="fast-model",
            routing_mode="model",
        )

        decision = await router.route("多少")

        self.assertEqual(decision.tier, "fast")
        self.assertEqual(decision.decision_source, "heuristic")
        self.assertIn("fast_path", decision.reasons)
        self.assertEqual(provider.calls, [])

    async def test_model_mode_fast_path_respects_char_limit(self):
        # 超过 fast_path_max_chars 上限的请求即使启发式高置信也必须走模型
        provider = ClassifierProvider({
            "complexity_score": 0,
            "confidence": 0.9,
            "reasons": ["simple_lookup"],
        })
        router = AdaptiveComplexityRouter(
            RoutingPolicy(),
            provider,  # type: ignore[arg-type]
            classifier_model="fast-model",
            routing_mode="model",
            fast_path_max_chars=5,
        )

        decision = await router.route("帮我总结一下这个文档")

        self.assertEqual(decision.decision_source, "model")
        self.assertEqual(decision.tier, "fast")
        self.assertEqual(len(provider.calls), 1)

    async def test_model_mode_invalid_response_falls_back_to_heuristic(self):
        provider = ClassifierProvider(invalid=True)
        router = AdaptiveComplexityRouter(
            RoutingPolicy(),
            provider,  # type: ignore[arg-type]
            classifier_model="fast-model",
            routing_mode="model",
        )

        decision = await router.route("请分析这个方案")

        self.assertEqual(decision.tier, "standard")
        self.assertEqual(decision.decision_source, "heuristic_fallback")
        self.assertIn("classifier_fallback", decision.reasons)
        self.assertEqual(len(provider.calls), 1)

    async def test_model_mode_web_cannot_be_downgraded_below_standard(self):
        provider = ClassifierProvider({
            "complexity_score": 0,
            "confidence": 0.9,
            "reasons": ["simple_lookup"],
        })
        router = AdaptiveComplexityRouter(
            RoutingPolicy(),
            provider,  # type: ignore[arg-type]
            classifier_model="fast-model",
            routing_mode="model",
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
            routing_mode="model",
        )

        decision = await router.route(
            "请分析这个方案",
            tier_preference="fast",
        )

        self.assertEqual(decision.tier, "fast")
        self.assertEqual(decision.decision_source, "manual")
        self.assertEqual(decision.confidence, 1.0)
        self.assertEqual(provider.calls, [])

    async def test_disabled_classifier_never_calls_model(self):
        provider = ClassifierProvider()
        router = AdaptiveComplexityRouter(
            RoutingPolicy(),
            provider,  # type: ignore[arg-type]
            classifier_model="fast-model",
            enabled=False,
        )

        decision = await router.route("请分析这个方案")

        self.assertEqual(decision.decision_source, "heuristic")
        self.assertEqual(provider.calls, [])

    # ── adaptive 模式: 保留旧混合行为 ──────────────────────────

    async def test_adaptive_mode_clear_request_stays_on_heuristic(self):
        provider = ClassifierProvider()
        router = AdaptiveComplexityRouter(
            RoutingPolicy(),
            provider,  # type: ignore[arg-type]
            classifier_model="fast-model",
            routing_mode="adaptive",
        )

        decision = await router.route(
            "请比较多个来源，分析差异并生成带引用的研究报告"
        )

        self.assertEqual(decision.tier, "expert")
        self.assertEqual(decision.decision_source, "heuristic")
        self.assertGreaterEqual(decision.confidence, 0.9)
        self.assertEqual(provider.calls, [])

    async def test_adaptive_mode_boundary_request_uses_model(self):
        provider = ClassifierProvider({
            "complexity_score": 5,
            "confidence": 0.86,
            "reasons": ["specialist_reasoning", "multiple_sources"],
        })
        router = AdaptiveComplexityRouter(
            RoutingPolicy(),
            provider,  # type: ignore[arg-type]
            classifier_model="fast-model",
            routing_mode="adaptive",
        )

        decision = await router.route("请分析这个方案")

        self.assertEqual(decision.decision_source, "model")
        self.assertEqual(decision.tier, "expert")
        self.assertEqual(len(provider.calls), 1)

    # ── heuristic 模式: 不调模型 ───────────────────────────────

    async def test_heuristic_mode_never_calls_model(self):
        provider = ClassifierProvider()
        router = AdaptiveComplexityRouter(
            RoutingPolicy(),
            provider,  # type: ignore[arg-type]
            classifier_model="fast-model",
            routing_mode="heuristic",
        )

        decision = await router.route("请分析这个方案")

        self.assertEqual(decision.tier, "standard")
        self.assertEqual(decision.decision_source, "heuristic")
        self.assertEqual(provider.calls, [])

    async def test_invalid_routing_mode_raises(self):
        provider = ClassifierProvider()
        with self.assertRaises(ValueError):
            AdaptiveComplexityRouter(
                RoutingPolicy(),
                provider,  # type: ignore[arg-type]
                classifier_model="fast-model",
                routing_mode="bogus",
            )


if __name__ == "__main__":
    unittest.main()
