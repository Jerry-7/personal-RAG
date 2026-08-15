import asyncio
import json
import importlib.util
from pathlib import Path
import unittest
from unittest.mock import AsyncMock, patch

from sqlalchemy import create_engine
from sqlalchemy import inspect, text
from alembic.migration import MigrationContext
from alembic.operations import Operations
from sqlalchemy.orm import sessionmaker

from app.agent.context import AgentRunContext
from app.agent.input_processor import AgentInputProcessor, UserInputPlan
from app.agent.loop import AgentLoop
from app.agent.tools import ToolRegistry
from app.db.database import Base
from app.db.models import Conversation, Message, WebSnapshot
from app.providers.base import AgentResponse, LLMResponse
from app.providers.ollama import OllamaLLMProvider
from app.services.notes import note_service
from app.services.web_fetcher import FetchedPage, WebFetcher
from app.services.web_research import WebResearchService
from app.services.web_search import SearXNGProvider


async def _collect_events(stream):
    return [event async for event in stream]


class WebSafetyTests(unittest.IsolatedAsyncioTestCase):
    def test_url_canonicalization(self):
        self.assertEqual(
            WebFetcher.canonicalize("HTTPS://Example.COM:443/a?q=1#fragment"),
            "https://example.com/a?q=1",
        )
        with self.assertRaises(ValueError):
            WebFetcher.canonicalize("https://user:secret@example.com/")
        with self.assertRaises(ValueError):
            WebFetcher.canonicalize("file:///etc/passwd")

    async def test_private_and_loopback_addresses_are_rejected(self):
        fetcher = WebFetcher()
        with self.assertRaisesRegex(ValueError, "禁止访问"):
            await fetcher.validate_public_url("http://127.0.0.1/")

    async def test_searxng_json_response_is_parsed(self):
        class Response:
            def raise_for_status(self): pass
            def json(self):
                return {"results": [{"title": "Result", "url": "https://example.com", "content": "Snippet", "engine": "test"}]}

        class Client:
            async def __aenter__(self): return self
            async def __aexit__(self, *args): return None
            async def get(self, *args, **kwargs): return Response()

        with patch("app.services.web_search.httpx.AsyncClient", return_value=Client()):
            results = await SearXNGProvider("http://search").search("query", max_results=1)
        self.assertEqual(results[0].title, "Result")
        self.assertEqual(results[0].snippet, "Snippet")


class ResearchPersistenceTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.engine = create_engine("sqlite:///:memory:")
        Base.metadata.create_all(self.engine)
        self.db = sessionmaker(bind=self.engine)()

    def tearDown(self):
        self.db.close()
        self.engine.dispose()

    async def test_crawl_stops_at_page_budget_and_deduplicates_snapshots(self):
        pages = {
            "https://example.com/": FetchedPage("https://example.com/", "Root", "root research text", "text/html", 200, "hash-root", ["https://example.com/a", "https://outside.example/x"]),
            "https://example.com/a": FetchedPage("https://example.com/a", "A", "child research text", "text/html", 200, "hash-a", ["https://example.com/b"]),
        }

        async def fake_fetch(url, **kwargs):
            return pages[url]

        context = AgentRunContext(db=self.db, conversation_id="conv", web_page_budget=2, max_crawl_depth=2)
        with patch("app.services.web_research.web_fetcher.fetch", new=AsyncMock(side_effect=fake_fetch)):
            results = await WebResearchService().crawl(context, "https://example.com", "research")
        self.assertEqual(len(results), 2)
        self.assertEqual(context.web_pages_used, 2)
        self.assertEqual(self.db.query(WebSnapshot).count(), 2)

        context.visited_urls.clear()
        context.web_pages_used = 0
        with patch("app.services.web_research.web_fetcher.fetch", new=AsyncMock(return_value=pages["https://example.com/"])):
            await WebResearchService().fetch_and_store(context, "https://example.com", "research")
        self.assertEqual(self.db.query(WebSnapshot).count(), 2)

    def test_note_draft_fixes_message_and_web_sources_then_pins_on_publish(self):
        conversation = Conversation(
            id="conv", title="Research", model_provider="ollama", model_name="model",
            embedding_provider="ollama", embedding_model="embed",
        )
        snapshot = WebSnapshot(
            id="snapshot", canonical_url="https://example.com/", title="Example",
            content="evidence", content_hash="hash", content_type="text/html", http_status=200,
        )
        user = Message(id="user", conversation_id="conv", role="user", content="What happened?")
        assistant = Message(
            id="assistant", conversation_id="conv", role="assistant", content="Answer [1]",
            citations_json=json.dumps([{"index": 1, "source_type": "web", "snapshot_id": "snapshot", "snippet": "evidence"}]),
        )
        self.db.add_all([conversation, snapshot, user, assistant]); self.db.commit()

        note = note_service.create_draft_from_conversation(self.db, "conv")
        serialized = note_service.serialize(self.db, note)
        self.assertEqual(note.status, "draft")
        self.assertTrue(any(source["snapshot_id"] == "snapshot" for source in serialized["sources"]))
        note_service.publish(self.db, note)
        self.assertTrue(self.db.get(WebSnapshot, "snapshot").is_pinned)
        self.assertIsNone(self.db.get(WebSnapshot, "snapshot").expires_at)


