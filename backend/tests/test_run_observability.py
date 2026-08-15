import unittest
from datetime import datetime, timedelta, timezone

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.api.research import get_research_run, list_research_runs
from app.db.database import Base
from app.db.models import AgentRun, Conversation, ToolExecution
from app.services.goal_runtime import GoalRuntime


class RunObservabilityTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.engine = create_engine("sqlite:///:memory:")
        Base.metadata.create_all(self.engine)
        self.db = sessionmaker(bind=self.engine)()
        self.conversation = Conversation(
            id="observable-conversation",
            title="Observability",
            model_provider="ollama",
            model_name="model",
            embedding_provider="ollama",
            embedding_model="embedding",
        )
        started_at = datetime.now(timezone.utc) - timedelta(seconds=2)
        self.run = AgentRun(
            id="observable-run",
            conversation_id=self.conversation.id,
            mode="auto",
            agent_profile="expert_supervisor",
            route_tier="expert",
            route_name="supervisor",
            route_score=6,
            route_reasons_json='["complex_intent"]',
            route_requires_decomposition=True,
            status="completed",
            web_page_budget=8,
            web_pages_used=3,
            started_at=started_at,
            completed_at=started_at + timedelta(seconds=2),
        )
        self.db.add_all([self.conversation, self.run])
        self.db.commit()
        runtime = GoalRuntime(self.db, self.run.id)
        root, _ = runtime.create_root(
            title="research",
            agent_profile="expert_supervisor",
            input_data={},
        )
        worker, _ = runtime.create_child(
            parent=root,
            title="worker",
            kind="agent",
            agent_profile="web_researcher",
            input_data={},
            tool_call_budget=7,
        )
        self.tool = ToolExecution(
            id="tool-execution",
            run_id=self.run.id,
            node_id=worker.id,
            iteration=1,
            tool_name="web_search",
            arguments_json='{"query": "test"}',
            status="completed",
            duration_ms=125,
        )
        self.db.add(self.tool)
        runtime.transition(worker, "completed")
        runtime.transition(root, "completed")
        self.retry = AgentRun(
            id="observable-retry",
            conversation_id=self.conversation.id,
            retry_of_run_id=self.run.id,
            mode="auto",
            status="failed",
            started_at=datetime.now(timezone.utc),
        )
        self.db.add(self.retry)
        self.db.commit()

    def tearDown(self):
        self.db.close()
        self.engine.dispose()

    async def test_run_list_and_detail_expose_metrics_and_retry_lineage(self):
        listed = await list_research_runs(self.conversation.id, 20, self.db)

        self.assertEqual([run["id"] for run in listed["runs"]], [
            self.retry.id,
            self.run.id,
        ])
        source_summary = listed["runs"][1]
        self.assertEqual(source_summary["retry_count"], 1)
        self.assertEqual(source_summary["metrics"]["agent_count"], 1)
        self.assertEqual(source_summary["metrics"]["tool_calls_used"], 1)
        self.assertEqual(source_summary["metrics"]["tool_call_budget"], 7)
        self.assertEqual(source_summary["routing"]["route"], "supervisor")

        detail = await get_research_run(self.run.id, self.db)

        self.assertEqual(detail["retried_by_run_ids"], [self.retry.id])
        self.assertFalse(detail["retryable"])
        self.assertEqual(detail["metrics"]["duration_ms"], 2000)
        self.assertEqual(detail["metrics"]["tool_duration_ms"], 125)
        self.assertEqual(detail["goals"][1]["tool_call_budget"], 7)
        self.assertEqual(detail["tools"][0]["name"], "web_search")
        self.assertEqual(detail["tools"][0]["arguments"], {"query": "test"})
