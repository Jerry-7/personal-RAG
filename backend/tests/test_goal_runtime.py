import importlib.util
import unittest
from pathlib import Path

from alembic.migration import MigrationContext
from alembic.operations import Operations
from sqlalchemy import create_engine, inspect, text
from sqlalchemy.orm import sessionmaker

from app.db.database import Base
from app.services.goal_runtime import GoalRuntime, serialize_event, serialize_goal


class GoalRuntimeTests(unittest.TestCase):
    def setUp(self):
        self.engine = create_engine("sqlite:///:memory:")
        Base.metadata.create_all(self.engine)
        self.db = sessionmaker(bind=self.engine)()

    def tearDown(self):
        self.db.close()
        self.engine.dispose()

    def test_root_lifecycle_records_ordered_events(self):
        runtime = GoalRuntime(self.db, "run-1")
        goal, initial_events = runtime.create_root(
            title="研究个人知识库",
            agent_profile="expert_supervisor",
            input_data={"mode": "auto"},
        )

        self.assertEqual(goal.status, "running")
        self.assertEqual([event.sequence for event in initial_events], [1, 2])
        self.assertEqual(initial_events[0].event_type, "goal_created")
        self.assertEqual(initial_events[1].event_type, "goal_running")

        completed = runtime.transition(goal, "completed", output={"message_id": "msg-1"})
        self.assertEqual(completed.sequence, 3)
        self.assertEqual(goal.status, "completed")
        self.assertEqual(serialize_goal(goal)["status"], "completed")
        self.assertEqual(serialize_event(completed)["payload"]["goal"]["id"], goal.id)

    def test_terminal_goal_cannot_transition_again(self):
        runtime = GoalRuntime(self.db, "run-2")
        goal, _ = runtime.create_root(
            title="直接回答",
            agent_profile="fast_general",
            input_data={},
        )
        runtime.transition(goal, "cancelled")
        with self.assertRaises(ValueError):
            runtime.transition(goal, "running")

    def test_runtime_telemetry_shares_the_ordered_event_stream(self):
        runtime = GoalRuntime(self.db, "run-telemetry")
        goal, _ = runtime.create_root(
            title="压缩上下文",
            agent_profile="standard_research",
            input_data={},
        )

        event = runtime.record_runtime_event(
            "context_compressed",
            {
                "scope": "agent_messages",
                "original_tokens": 8000,
                "compressed_tokens": 2000,
            },
            node_id=goal.id,
        )

        serialized = serialize_event(event)
        self.assertEqual(serialized["sequence"], 3)
        self.assertEqual(serialized["node_id"], goal.id)
        self.assertEqual(serialized["payload"]["compressed_tokens"], 2000)

    def test_child_goal_is_ordered_under_root(self):
        runtime = GoalRuntime(self.db, "run-3")
        root, _ = runtime.create_root(
            title="复杂任务",
            agent_profile="expert_supervisor",
            input_data={},
        )
        child, events = runtime.create_child(
            parent=root,
            title="执行研究",
            kind="agent",
            agent_profile="standard_research",
            input_data={"route": "tool_agent"},
            tool_call_budget=5,
        )

        self.assertEqual(child.parent_id, root.id)
        self.assertEqual(child.status, "running")
        self.assertEqual(serialize_goal(child)["tool_call_budget"], 5)
        self.assertEqual([event.sequence for event in events], [3, 4])
        with self.assertRaises(ValueError):
            runtime.create_child(
                parent=root,
                title="非法目标",
                kind="agent",
                agent_profile="standard_research",
                input_data={},
                max_attempts=0,
            )

    def test_retry_increments_attempt_without_leaving_running_state(self):
        runtime = GoalRuntime(self.db, "run-retry")
        root, _ = runtime.create_root(
            title="复杂任务",
            agent_profile="expert_supervisor",
            input_data={},
        )
        child, _ = runtime.create_child(
            parent=root,
            title="检索本地知识",
            kind="agent",
            agent_profile="local_retriever",
            input_data={},
            max_attempts=2,
        )

        event = runtime.retry(child, "temporary failure")

        self.assertEqual(child.status, "running")
        self.assertEqual(child.attempt, 2)
        self.assertEqual(child.max_attempts, 2)
        self.assertEqual(event.event_type, "goal_retrying")
        payload = serialize_event(event)["payload"]
        self.assertEqual(payload["goal"]["attempt"], 2)
        self.assertEqual(payload["previous_error"], "temporary failure")
        with self.assertRaises(ValueError):
            runtime.retry(child, "another failure")

    def test_retry_migration_upgrades_legacy_goal_table(self):
        engine = create_engine("sqlite:///:memory:")
        migration_path = (
            Path(__file__).parents[1]
            / "alembic"
            / "versions"
            / "20260815_01_goal_retries.py"
        )
        spec = importlib.util.spec_from_file_location("goal_retry_migration", migration_path)
        assert spec and spec.loader
        migration = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(migration)

        with engine.begin() as connection:
            connection.execute(text(
                "CREATE TABLE goal_nodes (id VARCHAR(36) PRIMARY KEY)"
            ))
            migration.op = Operations(MigrationContext.configure(connection))
            migration.upgrade()
            migration.upgrade()
            columns = {column["name"] for column in inspect(connection).get_columns("goal_nodes")}
            self.assertIn("attempt", columns)
            self.assertIn("max_attempts", columns)
            connection.execute(text("INSERT INTO goal_nodes (id) VALUES ('goal')"))
            row = connection.execute(text(
                "SELECT attempt, max_attempts FROM goal_nodes WHERE id = 'goal'"
            )).one()
            self.assertEqual(tuple(row), (1, 1))
        engine.dispose()

    def test_tool_budget_migration_upgrades_legacy_goal_table(self):
        engine = create_engine("sqlite:///:memory:")
        migration_path = (
            Path(__file__).parents[1]
            / "alembic"
            / "versions"
            / "20260815_03_goal_tool_budgets.py"
        )
        spec = importlib.util.spec_from_file_location("goal_budget_migration", migration_path)
        assert spec and spec.loader
        migration = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(migration)

        with engine.begin() as connection:
            connection.execute(text(
                "CREATE TABLE goal_nodes ("
                "id VARCHAR(36) PRIMARY KEY, kind VARCHAR(32), agent_profile VARCHAR(64))"
            ))
            connection.execute(text(
                "INSERT INTO goal_nodes (id, kind, agent_profile) "
                "VALUES ('goal', 'agent', 'web_researcher')"
            ))
            migration.op = Operations(MigrationContext.configure(connection))
            migration.upgrade()
            migration.upgrade()
            columns = {column["name"] for column in inspect(connection).get_columns("goal_nodes")}
            self.assertIn("tool_call_budget", columns)
            budget = connection.execute(text(
                "SELECT tool_call_budget FROM goal_nodes WHERE id = 'goal'"
            )).scalar_one()
            self.assertEqual(budget, 6)
        engine.dispose()