class ToolVisibilityTests(unittest.IsolatedAsyncioTestCase):
    def test_web_tools_can_be_filtered_by_source(self):
        registry = ToolRegistry()

        async def handler(): return "ok"
        registry.register("local", "local", {"type": "object"}, handler, source="builtin")
        registry.register("web", "web", {"type": "object"}, handler, source="web")
        names = [item["function"]["name"] for item in registry.to_openai_format(exclude_sources={"web"})]
        self.assertEqual(names, ["local"])

    async def test_local_mode_rejects_direct_web_tool_execution(self):
        registry = ToolRegistry()
        handler = AsyncMock(return_value="should not run")
        registry.register("web", "web", {"type": "object"}, handler, source="web")
        loop = AgentLoop(provider=None, tools=registry)
        context = AgentRunContext(
            db=None,
            conversation_id="conv",
            goal_node_id="goal-local",
            mode="local",
        )

        events = [event async for event in loop._execute_tool("web", {}, 1, context)]

        handler.assert_not_awaited()
        self.assertEqual(events[0]["data"]["node_id"], "goal-local")
        self.assertEqual(events[1]["data"]["node_id"], "goal-local")
        self.assertEqual(events[1]["data"]["status"], "failed")


class AgentInputProcessorTests(unittest.IsolatedAsyncioTestCase):
    async def test_rewrite_resolves_follow_up_and_builds_search_queries(self):
        class Provider:
            async def chat(self, **kwargs):
                return LLMResponse(content=json.dumps({
                    "standalone_question": "修复网络搜索引用索引不连续的问题",
                    "search_queries": ["网络搜索 引用索引 不连续", "citation index mapping"],
                }, ensure_ascii=False))

        plan = await AgentInputProcessor().optimize(
            Provider(),
            "修复这个问题",
            [{"role": "user", "content": "网络搜索的引用索引不连续"}],
        )

        self.assertTrue(plan.rewritten)
        self.assertEqual(plan.original_question, "修复这个问题")
        self.assertEqual(plan.standalone_question, "修复网络搜索引用索引不连续的问题")
        self.assertEqual(plan.primary_search_query, "网络搜索 引用索引 不连续")

    async def test_invalid_rewrite_falls_back_to_normalized_original(self):
        class Provider:
            async def chat(self, **kwargs):
                return LLMResponse(content="not json")

        plan = await AgentInputProcessor().optimize(
            Provider(), "  保留   原意\n\n\n并继续  "
        )

        self.assertFalse(plan.rewritten)
        self.assertEqual(plan.original_question, "保留 原意\n\n并继续")
        self.assertEqual(plan.standalone_question, plan.original_question)


