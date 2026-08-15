import asyncio
import importlib.util
import json
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import AsyncMock, patch

from alembic.migration import MigrationContext
from alembic.operations import Operations
from sqlalchemy import create_engine, inspect, text
from sqlalchemy.orm import sessionmaker

from app.db.database import Base
from app.db.models import AgentRun, Conversation, GoalNode, Message, RunEvent
from app.config import settings
from app.providers.base import AgentResponse
from app.services.conversation_memory import conversation_memory
from app.services.goal_runtime import GoalRuntime
from app.services.run_recovery import (
    INTERRUPTED_MESSAGE,
    recover_interrupted_agent_runs,
    resolve_retry_source,
)


class RunRecoveryTests(unittest.TestCase):
    def setUp(self):
        self.engine = create_engine("sqlite:///:memory:")
        Base.metadata.create_all(self.engine)
        self.db = sessionmaker(bind=self.engine)()
        self.conversation = Conversation(
            id="conversation",
            title="Recovery",
            model_provider="ollama",
            model_name="model",
            embedding_provider="ollama",
            embedding_model="embedding",
        )
        self.db.add(self.conversation)
        self.db.commit()

    def tearDown(self):
        self.db.close()
        self.engine.dispose()

    def _message(
        self,
        message_id: str,
        role: str,
        content: str,
        created_at: datetime,
    ) -> Message:
        message = Message(
            id=message_id,
            conversation_id=self.conversation.id,
            role=role,
            content=content,
            created_at=created_at,
        )
        self.db.add(message)
        return message

    def _run(
        self,
        run_id: str,
        user_message_id: str,
        status: str,
        mode: str = "web",
    ) -> AgentRun:
        run = AgentRun(
            id=run_id,
            conversation_id=self.conversation.id,
            user_message_id=user_message_id,
            mode=mode,
            status=status,
        )
        self.db.add(run)
        self.db.commit()
        return run

    def test_retry_reuses_original_message_and_excludes_later_output(self):
        started = datetime(2026, 8, 15, tzinfo=timezone.utc)
        self._message("prior", "assistant", "prior context", started)
        original = self._message(
            "original", "user", "original question", started + timedelta(seconds=1)
        )
        self._message(
            "partial", "assistant", "partial failed output", started + timedelta(seconds=2)
        )
        self.db.commit()
        source_run = self._run("failed-run", original.id, "failed")
        source_run.route_tier_preference = "expert"
        self.db.commit()

        source = resolve_retry_source(self.db, source_run.id)
        context = conversation_memory.get_context_before(
            self.db,
            self.conversation.id,
            source.user_message,
        )

        self.assertEqual(source.user_message.content, "original question")
        self.assertEqual(source.run.mode, "web")
        self.assertEqual(source.run.route_tier_preference, "expert")
        self.assertEqual(context, [{"role": "assistant", "content": "prior context"}])

    def test_active_retry_blocks_duplicate_replay(self):
        now = datetime.now(timezone.utc)
        message = self._message("question", "user", "question", now)
        self.db.commit()
        source = self._run("source", message.id, "failed")
        active_retry = self._run("active-retry", message.id, "running")
        active_retry.retry_of_run_id = source.id
        self.db.commit()

        with self.assertRaisesRegex(ValueError, "已有正在执行的运行"):
            resolve_retry_source(self.db, source.id)

    def test_startup_reconciles_running_run_and_goals(self):
        message = self._message(
            "question", "user", "question", datetime.now(timezone.utc)
        )
        self.db.commit()
        run = self._run("interrupted-run", message.id, "running")
        paused_run = self._run("paused-run", message.id, "paused")
        runtime = GoalRuntime(self.db, run.id)
        root, _ = runtime.create_root(
            title="question",
            agent_profile="expert_supervisor",
            input_data={},
        )
        child, _ = runtime.create_child(
            parent=root,
            title="worker",
            kind="agent",
            agent_profile="local_retriever",
            input_data={},
        )

        recovered = recover_interrupted_agent_runs(self.db)

        self.db.refresh(run)
        self.db.refresh(root)
        self.db.refresh(child)
        self.db.refresh(paused_run)
        self.assertEqual(recovered, 2)
        self.assertEqual(run.status, "interrupted")
        self.assertEqual(paused_run.status, "interrupted")
        self.assertEqual(run.error_message, INTERRUPTED_MESSAGE)
        self.assertIsNotNone(run.completed_at)
        self.assertEqual(root.status, "failed")
        self.assertEqual(child.status, "failed")
        failed_events = self.db.query(RunEvent).filter(
            RunEvent.run_id == run.id,
            RunEvent.event_type == "goal_failed",
        ).all()
        self.assertEqual(len(failed_events), 2)
        self.assertEqual(recover_interrupted_agent_runs(self.db), 0)

    def test_paused_run_blocks_duplicate_replay(self):
        message = self._message(
            "paused-question", "user", "question", datetime.now(timezone.utc)
        )
        self.db.commit()
        source = self._run("paused-source", message.id, "failed")
        self._run("paused-active", message.id, "paused")

        with self.assertRaises(ValueError):
            resolve_retry_source(self.db, source.id)

    def test_retry_link_migration_upgrades_legacy_agent_runs(self):
        engine = create_engine("sqlite:///:memory:")
        migration_path = (
            Path(__file__).parents[1]
            / "alembic"
            / "versions"
            / "20260815_02_run_recovery.py"
        )
        spec = importlib.util.spec_from_file_location("run_recovery_migration", migration_path)
        assert spec and spec.loader
        migration = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(migration)

        with engine.begin() as connection:
            connection.execute(text(
                "CREATE TABLE agent_runs (id VARCHAR(36) PRIMARY KEY)"
            ))
            migration.op = Operations(MigrationContext.configure(connection))
            migration.upgrade()
            migration.upgrade()
            columns = {
                column["name"]
                for column in inspect(connection).get_columns("agent_runs")
            }
            self.assertIn("retry_of_run_id", columns)
            connection.execute(text("INSERT INTO agent_runs (id) VALUES ('source')"))
            connection.execute(text(
                "INSERT INTO agent_runs (id, retry_of_run_id) VALUES ('retry', 'source')"
            ))
            linked = connection.execute(text(
                "SELECT retry_of_run_id FROM agent_runs WHERE id = 'retry'"
            )).scalar_one()
            self.assertEqual(linked, "source")
        engine.dispose()


class RunControlTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.engine = create_engine("sqlite:///:memory:")
        Base.metadata.create_all(self.engine)
        self.db = sessionmaker(bind=self.engine)()
        self.conversation = Conversation(
            id="controlled-conversation",
            title="Control",
            model_provider="ollama",
            model_name="model",
            embedding_provider="ollama",
            embedding_model="embedding",
        )
        self.run = AgentRun(
            id="controlled-run",
            conversation_id=self.conversation.id,
            mode="auto",
            status="running",
        )
        self.db.add_all([self.conversation, self.run])
        self.db.commit()

    def tearDown(self):
        from app.api.chat import _cancellation_flags, _pause_flags

        _cancellation_flags.clear()
        _pause_flags.clear()
        self.db.close()
        self.engine.dispose()

    async def test_pause_resume_and_cancel_update_cooperative_events(self):
        from app.api.chat import (
            _cancellation_flags,
            _pause_flags,
            cancel_chat,
            pause_chat,
            resume_chat,
        )

        class JsonRequest:
            def __init__(self, conversation_id: str):
                self.conversation_id = conversation_id

            async def json(self):
                return {"conversation_id": self.conversation_id}

        request = JsonRequest(self.conversation.id)
        cancellation_event = asyncio.Event()
        pause_event = asyncio.Event()
        pause_event.set()
        _cancellation_flags[self.conversation.id] = cancellation_event
        _pause_flags[self.conversation.id] = pause_event

        paused = await pause_chat(request, self.db)
        self.db.refresh(self.run)
        self.assertEqual(paused["status"], "paused")
        self.assertEqual(self.run.status, "paused")
        self.assertFalse(pause_event.is_set())

        resumed = await resume_chat(request, self.db)
        self.db.refresh(self.run)
        self.assertEqual(resumed["status"], "running")
        self.assertEqual(self.run.status, "running")
        self.assertTrue(pause_event.is_set())

        pause_event.clear()
        cancelled = await cancel_chat(request)
        self.assertEqual(cancelled["status"], "cancelled")
        self.assertTrue(pause_event.is_set())
        self.assertTrue(cancellation_event.is_set())


class RunReplayGeneratorTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.engine = create_engine("sqlite:///:memory:")
        Base.metadata.create_all(self.engine)
        self.db = sessionmaker(bind=self.engine)()
        self.conversation = Conversation(
            id="conversation-replay",
            title="Replay",
            model_provider="ollama",
            model_name="model",
            embedding_provider="ollama",
            embedding_model="embedding",
        )
        self.user_message = Message(
            id="original-question",
            conversation_id=self.conversation.id,
            role="user",
            content="simple retry question",
        )
        self.source_run = AgentRun(
            id="source-run",
            conversation_id=self.conversation.id,
            user_message_id=self.user_message.id,
            mode="auto",
            route_tier_preference="fast",
            status="failed",
        )
        self.db.add_all([self.conversation, self.user_message, self.source_run])
        self.db.commit()

    def tearDown(self):
        self.db.close()
        self.engine.dispose()

    async def test_replay_generator_links_new_run_without_duplicate_user_message(self):
        from app.api.chat import _agent_event_generator
        from app.services.generator import generator

        class Provider:
            model = None

            async def chat_with_tools(self, **kwargs):
                self.model = kwargs.get("model")
                return AgentResponse(content="replayed answer")

        provider = Provider()
        with (
            patch.object(
                generator,
                "_get_provider",
                new=AsyncMock(return_value=provider),
            ),
            patch.object(settings, "agent_fast_model", "fast-replay-model"),
        ):
            events = [
                event
                async for event in _agent_event_generator(
                    self.user_message.content,
                    self.conversation.id,
                    self.db,
                    self.conversation,
                    [],
                    "auto",
                    self.user_message.id,
                    tier_preference=self.source_run.route_tier_preference,
                    retry_of_run_id=self.source_run.id,
                )
            ]

        retried_run = self.db.query(AgentRun).filter(
            AgentRun.retry_of_run_id == self.source_run.id
        ).one()
        user_messages = self.db.query(Message).filter(
            Message.conversation_id == self.conversation.id,
            Message.role == "user",
        ).all()
        self.assertEqual(retried_run.status, "completed")
        self.assertEqual(retried_run.user_message_id, self.user_message.id)
        self.assertEqual(retried_run.model_name, "fast-replay-model")
        self.assertEqual(retried_run.route_tier_preference, "fast")
        self.assertEqual(provider.model, "fast-replay-model")
        self.assertEqual(len(user_messages), 1)
        self.assertTrue(any(event["event"] == "done" for event in events))
        run_started = next(event for event in events if event["event"] == "run_started")
        self.assertEqual(
            json.loads(run_started["data"])["retry_of_run_id"],
            self.source_run.id,
        )
