import re
import unittest
from unittest.mock import patch

from app.agent.context import AgentRunContext
from app.agent.input_processor import UserInputPlan
from app.agent.loop import AgentLoop
from app.agent.tools import ToolRegistry
from app.config import settings
from app.providers.base import AgentResponse, LLMResponse, ToolCall
from app.services.context_compression import (
    ContextCompressionError,
    ContextCompressor,
    estimate_tokens,
    extract_protected_anchors,
    split_text_losslessly,
)


class IdentifierPreservingProvider:
    def __init__(self) -> None:
        self.calls = 0

    async def chat(self, *, messages, **kwargs):
        self.calls += 1
        content = messages[-1]["content"]
        identifiers = list(dict.fromkeys(re.findall(r"CASE-\d{4}", content)))
        return LLMResponse(content=" ".join(identifiers) or "context")


class NonReducingProvider:
    async def chat(self, *, messages, **kwargs):
        content = messages[-1]["content"]
        source = content.split("<context>\n", 1)[1].rsplit("\n</context>", 1)[0]
        return LLMResponse(content=source)


class StaticInputProcessor:
    async def optimize(self, provider, question, chat_history):
        return UserInputPlan(
            original_question=question,
            standalone_question=question,
            search_queries=[question],
        )


class AgentCompressionProvider(IdentifierPreservingProvider):
    def __init__(self, *, tool_name: str | None = None) -> None:
        super().__init__()
        self.tool_name = tool_name
        self.agent_calls = 0
        self.agent_messages = []

    async def chat_with_tools(self, *, messages, **kwargs):
        self.agent_calls += 1
        self.agent_messages.append(messages)
        if self.tool_name and self.agent_calls == 1:
            return AgentResponse(tool_calls=[
                ToolCall(id="call-1", name=self.tool_name, arguments={})
            ])
        return AgentResponse(content="done")


class CorrectingAnchorProvider:
    def __init__(self, *, always_omit: bool = False) -> None:
        self.always_omit = always_omit
        self.calls = 0

    async def chat(self, *, messages, **kwargs):
        self.calls += 1
        content = messages[-1]["content"]
        anchors = extract_protected_anchors(content)
        if "Missing anchors:" in content and not self.always_omit:
            return LLMResponse(content="corrected " + " ".join(anchors))
        return LLMResponse(content="summary without protected references")


