import unittest

from app.agent.context import AgentRunContext
from app.agent.loop import AgentLoop
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


class AgentRegistryTests(unittest.TestCase):
    def test_default_registry_has_three_tiers(self):
        registry = build_default_agent_registry()
        self.assertEqual({profile.tier for profile in registry.list()}, {"fast", "standard", "expert"})
        self.assertEqual(registry.require("fast_general").max_iterations, 1)
        all_sources = frozenset({"builtin", "skill", "web"})
        self.assertEqual(registry.require("fast_general").allowed_tool_sources, all_sources)
        self.assertEqual(registry.require("standard_research").allowed_tool_sources, all_sources)
        self.assertEqual(registry.require("expert_supervisor").allowed_tool_sources, all_sources)
        self.assertEqual(registry.require("fast_general").tool_call_budget, 2)
        self.assertEqual(registry.require("expert_supervisor").max_children, 4)
        self.assertEqual(registry.require("local_retriever").max_attempts, 2)
        self.assertEqual(registry.require("web_researcher").max_attempts, 2)

    def test_duplicate_and_invalid_profiles_are_rejected(self):
        registry = build_default_agent_registry()
        with self.assertRaises(ValueError):
            registry.register(registry.require("fast_general"))


class AgentToolPolicyTests(unittest.IsolatedAsyncioTestCase):
    def test_profile_source_policy_filters_tool_prompt(self):
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
            allowed_tool_sources=frozenset({"builtin"}),
        )  # type: ignore[arg-type]
        agent = AgentLoop(provider=object(), tools=registry)  # type: ignore[arg-type]

        tool_list = agent._build_tool_list(context)
        self.assertIn("local_tool", tool_list)
        self.assertNotIn("web_tool", tool_list)
        self.assertTrue(context.can_use_tool_source("builtin"))
        self.assertFalse(context.can_use_tool_source("web"))

    async def test_profile_source_policy_blocks_direct_execution(self):
        registry = ToolRegistry()

        async def web_tool() -> str:
            return "must not run"

        registry.register("web_tool", "web", {"type": "object"}, web_tool, source="web")
        context = AgentRunContext(
            db=object(),
            conversation_id="conversation",
            allowed_tool_sources=frozenset({"builtin"}),
        )  # type: ignore[arg-type]
        agent = AgentLoop(provider=object(), tools=registry)  # type: ignore[arg-type]

        events = [
            event
            async for event in agent._execute_tool("web_tool", {}, 1, context)
        ]
        self.assertEqual(events[-1]["data"]["status"], "failed")
        self.assertIn("does not allow", events[-1]["data"]["result"])
