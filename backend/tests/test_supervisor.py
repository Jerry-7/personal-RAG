import asyncio
import json
import unittest
from unittest.mock import patch

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.agent.context import AgentRunContext
from app.agent.routing import AgentProfile, build_default_agent_registry
from app.agent.supervisor import Supervisor
from app.config import settings
from app.db.database import Base
from app.db.models import GoalNode
from app.services.goal_runtime import GoalRuntime


class FakeAgent:
    def __init__(self, profile: AgentProfile, *, fail_role: str | None = None) -> None:
        self.profile = profile
        self.fail_role = fail_role

    async def run(self, **kwargs):
        if self.profile.role == self.fail_role:
            yield {"event": "error", "data": {"message": f"{self.profile.role} failed"}}
            return
        if self.profile.role == "synthesizer":
            yield {"event": "token", "data": "final synthesized answer [1]"}
            return
        yield {
            "event": "tool_call",
            "data": {"id": self.profile.name, "name": "search", "arguments": {}},
        }
        yield {"event": "token", "data": f"{self.profile.role} evidence [1]"}


class ConcurrentCitationAgent:
    def __init__(self, profile: AgentProfile, state: dict) -> None:
        self.profile = profile
        self.state = state

    async def run(self, **kwargs):
        if self.profile.role == "synthesizer":
            self.state["synthesis_question"] = kwargs["question"]
            yield {"event": "token", "data": "final answer [1] [2]"}
            return

        self.state["active"] += 1
        self.state["max_active"] = max(
            self.state["max_active"], self.state["active"]
        )
        try:
            await asyncio.sleep(0.02)
            context = kwargs["context"]
            index = context.register_source({
                "source_type": self.profile.role,
                "snippet": f"{self.profile.role} source",
            })
            yield {
                "event": "token",
                "data": f"{self.profile.role} evidence [{index}]",
            }
        finally:
            self.state["active"] -= 1


class FlakyAgent:
    def __init__(self, profile: AgentProfile, state: dict) -> None:
        self.profile = profile
        self.state = state

    async def run(self, **kwargs):
        role = self.profile.role
        self.state[role] = self.state.get(role, 0) + 1
        if role == "retriever" and self.state[role] == 1:
            yield {"event": "error", "data": {"message": "temporary retriever failure"}}
            return
        if role == "synthesizer":
            self.state["synthesis_question"] = kwargs["question"]
            yield {"event": "token", "data": "recovered synthesis"}
            return
        yield {"event": "token", "data": f"{role} recovered evidence"}


class BudgetRetryAgent:
    def __init__(self, profile: AgentProfile, state: dict) -> None:
        self.profile = profile
        self.state = state

    async def run(self, **kwargs):
        role = self.profile.role
        context = kwargs["context"]
        if role == "web_researcher":
            self.state["web_attempts"] = self.state.get("web_attempts", 0) + 1
            self.state.setdefault("sessions", []).append(context.db)
            if self.state["web_attempts"] == 1:
                context.web_pages_used = 2
                context.visited_urls.add("https://example.com/evidence")
                context.tool_output_chars = 123
                yield {"event": "error", "data": {"message": "temporary web failure"}}
                return
            self.state["second_attempt_budget"] = (
                context.web_pages_used,
                set(context.visited_urls),
                context.tool_output_chars,
            )
            yield {"event": "token", "data": "web evidence after retry"}
            return
        if role == "synthesizer":
            yield {"event": "token", "data": "budget-aware synthesis"}
            return
        yield {"event": "token", "data": "local evidence"}


class SupervisorTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.engine = create_engine("sqlite:///:memory:")
        Base.metadata.create_all(self.engine)
        self.session_factory = sessionmaker(bind=self.engine)
        self.db = self.session_factory()
        self.runtime = GoalRuntime(self.db, "run-supervisor")
        self.root, _ = self.runtime.create_root(
            title="复杂研究",
            agent_profile="expert_supervisor",
            input_data={},
        )
        self.parent, _ = self.runtime.create_child(
            parent=self.root,
            title="编排请求",
            kind="agent",
            agent_profile="expert_supervisor",
            input_data={},
        )
        self.context = AgentRunContext(
            db=self.db,
            conversation_id="conversation",
            run_id="run-supervisor",
            goal_node_id=self.parent.id,
            mode="auto",
            agent_profile="expert_supervisor",
            tool_call_budget=10,
        )

    def tearDown(self):
        self.db.close()
        self.engine.dispose()

    async def test_auto_mode_runs_two_workers_then_synthesizer(self):
        standard_patch = patch.object(settings, "agent_standard_model", "standard-model")
        expert_patch = patch.object(settings, "agent_expert_model", "expert-model")
        standard_patch.start()
        expert_patch.start()
        self.addCleanup(standard_patch.stop)
        self.addCleanup(expert_patch.stop)
        registry = build_default_agent_registry()
        supervisor = Supervisor(
            provider=object(),  # type: ignore[arg-type]
            registry=registry,
            goal_runtime=self.runtime,
            parent_goal=self.parent,
            context=self.context,
            agent_factory=lambda profile: FakeAgent(profile),
            session_factory=self.session_factory,
        )

        events = [
            event
            async for event in supervisor.run(question="比较多份资料", mode="auto")
        ]
        goals = (
            self.db.query(GoalNode)
            .filter(GoalNode.run_id == "run-supervisor")
            .order_by(GoalNode.sequence)
            .all()
        )
        worker_goals = [goal for goal in goals if goal.parent_id == self.parent.id]

        self.assertEqual(
            [goal.agent_profile for goal in worker_goals],
            ["local_retriever", "web_researcher", "expert_synthesizer"],
        )
        self.assertTrue(all(goal.status == "completed" for goal in worker_goals))
        self.assertEqual(
            [goal.model_name for goal in worker_goals],
            ["standard-model", "standard-model", "expert-model"],
        )
        dependencies = json.loads(worker_goals[-1].dependencies_json)
        self.assertEqual(dependencies, [worker_goals[0].id, worker_goals[1].id])
        self.assertIn(
            "final synthesized answer",
            "".join(str(event.get("data", "")) for event in events if event["event"] == "token"),
        )
        self.assertEqual(self.context.goal_node_id, self.parent.id)
        self.assertEqual(self.context.agent_profile, "expert_supervisor")

    async def test_failed_worker_does_not_prevent_synthesis(self):
        supervisor = Supervisor(
            provider=object(),  # type: ignore[arg-type]
            registry=build_default_agent_registry(),
            goal_runtime=self.runtime,
            parent_goal=self.parent,
            context=self.context,
            agent_factory=lambda profile: FakeAgent(profile, fail_role="retriever"),
            session_factory=self.session_factory,
        )

        events = [
            event
            async for event in supervisor.run(question="研究并比较", mode="auto")
        ]
        children = self.db.query(GoalNode).filter(GoalNode.parent_id == self.parent.id).all()
        status_by_profile = {goal.agent_profile: goal.status for goal in children}
        retriever_goal = next(
            goal for goal in children if goal.agent_profile == "local_retriever"
        )

        self.assertEqual(status_by_profile["local_retriever"], "failed")
        self.assertEqual(retriever_goal.attempt, 2)
        self.assertEqual(status_by_profile["web_researcher"], "completed")
        self.assertEqual(status_by_profile["expert_synthesizer"], "completed")
        self.assertFalse(any(event["event"] == "error" for event in events))
        self.assertTrue(any(event["event"] == "goal_retrying" for event in events))

    async def test_transient_worker_failure_recovers_on_second_attempt(self):
        state = {}
        supervisor = Supervisor(
            provider=object(),  # type: ignore[arg-type]
            registry=build_default_agent_registry(),
            goal_runtime=self.runtime,
            parent_goal=self.parent,
            context=self.context,
            agent_factory=lambda profile: FlakyAgent(profile, state),
            session_factory=self.session_factory,
        )

        events = [
            event
            async for event in supervisor.run(question="重试研究", mode="auto")
        ]
        children = self.db.query(GoalNode).filter(
            GoalNode.parent_id == self.parent.id
        ).all()
        retriever_goal = next(
            goal for goal in children if goal.agent_profile == "local_retriever"
        )

        self.assertEqual(state["retriever"], 2)
        self.assertEqual(state["web_researcher"], 1)
        self.assertEqual(retriever_goal.status, "completed")
        self.assertEqual(retriever_goal.attempt, 2)
        self.assertIsNone(retriever_goal.error_message)
        self.assertIn("retriever recovered evidence", state["synthesis_question"])
        retry_events = [event for event in events if event["event"] == "goal_retrying"]
        self.assertEqual(len(retry_events), 1)
        self.assertEqual(retry_events[0]["data"]["payload"]["goal"]["attempt"], 2)

    async def test_workers_overlap_and_citations_are_remapped_in_plan_order(self):
        state = {
            "active": 0,
            "max_active": 0,
            "synthesis_question": "",
        }
        supervisor = Supervisor(
            provider=object(),  # type: ignore[arg-type]
            registry=build_default_agent_registry(),
            goal_runtime=self.runtime,
            parent_goal=self.parent,
            context=self.context,
            agent_factory=lambda profile: ConcurrentCitationAgent(profile, state),
            session_factory=self.session_factory,
        )

        events = [
            event
            async for event in supervisor.run(question="并行研究", mode="auto")
        ]

        self.assertEqual(state["max_active"], 2)
        self.assertIn("retriever evidence [1]", state["synthesis_question"])
        self.assertIn("web_researcher evidence [2]", state["synthesis_question"])
        self.assertEqual(
            [citation["index"] for citation in self.context.citations],
            [1, 2],
        )
        self.assertIn(
            "final answer [1] [2]",
            "".join(
                str(event.get("data", ""))
                for event in events
                if event["event"] == "token"
            ),
        )

    async def test_retry_keeps_worker_resource_usage_across_fresh_sessions(self):
        state = {}
        supervisor = Supervisor(
            provider=object(),  # type: ignore[arg-type]
            registry=build_default_agent_registry(),
            goal_runtime=self.runtime,
            parent_goal=self.parent,
            context=self.context,
            agent_factory=lambda profile: BudgetRetryAgent(profile, state),
            session_factory=self.session_factory,
        )

        events = [
            event
            async for event in supervisor.run(question="预算重试", mode="auto")
        ]

        self.assertEqual(state["web_attempts"], 2)
        self.assertIsNot(state["sessions"][0], state["sessions"][1])
        self.assertEqual(
            state["second_attempt_budget"],
            (2, {"https://example.com/evidence"}, 123),
        )
        self.assertEqual(self.context.web_pages_used, 2)
        self.assertIn("https://example.com/evidence", self.context.visited_urls)
        self.assertEqual(
            len([event for event in events if event["event"] == "goal_retrying"]),
            1,
        )
