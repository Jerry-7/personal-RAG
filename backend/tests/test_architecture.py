import tempfile
import unittest
from pathlib import Path

from app.agent.context import AgentRunContext
from app.agent.tools import ToolRegistry
from app.config import settings
from app.db.vector_store import VectorStore
from app.services.event_bus import EventBus
from app.services.runtime_settings import embedding_signature, flatten_updates
from app.services.retriever import Retriever


class AgentContextTests(unittest.IsolatedAsyncioTestCase):
    async def test_tool_registry_passes_explicit_context(self):
        registry = ToolRegistry()
        received = None

        async def handler(query: str, *, context: AgentRunContext) -> str:
            nonlocal received
            received = context
            return query

        registry.register("search", "search", {"type": "object"}, handler)
        context = AgentRunContext(db=object(), conversation_id="conversation")  # type: ignore[arg-type]
        result = await registry.execute("search", {"query": "term"}, context=context)

        self.assertEqual(result, "term")
        self.assertIs(received, context)


class ArchitectureTests(unittest.TestCase):
    def test_flatten_updates_uses_canonical_keys(self):
        self.assertEqual(flatten_updates({
            "llm_provider": "openai",
            "ollama": {"base_url": "http://ollama", "llm_model": "qwen"},
            "rag": {"chunk_size": 512, "chunk_overlap": 64},
            "unknown": "ignored",
        }), {
            "llm_provider": "openai",
            "ollama_base_url": "http://ollama",
            "ollama_llm_model": "qwen",
            "chunk_size": 512,
            "chunk_overlap": 64,
        })

    def test_embedding_signature_selects_provider_model(self):
        self.assertEqual(
            embedding_signature({
                "embedding_provider": "openai",
                "openai_embedding_model": "embedding-v2",
            }),
            ("openai", "embedding-v2"),
        )

    def test_event_bus_broadcasts_to_each_subscriber(self):
        bus = EventBus()
        first = bus.subscribe("doc")
        second = bus.subscribe("doc")
        bus.publish("doc", {"event": "progress"})

        self.assertEqual(first.get_nowait(), {"event": "progress"})
        self.assertEqual(second.get_nowait(), {"event": "progress"})
        bus.unsubscribe("doc", first)
        self.assertEqual(bus.active_count, 1)

    def test_reciprocal_rank_fusion_combines_recall_sources(self):
        ordered, scores = Retriever._reciprocal_rank_fusion(
            ["semantic", "both"],
            ["exact", "both"],
        )
        self.assertEqual(ordered[0], "both")
        self.assertGreater(scores["both"], scores["semantic"])

    def test_fts_query_generates_chinese_trigrams(self):
        query = Retriever._build_fts_query("项目架构优化")
        self.assertIn('"项目架"', query)
        self.assertIn('"构优化"', query)

    def test_vector_store_deletes_exact_chunk_ids(self):
        original_data_dir = settings.data_dir
        with tempfile.TemporaryDirectory() as directory:
            settings.data_dir = Path(directory)
            try:
                store = VectorStore()
                store.add_chunks(
                    chunk_ids=["chunk-a", "chunk-b"],
                    texts=["a", "b"],
                    embeddings=[[1.0, 0.0], [0.0, 1.0]],
                    metadatas=[{}, {}],
                )

                self.assertEqual(store.delete_chunks(["chunk-a"]), 1)
                self.assertEqual(store.chunk_ids(), {"chunk-b"})
                self.assertEqual(store.count(), 1)
            finally:
                settings.data_dir = original_data_dir
