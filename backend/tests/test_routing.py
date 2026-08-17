import json
import unittest
from pathlib import Path
from types import SimpleNamespace

from app.agent.context import AgentRunContext
from app.agent.loop import AgentLoop
from app.agent.model_selection import select_agent_model, select_fast_model
from app.agent.routing import ComplexityRouter, build_default_agent_registry
from app.agent.tools import ToolRegistry


class ComplexityRouterTests(unittest.TestCase):
    def setUp(self):
        self.router = ComplexityRouter()

    def test_empty_request_uses_fast_direct_path(self):
        decision = self.router.route("")
        self.assertEqual(decision.tier, "fast")
        self.assertEqual(decision.route, "direct")
        self.assertIn("empty_request", decision.reasons)

    def test_simple_fact_is_fast(self):
        decision = self.router.route("这份文档有多少页？")
        self.assertEqual(decision.tier, "fast")
        self.assertFalse(decision.requires_decomposition)

    def test_web_research_is_at_least_standard(self):
        decision = self.router.route("请搜索相关资料并总结主要结论", mode="web")
        self.assertIn(decision.tier, {"standard", "expert"})
        self.assertIn("web_mode", decision.reasons)

    def test_cross_source_analysis_uses_supervisor(self):
        decision = self.router.route("请比较多个来源，分析差异并生成带引用的研究报告")
        self.assertEqual(decision.tier, "expert")
        self.assertEqual(decision.route, "supervisor")
        self.assertTrue(decision.requires_decomposition)
        self.assertEqual(decision.max_depth, 2)

    def test_table_driven_routing_evaluation_cases(self):
        fixture_path = Path(__file__).parent / "fixtures" / "routing_cases.json"
        cases = json.loads(fixture_path.read_text(encoding="utf-8"))

        for case in cases:
            with self.subTest(case=case["name"]):
                decision = self.router.route(case["question"], mode=case["mode"])
                self.assertEqual(decision.tier, case["expected_tier"])
                self.assertEqual(decision.route, case["expected_route"])
                self.assertEqual(decision.tier_preference, "auto")

    def test_manual_tier_override_is_deterministic(self):
        expected = {
            "fast": ("direct", 0, False),
            "standard": ("tool_agent", 2, False),
            "expert": ("supervisor", 4, True),
        }
        for tier, (route, score, decomposition) in expected.items():
            with self.subTest(tier=tier):
                decision = self.router.route(
                    "请比较多个来源并生成报告",
                    mode="web",
                    tier_preference=tier,
                )
                self.assertEqual(decision.tier, tier)
                self.assertEqual(decision.route, route)
                self.assertEqual(decision.score, score)
                self.assertEqual(decision.requires_decomposition, decomposition)
                self.assertEqual(decision.tier_preference, tier)
                self.assertEqual(decision.reasons, ("manual_tier_override",))

    def test_invalid_manual_tier_is_rejected(self):
        with self.assertRaisesRegex(ValueError, "tier_preference"):
            self.router.route("question", tier_preference="invalid")


