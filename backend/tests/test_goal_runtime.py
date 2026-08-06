import unittest

from sqlalchemy import create_engine
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
        )

        self.assertEqual(child.parent_id, root.id)
        self.assertEqual(child.status, "running")
        self.assertEqual([event.sequence for event in events], [3, 4])
