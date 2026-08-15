import importlib.util
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path

from alembic.migration import MigrationContext
from alembic.operations import Operations
from sqlalchemy import create_engine, inspect, text
from sqlalchemy.orm import sessionmaker

from fastapi import HTTPException

from app.api.research import (
    delete_run_feedback,
    get_research_run,
    get_routing_analytics,
    list_research_runs,
    update_run_feedback,
)
from app.db.database import Base
from app.db.models import AgentRun, Conversation, ToolExecution
from app.services.goal_runtime import GoalRuntime
from app.schemas.research import RunFeedbackUpdate


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
            route_tier_preference="expert",
            agent_profile="expert_supervisor",
            route_tier="expert",
            route_name="supervisor",
            route_score=6,
            route_reasons_json='["complex_intent"]',
            route_decision_source="model",
            route_confidence=0.86,
            route_classifier_model="fast-model",
            route_classifier_original_tokens=2400,
            route_classifier_compressed_tokens=1200,
            route_classifier_calls=2,
            route_requires_decomposition=True,
            route_max_children=4,
            route_max_depth=2,
            model_provider="ollama",
            model_name="expert-model",
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
        primary, _ = runtime.create_child(
            parent=root,
            title="primary",
            kind="agent",
            agent_profile="expert_supervisor",
            input_data={},
            tool_call_budget=10,
            model_provider="ollama",
            model_name="expert-model",
        )
        worker, _ = runtime.create_child(
            parent=primary,
            title="worker",
            kind="agent",
            agent_profile="web_researcher",
            input_data={"planning_source": "model"},
            tool_call_budget=7,
            model_provider="ollama",
            model_name="standard-model",
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
        runtime.transition(primary, "completed")
        runtime.transition(root, "completed")
        runtime.record_runtime_event(
            "context_compressed",
            {
                "scope": "agent_messages",
                "original_tokens": 10000,
                "compressed_tokens": 2500,
                "calls": 4,
                "protected_anchors": 3,
                "anchor_retries": 1,
            },
            node_id=primary.id,
        )
        runtime.record_runtime_event(
            "context_compression_failed",
            {
                "scope": "conversation_memory",
                "message": "provider unavailable",
            },
            node_id=primary.id,
        )
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
        self.assertEqual(source_summary["metrics"]["agent_count"], 2)
        self.assertEqual(source_summary["metrics"]["tool_calls_used"], 1)
        self.assertEqual(source_summary["metrics"]["tool_call_budget"], 17)
        self.assertEqual(source_summary["metrics"]["progress_percent"], 100)
        self.assertEqual(source_summary["metrics"]["goals_pending"], 0)
        self.assertEqual(source_summary["metrics"]["goal_retry_attempts"], 0)
        self.assertEqual(source_summary["metrics"]["context_compressions"], 1)
        self.assertEqual(source_summary["metrics"]["context_compression_failures"], 1)
        self.assertEqual(source_summary["metrics"]["context_compression_calls"], 4)
        self.assertEqual(source_summary["metrics"]["context_protected_anchors"], 3)
        self.assertEqual(source_summary["metrics"]["context_anchor_retries"], 1)
        self.assertEqual(source_summary["metrics"]["context_tokens_saved"], 7500)
        self.assertEqual(source_summary["metrics"]["context_compression_ratio"], 75.0)
        self.assertEqual(source_summary["routing"]["route"], "supervisor")
        self.assertEqual(source_summary["routing"]["max_children"], 4)
        self.assertEqual(source_summary["routing"]["max_depth"], 2)
        self.assertEqual(source_summary["routing"]["decision_source"], "model")
        self.assertEqual(source_summary["routing"]["confidence"], 0.86)
        self.assertEqual(source_summary["routing"]["classifier_model"], "fast-model")
        self.assertEqual(source_summary["routing"]["classifier_original_tokens"], 2400)
        self.assertEqual(source_summary["routing"]["classifier_compressed_tokens"], 1200)
        self.assertEqual(source_summary["routing"]["classifier_calls"], 2)
        self.assertEqual(source_summary["routing"]["observed_max_children"], 1)
        self.assertEqual(source_summary["routing"]["observed_max_depth"], 1)
        self.assertEqual(source_summary["model_name"], "expert-model")

        detail = await get_research_run(self.run.id, self.db)

        self.assertEqual(detail["retried_by_run_ids"], [self.retry.id])
        self.assertFalse(detail["retryable"])
        self.assertEqual(detail["metrics"]["duration_ms"], 2000)
        self.assertEqual(detail["metrics"]["tool_duration_ms"], 125)
        self.assertEqual(detail["metrics"]["context_original_tokens"], 10000)
        self.assertEqual(detail["metrics"]["context_compressed_tokens"], 2500)
        self.assertEqual(detail["goals"][2]["tool_call_budget"], 7)
        self.assertEqual(detail["goals"][2]["model_name"], "standard-model")
        self.assertEqual(detail["tools"][0]["name"], "web_search")
        self.assertEqual(detail["tools"][0]["arguments"], {"query": "test"})

    async def test_routing_analytics_groups_operational_metrics(self):
        analytics = await get_routing_analytics(None, 200, self.db)
        summary = analytics["summary"]

        self.assertEqual(summary["run_count"], 2)
        self.assertEqual(summary["terminal_run_count"], 2)
        self.assertEqual(summary["completed_run_count"], 1)
        self.assertEqual(summary["failed_run_count"], 1)
        self.assertEqual(summary["operational_success_rate"], 50.0)
        self.assertEqual(summary["average_duration_ms"], 2000)
        self.assertEqual(summary["retry_run_count"], 1)
        self.assertEqual(summary["manual_override_count"], 1)
        self.assertEqual(summary["tool_call_count"], 1)
        self.assertEqual(summary["tool_budget_utilization"], 5.9)
        self.assertEqual(summary["tier_counts"], {
            "fast": 0,
            "standard": 1,
            "expert": 1,
        })
        self.assertEqual(summary["decision_source_counts"], {
            "heuristic": 1,
            "model": 1,
        })
        self.assertEqual(summary["average_route_confidence"], 0.93)
        self.assertEqual(summary["classifier_call_count"], 2)
        self.assertEqual(summary["model_routed_run_count"], 1)
        self.assertEqual(summary["classifier_fallback_count"], 0)
        expert = next(group for group in analytics["groups"] if group["tier"] == "expert")
        self.assertEqual(expert["route"], "supervisor")
        self.assertEqual(expert["planning_source"], "model")
        self.assertEqual(expert["operational_success_rate"], 100.0)
        self.assertFalse(analytics["recommendation_report"]["readiness"]["operational_ready"])
        self.assertEqual(analytics["recommendation_report"]["items"], [])

    async def test_feedback_lifecycle_updates_run_and_routing_quality(self):
        positive = await update_run_feedback(
            self.run.id,
            RunFeedbackUpdate(rating="positive"),
            self.db,
        )
        self.assertEqual(positive["rating"], "positive")
        self.assertIsNone(positive["reason"])

        negative = await update_run_feedback(
            self.run.id,
            RunFeedbackUpdate(rating="negative", reason="missing_evidence"),
            self.db,
        )
        self.assertEqual(negative["reason"], "missing_evidence")

        detail = await get_research_run(self.run.id, self.db)
        listed = await list_research_runs(self.conversation.id, 20, self.db)
        analytics = await get_routing_analytics(None, 200, self.db)
        self.assertEqual(detail["feedback"]["rating"], "negative")
        self.assertEqual(listed["runs"][1]["feedback"]["reason"], "missing_evidence")
        self.assertEqual(analytics["summary"]["rated_run_count"], 1)
        self.assertEqual(analytics["summary"]["user_satisfaction_rate"], 0.0)
        self.assertEqual(
            analytics["summary"]["negative_reason_counts"],
            {"missing_evidence": 1},
        )

        removed = await delete_run_feedback(self.run.id, self.db)
        self.assertEqual(removed, {"status": "removed"})
        self.assertIsNone((await get_research_run(self.run.id, self.db))["feedback"])

        with self.assertRaises(HTTPException) as context:
            await update_run_feedback(
                self.retry.id,
                RunFeedbackUpdate(rating="positive"),
                self.db,
            )
        self.assertEqual(context.exception.status_code, 409)


class ModelRoutingMigrationTests(unittest.TestCase):
    def test_model_routing_migration_backfills_runs_and_goals(self):
        engine = create_engine("sqlite:///:memory:")
        migration_path = (
            Path(__file__).parents[1]
            / "alembic"
            / "versions"
            / "20260815_04_agent_model_routing.py"
        )
        spec = importlib.util.spec_from_file_location("model_routing_migration", migration_path)
        assert spec and spec.loader
        migration = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(migration)

        with engine.begin() as connection:
            connection.execute(text(
                "CREATE TABLE conversations (id VARCHAR(36) PRIMARY KEY, "
                "model_provider VARCHAR(32), model_name VARCHAR(256))"
            ))
            connection.execute(text(
                "CREATE TABLE agent_runs (id VARCHAR(36) PRIMARY KEY, "
                "conversation_id VARCHAR(36))"
            ))
            connection.execute(text(
                "CREATE TABLE goal_nodes (id VARCHAR(36) PRIMARY KEY, run_id VARCHAR(36))"
            ))
            connection.execute(text(
                "INSERT INTO conversations VALUES ('conversation', 'ollama', 'legacy-model')"
            ))
            connection.execute(text(
                "INSERT INTO agent_runs VALUES ('run', 'conversation')"
            ))
            connection.execute(text(
                "INSERT INTO goal_nodes VALUES ('goal', 'run')"
            ))
            migration.op = Operations(MigrationContext.configure(connection))
            migration.upgrade()
            migration.upgrade()

            run_model = connection.execute(text(
                "SELECT model_provider, model_name FROM agent_runs WHERE id = 'run'"
            )).one()
            goal_model = connection.execute(text(
                "SELECT model_provider, model_name FROM goal_nodes WHERE id = 'goal'"
            )).one()
            self.assertEqual(tuple(run_model), ("ollama", "legacy-model"))
            self.assertEqual(tuple(goal_model), ("ollama", "legacy-model"))
            self.assertIn(
                "model_name",
                {column["name"] for column in inspect(connection).get_columns("goal_nodes")},
            )
        engine.dispose()


class AgentTierPreferenceMigrationTests(unittest.TestCase):
    def test_tier_preference_migration_defaults_legacy_runs_to_auto(self):
        engine = create_engine("sqlite:///:memory:")
        migration_path = (
            Path(__file__).parents[1]
            / "alembic"
            / "versions"
            / "20260815_05_agent_tier_preference.py"
        )
        spec = importlib.util.spec_from_file_location("tier_preference_migration", migration_path)
        assert spec and spec.loader
        migration = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(migration)

        with engine.begin() as connection:
            connection.execute(text(
                "CREATE TABLE agent_runs (id VARCHAR(36) PRIMARY KEY)"
            ))
            connection.execute(text("INSERT INTO agent_runs VALUES ('legacy-run')"))
            migration.op = Operations(MigrationContext.configure(connection))
            migration.upgrade()
            migration.upgrade()

            preference = connection.execute(text(
                "SELECT route_tier_preference FROM agent_runs WHERE id = 'legacy-run'"
            )).scalar_one()
            self.assertEqual(preference, "auto")
        engine.dispose()


class RouteHierarchyLimitMigrationTests(unittest.TestCase):
    def test_route_limits_migration_backfills_each_legacy_tier(self):
        engine = create_engine("sqlite:///:memory:")
        migration_path = (
            Path(__file__).parents[1]
            / "alembic"
            / "versions"
            / "20260815_06_route_hierarchy_limits.py"
        )
        spec = importlib.util.spec_from_file_location("route_limit_migration", migration_path)
        assert spec and spec.loader
        migration = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(migration)

        with engine.begin() as connection:
            connection.execute(text(
                "CREATE TABLE agent_runs (id VARCHAR(36) PRIMARY KEY, route_tier VARCHAR(16))"
            ))
            connection.execute(text(
                "INSERT INTO agent_runs VALUES "
                "('fast-run', 'fast'), ('standard-run', 'standard'), ('expert-run', 'expert')"
            ))
            migration.op = Operations(MigrationContext.configure(connection))
            migration.upgrade()
            migration.upgrade()

            limits = connection.execute(text(
                "SELECT route_tier, route_max_children, route_max_depth "
                "FROM agent_runs ORDER BY route_tier"
            )).all()
            self.assertEqual(limits, [
                ("expert", 4, 2),
                ("fast", 0, 0),
                ("standard", 1, 1),
            ])
        engine.dispose()


class AgentRunFeedbackMigrationTests(unittest.TestCase):
    def test_feedback_migration_is_idempotent(self):
        engine = create_engine("sqlite:///:memory:")
        migration_path = (
            Path(__file__).parents[1]
            / "alembic"
            / "versions"
            / "20260815_07_agent_run_feedback.py"
        )
        spec = importlib.util.spec_from_file_location("feedback_migration", migration_path)
        assert spec and spec.loader
        migration = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(migration)

        with engine.begin() as connection:
            connection.execute(text(
                "CREATE TABLE agent_runs (id VARCHAR(36) PRIMARY KEY)"
            ))
            connection.execute(text("INSERT INTO agent_runs VALUES ('run')"))
            migration.op = Operations(MigrationContext.configure(connection))
            migration.upgrade()
            migration.upgrade()
            connection.execute(text(
                "INSERT INTO agent_run_feedback (run_id, rating, reason) "
                "VALUES ('run', 'negative', 'incorrect')"
            ))

            feedback = connection.execute(text(
                "SELECT rating, reason FROM agent_run_feedback WHERE run_id = 'run'"
            )).one()
            self.assertEqual(tuple(feedback), ("negative", "incorrect"))
            self.assertEqual(
                {column["name"] for column in inspect(connection).get_columns("agent_run_feedback")},
                {"run_id", "rating", "reason", "created_at", "updated_at"},
            )
        engine.dispose()


class RouteClassifierEvidenceMigrationTests(unittest.TestCase):
    def test_classifier_evidence_migration_backfills_and_is_idempotent(self):
        engine = create_engine("sqlite:///:memory:")
        migration_path = (
            Path(__file__).parents[1]
            / "alembic"
            / "versions"
            / "20260815_10_route_classifier_evidence.py"
        )
        spec = importlib.util.spec_from_file_location(
            "route_classifier_evidence_migration", migration_path
        )
        assert spec and spec.loader
        migration = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(migration)

        with engine.begin() as connection:
            connection.execute(text(
                "CREATE TABLE agent_runs ("
                "id VARCHAR(36) PRIMARY KEY, route_tier_preference VARCHAR(16))"
            ))
            connection.execute(text(
                "INSERT INTO agent_runs VALUES "
                "('auto-run', 'auto'), ('manual-run', 'expert')"
            ))
            migration.op = Operations(MigrationContext.configure(connection))
            migration.upgrade()
            migration.upgrade()

            evidence = connection.execute(text(
                "SELECT id, route_decision_source, route_confidence, "
                "route_classifier_model, route_classifier_original_tokens, "
                "route_classifier_compressed_tokens, route_classifier_calls "
                "FROM agent_runs ORDER BY id"
            )).all()
            self.assertEqual(evidence, [
                ("auto-run", "heuristic", 1.0, "", 0, 0, 0),
                ("manual-run", "manual", 1.0, "", 0, 0, 0),
            ])
            column_names = {
                column["name"]
                for column in inspect(connection).get_columns("agent_runs")
            }
            self.assertTrue({name for name, _, _ in migration._COLUMNS} <= column_names)
        engine.dispose()
