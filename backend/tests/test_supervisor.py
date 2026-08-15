import json
import unittest

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.agent.context import AgentRunContext
from app.agent.routing import AgentProfile, build_default_agent_registry
from app.agent.supervisor import Supervisor
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


class SupervisorTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.engine = create_engine("sqlite:///:memory:")
        Base.metadata.create_all(self.engine)
        self.db = sessionmaker(bind=self.engine)()
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
        registry = build_default_agent_registry()
        supervisor = Supervisor(
            provider=object(),  # type: ignore[arg-type]
            registry=registry,
            goal_runtime=self.runtime,
            parent_goal=self.parent,
            context=self.context,
            agent_factory=lambda profile: FakeAgent(profile),
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
        )

        events = [
            event
            async for event in supervisor.run(question="研究并比较", mode="auto")
        ]
        children = self.db.query(GoalNode).filter(GoalNode.parent_id == self.parent.id).all()
        status_by_profile = {goal.agent_profile: goal.status for goal in children}

        self.assertEqual(status_by_profile["local_retriever"], "failed")
        self.assertEqual(status_by_profile["web_researcher"], "completed")
        self.assertEqual(status_by_profile["expert_synthesizer"], "completed")
        self.assertFalse(any(event["event"] == "error" for event in events))