class AgentEmptyResponseTests(unittest.IsolatedAsyncioTestCase):
    async def test_agent_waits_at_pause_boundary_before_model_call(self):
        registry = ToolRegistry()

        async def local_tool():
            return "ok"

        registry.register(
            "local", "local", {"type": "object"}, local_tool, source="builtin"
        )

        class Processor:
            async def optimize(self, provider, question, chat_history):
                return UserInputPlan(
                    original_question=question,
                    standalone_question=question,
                    search_queries=[],
                    rewritten=False,
                )

        class Provider:
            def __init__(self):
                self.called = asyncio.Event()
                self.model = None

            async def chat_with_tools(self, **kwargs):
                self.model = kwargs.get("model")
                self.called.set()
                return AgentResponse(content="answer")

        provider = Provider()
        pause_event = asyncio.Event()
        loop = AgentLoop(
            provider=provider,
            max_iterations=1,
            tools=registry,
            input_processor=Processor(),
            model_name="fast-model",
        )
        context = AgentRunContext(
            db=None,
            conversation_id="conv",
            pause_event=pause_event,
        )

        task = asyncio.create_task(
            _collect_events(loop.run("question", context=context))
        )
        await asyncio.sleep(0)
        self.assertFalse(provider.called.is_set())

        pause_event.set()
        events = await asyncio.wait_for(task, timeout=1)

        self.assertTrue(provider.called.is_set())
        self.assertEqual(provider.model, "fast-model")
        self.assertTrue(any(event["event"] == "token" for event in events))

    async def test_web_mode_uses_rewritten_query_but_keeps_original_request(self):
        registry = ToolRegistry()
        searched_queries = []

        async def web_search(query: str, *, context):
            searched_queries.append(query)
            return "[W1] candidate"

        registry.register(
            "web_search", "search", {"type": "object"}, web_search, source="web"
        )

        class Processor:
            async def optimize(self, provider, question, chat_history):
                return UserInputPlan(
                    original_question=question,
                    standalone_question="standalone request",
                    search_queries=["optimized search query"],
                    rewritten=True,
                )

        class Provider:
            messages = None

            async def chat_with_tools(self, *, messages, **kwargs):
                self.messages = messages
                return AgentResponse(content="answer")

        provider = Provider()
        loop = AgentLoop(
            provider=provider,
            max_iterations=1,
            tools=registry,
            input_processor=Processor(),
        )
        context = AgentRunContext(db=None, conversation_id="conv", mode="web")

        events = [event async for event in loop.run("original request", context=context)]

        self.assertTrue(any(event["event"] == "token" for event in events))
        self.assertEqual(searched_queries, ["optimized search query"])
        self.assertIn(
            "Original user request (authoritative):\noriginal request",
            provider.messages[-1]["content"],
        )
        self.assertIn("Context-resolved request", provider.messages[-1]["content"])
        self.assertIn("[W1]", provider.messages[0]["content"])
        self.assertIn("never citations", provider.messages[0]["content"])

    async def test_web_search_results_stay_in_the_user_message(self):
        registry = ToolRegistry()

        async def web_search(query: str, *, context):
            return f"candidate for {query}"

        registry.register(
            "web_search", "search", {"type": "object"}, web_search, source="web"
        )

        class Provider:
            messages = None

            async def chat_with_tools(self, *, messages, **kwargs):
                self.messages = messages
                return AgentResponse(content="answer")

        provider = Provider()
        loop = AgentLoop(provider=provider, max_iterations=1, tools=registry)
        context = AgentRunContext(db=None, conversation_id="conv", mode="web")

        events = [event async for event in loop.run(
            "question",
            chat_history=[
                {"role": "system", "content": "Earlier conversation summary"},
                {"role": "user", "content": "previous question"},
                {"role": "assistant", "content": "previous answer"},
            ],
            context=context,
        )]

        self.assertTrue(any(event["event"] == "token" for event in events))
        self.assertEqual(
            [index for index, message in enumerate(provider.messages) if message["role"] == "system"],
            [0],
        )
        self.assertIn("Earlier conversation summary", provider.messages[0]["content"])
        self.assertIn("candidate for question", provider.messages[-1]["content"])

    async def test_empty_response_recovery_does_not_append_system_message(self):
        registry = ToolRegistry()

        async def local_tool():
            return "ok"

        registry.register("local", "local", {"type": "object"}, local_tool, source="builtin")

        class Provider:
            recovery_messages = None

            async def chat_with_tools(self, **kwargs):
                return AgentResponse(content="")

            async def chat_stream(self, *, messages, **kwargs):
                self.recovery_messages = messages
                yield "recovered"

        provider = Provider()
        loop = AgentLoop(provider=provider, max_iterations=1, tools=registry)
        context = AgentRunContext(db=None, conversation_id="conv")

        events = [event async for event in loop.run("question", context=context)]

        self.assertTrue(any(event.get("data") == "recovered" for event in events))
        self.assertEqual(
            [index for index, message in enumerate(provider.recovery_messages) if message["role"] == "system"],
            [0],
        )

    async def test_ollama_agent_requests_disable_hidden_thinking(self):
        provider = OllamaLLMProvider(base_url="http://localhost:11434")
        provider._client._request = AsyncMock(return_value={
            "message": {"content": "answer", "tool_calls": []}
        })

        response = await provider.chat_with_tools(
            [
                {"role": "system", "content": "primary"},
                {"role": "user", "content": "question"},
                {"role": "system", "content": "rolling summary"},
            ],
            [{"type": "function", "function": {"name": "search", "parameters": {}}}],
        )

        self.assertEqual(response.content, "answer")
        payload = provider._client._request.await_args.kwargs["json"]
        self.assertIs(payload["think"], False)
        self.assertEqual(
            [index for index, message in enumerate(payload["messages"]) if message["role"] == "system"],
            [0],
        )
        self.assertIn("rolling summary", payload["messages"][0]["content"])