class AgentRegistryTests(unittest.TestCase):
    def test_default_registry_has_three_tiers(self):
        registry = build_default_agent_registry()
        self.assertEqual({profile.tier for profile in registry.list()}, {"fast", "standard", "expert"})
        self.assertEqual(registry.require("fast_general").max_iterations, 1)
        self.assertEqual(registry.require("fast_general").tool_call_budget, 2)
        self.assertEqual(registry.require("fast_general").tool_repeat_limit, 1)
        self.assertEqual(registry.require("standard_research").tool_repeat_limit, 3)
        self.assertEqual(registry.require("expert_supervisor").tool_repeat_limit, 5)
        self.assertEqual(registry.require("expert_supervisor").max_children, 4)
        self.assertEqual(registry.require("local_retriever").max_attempts, 2)
        self.assertEqual(registry.require("web_researcher").max_attempts, 2)

    def test_duplicate_and_invalid_profiles_are_rejected(self):
        registry = build_default_agent_registry()
        with self.assertRaises(ValueError):
            registry.register(registry.require("fast_general"))

    def test_model_selection_uses_tier_override_and_explicit_default(self):
        registry = build_default_agent_registry()
        config = SimpleNamespace(
            llm_provider="ollama",
            ollama_llm_model="default-model",
            openai_llm_model="openai-default",
            anthropic_llm_model="anthropic-default",
            agent_fast_model="small-model",
            agent_standard_model=None,
            agent_expert_model="large-model",
        )

        fast = select_agent_model(registry.require("fast_general"), config=config)
        standard = select_agent_model(
            registry.require("standard_research"), config=config
        )
        synthesizer = select_agent_model(
            registry.require("expert_synthesizer"), config=config
        )

        self.assertEqual((fast.model, fast.model_key), ("small-model", "fast"))
        self.assertFalse(fast.uses_default)
        self.assertEqual(standard.model, "default-model")
        self.assertTrue(standard.uses_default)
        self.assertEqual(synthesizer.model, "large-model")

    def test_select_fast_model_uses_configured_fast_model(self):
        config = SimpleNamespace(
            llm_provider="ollama",
            ollama_llm_model="default-model",
            openai_llm_model="openai-default",
            anthropic_llm_model="anthropic-default",
            agent_fast_model="fast-model",
            agent_standard_model=None,
            agent_expert_model=None,
        )

        fast = select_fast_model(config=config)

        self.assertEqual((fast.model, fast.model_key), ("fast-model", "fast"))
        self.assertFalse(fast.uses_default)

    def test_select_fast_model_falls_back_to_default_llm(self):
        config = SimpleNamespace(
            llm_provider="ollama",
            ollama_llm_model="default-model",
            openai_llm_model="openai-default",
            anthropic_llm_model="anthropic-default",
            agent_fast_model=None,
            agent_standard_model=None,
            agent_expert_model=None,
        )

        fast = select_fast_model(config=config)

        self.assertEqual(fast.model, "default-model")
        self.assertTrue(fast.uses_default)


class AgentToolPolicyTests(unittest.IsolatedAsyncioTestCase):
    def test_agent_tier_does_not_filter_tool_prompt(self):
        registry = ToolRegistry()

        async def local_tool() -> str:
            return "local"

        async def web_tool() -> str:
            return "web"

        registry.register("local_tool", "local", {"type": "object"}, local_tool, source="builtin")
        registry.register("web_tool", "web", {"type": "object"}, web_tool, source="web")
        context = AgentRunContext(
            db=object(),
            conversation_id="conversation",
        )  # type: ignore[arg-type]
        agent = AgentLoop(provider=object(), tools=registry)  # type: ignore[arg-type]

        tool_list = agent._build_tool_list(context)
        self.assertIn("local_tool", tool_list)
        self.assertIn("web_tool", tool_list)
        local_tool_list = agent._build_tool_list(AgentRunContext(
            db=object(),
            conversation_id="conversation",
            mode="local",
        ))  # type: ignore[arg-type]
        self.assertIn("local_tool", local_tool_list)
        self.assertNotIn("web_tool", local_tool_list)

    async def test_agent_tier_does_not_block_direct_tool_execution(self):
        registry = ToolRegistry()

        async def web_tool() -> str:
            return "must not run"

        registry.register("web_tool", "web", {"type": "object"}, web_tool, source="web")
        context = AgentRunContext(
            db=object(),
            conversation_id="conversation",
        )  # type: ignore[arg-type]
        agent = AgentLoop(provider=object(), tools=registry)  # type: ignore[arg-type]

        events = [
            event
            async for event in agent._execute_tool("web_tool", {}, 1, context)
        ]
        self.assertEqual(events[-1]["data"]["status"], "completed")
        self.assertEqual(events[-1]["data"]["result"], "must not run")
