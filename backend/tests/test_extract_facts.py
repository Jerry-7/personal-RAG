"""extract_facts 工具测试: 来源解析 (chunk/URL) + 目标语义提取 + 错误引导."""

import unittest
from unittest.mock import AsyncMock, patch

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.agent.builtin_tools import _extract_facts
from app.agent.context import AgentRunContext
from app.agent.tools import tool_registry
from app.db.database import Base
from app.db.models import Chunk, WebSnapshot
from app.services.context_compression import CompressionStats
from app.services.semantic_extractor import SemanticExtraction


class ExtractFactsTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.engine = create_engine("sqlite:///:memory:")
        Base.metadata.create_all(self.engine)
        self.db = sessionmaker(bind=self.engine)()

    def tearDown(self):
        self.db.close()
        self.engine.dispose()

    def _context(self) -> AgentRunContext:
        return AgentRunContext(db=self.db, conversation_id="conv")

    async def test_extracts_facts_from_chunk_id(self):
        chunk = Chunk(
            id="chunk-1", source_id="src-1", chunk_index=0, text="长正文内容。"
        )
        self.db.add(chunk)
        self.db.commit()

        with patch(
            "app.services.semantic_extractor.semantic_extractor.extract",
            new=AsyncMock(return_value=SemanticExtraction(
                content="目标事实",
                decision="extracted",
                stats=CompressionStats(100, 8, calls=1),
            )),
        ) as mock_extract:
            result = await _extract_facts(
                "chunk-1", "找出关键事实", context=self._context()
            )

        self.assertEqual(result, "目标事实")
        self.assertEqual(mock_extract.await_args.args[0], "长正文内容。")
        self.assertEqual(mock_extract.await_args.kwargs["objective"], "找出关键事实")

    async def test_extracts_facts_from_web_snapshot_url(self):
        snapshot = WebSnapshot(
            id="snap-1", canonical_url="https://example.com/", title="Example",
            content="网页全文内容。", content_hash="h", content_type="text/html",
            http_status=200,
        )
        self.db.add(snapshot)
        self.db.commit()

        with patch(
            "app.services.semantic_extractor.semantic_extractor.extract",
            new=AsyncMock(return_value=SemanticExtraction(
                content="网页事实",
                decision="extracted",
                stats=CompressionStats(80, 6, calls=1),
            )),
        ) as mock_extract:
            result = await _extract_facts(
                "https://example.com/", "总结要点", context=self._context()
            )

        self.assertEqual(result, "网页事实")
        self.assertEqual(mock_extract.await_args.args[0], "网页全文内容。")

    async def test_unknown_source_returns_guidance(self):
        result = await _extract_facts(
            "no-such-id", "目标", context=self._context()
        )

        self.assertIn("无法从 no-such-id 解析到文本", result)
        self.assertIn("fetch_web_page", result)

    async def test_empty_objective_returns_guidance(self):
        chunk = Chunk(
            id="chunk-2", source_id="src-2", chunk_index=0, text="正文内容。"
        )
        self.db.add(chunk)
        self.db.commit()

        result = await _extract_facts(
            "chunk-2", "   ", context=self._context()
        )

        self.assertIn("objective 不能为空", result)

    async def test_tool_registration_exposes_reference_schema(self):
        definition = tool_registry.get("extract_facts")
        self.assertIsNotNone(definition)
        required = definition.parameters["required"]
        self.assertEqual(required, ["source_ref", "objective"])
        self.assertEqual(definition.source, "builtin")


if __name__ == "__main__":
    unittest.main()