class MigrationTests(unittest.TestCase):
    def test_legacy_document_data_is_backfilled_to_knowledge_sources(self):
        engine = create_engine("sqlite:///:memory:")
        with engine.begin() as connection:
            connection.execute(text("CREATE TABLE conversations (id VARCHAR(36) PRIMARY KEY)"))
            connection.execute(text("CREATE TABLE messages (id VARCHAR(36) PRIMARY KEY, conversation_id VARCHAR(36))"))
            connection.execute(text("CREATE TABLE documents (id VARCHAR(36) PRIMARY KEY, original_name VARCHAR(512), status VARCHAR(20), created_at DATETIME, updated_at DATETIME)"))
            connection.execute(text("CREATE TABLE chunks (id VARCHAR(36) PRIMARY KEY, document_id VARCHAR(36) NOT NULL)"))
            connection.execute(text("CREATE TABLE index_jobs (id VARCHAR(36) PRIMARY KEY, document_id VARCHAR(36) NOT NULL)"))
            connection.execute(text("INSERT INTO documents VALUES ('doc', 'legacy.pdf', 'indexed', CURRENT_TIMESTAMP, CURRENT_TIMESTAMP)"))
            connection.execute(text("INSERT INTO chunks VALUES ('chunk', 'doc')"))
            connection.execute(text("INSERT INTO index_jobs VALUES ('job', 'doc')"))
            migration_path = Path(__file__).parents[1] / "alembic" / "versions" / "20260731_01_research_agent.py"
            spec = importlib.util.spec_from_file_location("research_agent_migration", migration_path)
            assert spec and spec.loader
            migration = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(migration)
            migration.op = Operations(MigrationContext.configure(connection))
            migration.upgrade()

            source = connection.execute(text("SELECT id, kind, title FROM knowledge_sources")).one()
            self.assertEqual(tuple(source), ("doc", "document", "legacy.pdf"))
            self.assertEqual(connection.execute(text("SELECT source_id FROM chunks")).scalar(), "doc")
            self.assertEqual(connection.execute(text("SELECT source_id FROM index_jobs")).scalar(), "doc")
            self.assertIn("source_id", {column["name"] for column in inspect(connection).get_columns("documents")})
        engine.dispose()
