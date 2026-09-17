import asyncio
import json

import pytest

from core.intent_recognizer import IntentCategory, IntentRecognizer
from core.llm_utils import extract_json_value, extract_labeled_floats
from evaluation.evaluator import LLMJudge
from memory.conversation_memory import MemoryManager, Message, MsgRole
from mcp.knowledge_base import KnowledgeBase
from mcp.tool_manager import MCPToolManager, Tool


class TextBlock:
    type = "text"

    def __init__(self, text):
        self.text = text


class StaticClient:
    def __init__(self, text):
        class Messages:
            async def create(inner, **kwargs):
                return type("Response", (), {"content": [TextBlock(text)]})()

        self.messages = Messages()


def test_json_helpers_accept_fences_and_labeled_numbers():
    parsed = extract_json_value("说明\n```json\n{\"intent\": \"refund\"}\n```", dict)
    scores = extract_labeled_floats("relevance: 0.9，accuracy：0.8", ("relevance", "accuracy"))

    assert parsed == {"intent": "refund"}
    assert scores == {"relevance": 0.9, "accuracy": 0.8}


def test_intent_parser_accepts_compatible_plain_text_output():
    parsed = IntentRecognizer._parse_llm_payload("意图: technical_login\n置信度: 0.86")

    assert parsed["intent"] == IntentCategory.TECHNICAL_LOGIN.value
    assert parsed["confidence"] == 0.86


def test_order_id_extraction_accepts_chinese_connector():
    recognizer = IntentRecognizer.__new__(IntentRecognizer)

    entities = recognizer._extract_entities("订单号是 C24680。")

    assert entities["order_id"] == ["C24680"]


def test_judge_accepts_labeled_scores_without_json_braces():
    judge = LLMJudge(
        StaticClient("relevance: 0.9\naccuracy: 0.8\ncompleteness: 0.7\nhelpfulness: 0.85"),
        "test-model",
    )

    result = asyncio.run(judge.judge("问题", "回答"))

    assert result.judge_failed is False
    assert result.overall == pytest.approx(0.8125)


def test_judge_retries_once_after_empty_response():
    class RetryClient:
        def __init__(self):
            self.calls = 0
            self.max_tokens = []

            class Messages:
                async def create(inner, **kwargs):
                    self.calls += 1
                    self.max_tokens.append(kwargs["max_tokens"])
                    text = "" if self.calls == 1 else (
                        '{"relevance": 0.9, "accuracy": 0.8, '
                        '"completeness": 0.7, "helpfulness": 0.6}'
                    )
                    return type("Response", (), {"content": [TextBlock(text)]})()

            self.messages = Messages()

    client = RetryClient()
    result = asyncio.run(LLMJudge(client, "test-model").judge("问题", "回答"))

    assert client.calls == 2
    assert client.max_tokens == [1600, 3200]
    assert result.judge_failed is False
    assert result.overall == pytest.approx(0.75)


def test_chinese_lexical_ranking_can_correct_weak_vector_order():
    class Collection:
        def count(self):
            return 2

        def query(self, **kwargs):
            return {
                "documents": [["账户安全设置说明", "会员积分有效期为一年，过期清零"]],
                "metadatas": [[
                    {"title": "账户安全", "chunk_index": 0},
                    {"title": "会员与积分", "chunk_index": 0},
                ]],
                "distances": [[0.1, 0.3]],
            }

    kb = KnowledgeBase.__new__(KnowledgeBase)
    kb._collection = Collection()

    results = kb.search("会员积分什么时候过期", top_k=2)

    assert results[0]["title"] == "会员与积分"
    assert results[0]["lexical_score"] > results[1]["lexical_score"]
    assert "vector_score" in results[0]


def test_knowledge_import_uses_deterministic_upsert():
    class Collection:
        def __init__(self):
            self.calls = []

        def upsert(self, **kwargs):
            self.calls.append(kwargs)

    kb = KnowledgeBase.__new__(KnowledgeBase)
    kb._collection = Collection()
    docs = [{"title": "退款政策", "content": "退款审核需要一到三个工作日。"}]

    assert kb.add_documents(docs) == 1
    assert kb.add_documents(docs) == 1
    assert kb._collection.calls[0]["ids"] == kb._collection.calls[1]["ids"]


def test_tool_stats_only_count_completed_calls():
    async def exercise():
        started = asyncio.Event()
        release = asyncio.Event()

        async def handler(params, context):
            started.set()
            await release.wait()
            return {"ok": True}

        manager = MCPToolManager.__new__(MCPToolManager)
        tool = Tool(
            name="slow_tool",
            description="test",
            handler=handler,
            schema={"type": "object", "properties": {}, "additionalProperties": False},
        )
        manager._tools = {tool.name: tool}
        manager._cache = {}

        task = asyncio.create_task(manager.call(tool.name, {}))
        await started.wait()
        assert tool.stats.total == 0

        release.set()
        result = await task
        assert result.success is True
        assert tool.stats.total == 1
        assert tool.stats.success == 1

    asyncio.run(exercise())


def test_tool_schema_rejects_unknown_and_out_of_range_parameters():
    manager = MCPToolManager.__new__(MCPToolManager)
    tool = Tool(
        name="bounded_tool",
        description="test",
        handler=lambda params, context: None,
        schema={
            "type": "object",
            "properties": {"top_k": {"type": "integer", "minimum": 1, "maximum": 20}},
            "required": ["top_k"],
            "additionalProperties": False,
        },
    )

    with pytest.raises(ValueError, match="不允许参数"):
        manager._validate_params(tool, {"top_k": 3, "secret": "no"})
    with pytest.raises(ValueError, match="小于最小值"):
        manager._validate_params(tool, {"top_k": 0})
    with pytest.raises(ValueError, match="超过最大值"):
        manager._validate_params(tool, {"top_k": 21})


def test_profile_parser_accepts_fenced_json_and_normalizes_values():
    parsed = MemoryManager._parse_profile_payload(
        '说明\n```json\n{"preferences": "偏好中文", '
        '"entities": {"产品": "会员", "问题类型": ["退款", ""]}}\n```'
    )

    assert parsed == {
        "preferences": ["偏好中文"],
        "entities": {"产品": ["会员"], "问题类型": ["退款"]},
    }


def test_memory_compression_rebuilds_redis_with_newest_message_first():
    class FakeRedis:
        def __init__(self):
            self.items = []

        async def get(self, key):
            return ""

        async def setex(self, key, ttl, value):
            return True

        async def delete(self, key):
            self.items.clear()

        async def lpush(self, key, value):
            self.items.insert(0, value)

        async def expire(self, key, ttl):
            return True

    async def exercise():
        memory = MemoryManager.__new__(MemoryManager)
        memory._redis = FakeRedis()
        memory._client = StaticClient("测试摘要")
        memory._model = "test-model"
        messages = [Message(MsgRole.USER, f"message-{index}") for index in range(15)]

        async def get_messages(user_id, conv_id):
            return messages

        async def store_episodic(user_id, conv_id, text, summary):
            return None

        memory._get_working_memory = get_messages
        memory._store_episodic = store_episodic

        await memory._compress("u1", "c1")

        contents = [json.loads(raw)["content"] for raw in memory._redis.items]
        assert contents == ["message-14", "message-13", "message-12", "message-11", "message-10"]

    asyncio.run(exercise())