class ContextCompressionTests(unittest.IsolatedAsyncioTestCase):
    def test_lossless_split_never_discards_characters(self):
        text = "第一段。\n\n" + "alpha beta gamma. " * 80 + "结束 [12]"
        chunks = split_text_losslessly(text, 24)

        self.assertEqual("".join(chunks), text)
        self.assertGreater(len(chunks), 1)
        self.assertTrue(all(estimate_tokens(chunk) <= 24 for chunk in chunks))

    async def test_hierarchical_compression_processes_every_chunk(self):
        identifiers = [f"CASE-{index:04d}" for index in range(30)]
        text = "\n".join(
            f"{identifier}: " + "supporting detail " * 12
            for identifier in identifiers
        )
        provider = IdentifierPreservingProvider()
        compressor = ContextCompressor(
            provider,  # type: ignore[arg-type]
            chunk_tokens=90,
            max_rounds=4,
        )

        result = await compressor.compress_text(
            text,
            target_tokens=160,
            purpose="test evidence",
        )

        self.assertTrue(result.stats.compressed)
        self.assertGreater(provider.calls, 1)
        self.assertLessEqual(result.stats.compressed_tokens, 160)
        for identifier in identifiers:
            self.assertIn(identifier, result.content)

    async def test_non_reducing_agent_fails_instead_of_truncating(self):
        compressor = ContextCompressor(
            NonReducingProvider(),  # type: ignore[arg-type]
            chunk_tokens=128,
            max_rounds=2,
        )

        with self.assertRaisesRegex(ContextCompressionError, "did not reduce"):
            await compressor.compress_text(
                "unchanged evidence " * 300,
                target_tokens=128,
                purpose="non-reducing context",
            )

    async def test_missing_anchor_is_retried_and_preserved(self):
        provider = CorrectingAnchorProvider()
        compressor = ContextCompressor(
            provider,  # type: ignore[arg-type]
            chunk_tokens=256,
            max_rounds=2,
        )
        text = (
            "Investigate CASE-2048 using https://example.com/report and cite [7]. "
            + "supporting detail " * 100
        )

        result = await compressor.compress_text(
            text,
            target_tokens=128,
            purpose="protected evidence",
        )

        self.assertEqual(result.stats.protected_anchors, 3)
        self.assertGreaterEqual(result.stats.anchor_retries, 1)
        self.assertGreaterEqual(provider.calls, 2)
        for anchor in ("CASE-2048", "https://example.com/report", "[7]"):
            self.assertIn(anchor, result.content)

    async def test_repeated_anchor_omission_fails_explicitly(self):
        compressor = ContextCompressor(
            CorrectingAnchorProvider(always_omit=True),  # type: ignore[arg-type]
            chunk_tokens=256,
            max_rounds=2,
        )

        with self.assertRaisesRegex(ContextCompressionError, "protected anchors"):
            await compressor.compress_text(
                "CASE-4096 " + "detail " * 200,
                target_tokens=128,
                purpose="anchor failure",
            )

    async def test_message_compression_keeps_system_rules_and_request_identifier(self):
        provider = IdentifierPreservingProvider()
        compressor = ContextCompressor(
            provider,  # type: ignore[arg-type]
            chunk_tokens=96,
            max_rounds=4,
        )
        messages = [
            {"role": "system", "content": "Primary system rule"},
            {"role": "user", "content": "history " * 300},
            {"role": "user", "content": "Current request CASE-9999 " + "detail " * 100},
        ]

        result = await compressor.compress_messages(messages, target_tokens=220)

        self.assertEqual(result.messages[0]["content"], "Primary system rule")
        self.assertIn("CASE-9999", result.messages[-1]["content"])
        self.assertLessEqual(result.stats.compressed_tokens, 220)

    async def test_agent_loop_compresses_full_history_before_model_call(self):
        provider = AgentCompressionProvider()
        registry = ToolRegistry()

        async def local_tool():
            return "unused"

        registry.register(
            "local_tool",
            "local",
            {"type": "object", "properties": {}},
            local_tool,
        )
        compressor = ContextCompressor(
            provider,  # type: ignore[arg-type]
            chunk_tokens=240,
            max_rounds=4,
        )
        loop = AgentLoop(
            provider=provider,  # type: ignore[arg-type]
            max_iterations=1,
            tools=registry,
            input_processor=StaticInputProcessor(),  # type: ignore[arg-type]
            context_compressor=compressor,
        )
        history = [
            {
                "role": "user" if index % 2 == 0 else "assistant",
                "content": f"CASE-{index:04d} " + "historical detail " * 120,
            }
            for index in range(12)
        ]

        with patch.object(settings, "agent_context_max_tokens", 2200):
            events = [
                event
                async for event in loop.run(
                    "current request CASE-9999",
                    chat_history=history,
                    context=AgentRunContext(  # type: ignore[arg-type]
                        db=None,
                        conversation_id="conversation",
                    ),
                )
            ]

        compression_events = [
            event for event in events if event["event"] == "context_compressed"
        ]
        self.assertTrue(compression_events)
        self.assertEqual(compression_events[0]["data"]["scope"], "agent_messages")
        sent_text = "\n".join(
            str(message.get("content") or "")
            for message in provider.agent_messages[0]
        )
        self.assertIn("CASE-9999", sent_text)
        self.assertIn("You are a personal assistant", sent_text)
        for index in range(12):
            self.assertIn(f"CASE-{index:04d}", sent_text)

    async def test_tool_output_is_agent_compressed_instead_of_truncated(self):
        provider = AgentCompressionProvider(tool_name="large_tool")
        registry = ToolRegistry()
        identifiers = [f"CASE-{index:04d}" for index in range(10)]
        full_result = "\n".join(
            f"{identifier} " + "tool evidence " * 80
            for identifier in identifiers
        )

        async def large_tool():
            return full_result

        registry.register(
            "large_tool",
            "large result",
            {"type": "object", "properties": {}},
            large_tool,
        )
        loop = AgentLoop(
            provider=provider,  # type: ignore[arg-type]
            max_iterations=2,
            tools=registry,
            input_processor=StaticInputProcessor(),  # type: ignore[arg-type]
            context_compressor=ContextCompressor(
                provider,  # type: ignore[arg-type]
                chunk_tokens=160,
                max_rounds=4,
            ),
        )

        with patch.object(settings, "agent_tool_result_max_tokens", 160):
            events = [
                event
                async for event in loop.run(
                    "inspect tool output",
                    context=AgentRunContext(  # type: ignore[arg-type]
                        db=None,
                        conversation_id="conversation",
                    ),
                )
            ]

        tool_compression = [
            event
            for event in events
            if event["event"] == "context_compressed"
            and event["data"]["scope"] == "tool_result"
        ]
        self.assertEqual(len(tool_compression), 1)
        tool_message = next(
            message
            for message in provider.agent_messages[-1]
            if message.get("role") == "tool"
        )
        self.assertNotIn("截断", tool_message["content"])
        for identifier in identifiers:
            self.assertIn(identifier, tool_message["content"])

    async def test_tool_registry_returns_complete_result(self):
        registry = ToolRegistry()
        result = "complete-result-" * 5000

        async def large_tool():
            return result

        registry.register(
            "large_tool",
            "large result",
            {"type": "object", "properties": {}},
            large_tool,
        )

        self.assertEqual(await registry.execute("large_tool", {}), result)


if __name__ == "__main__":
    unittest.main()
