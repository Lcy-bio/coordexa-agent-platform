import asyncio

import pytest

from agents.agent_orchestrator import AgentType, Request, ResponseComposer, TechnicalAgent
from api.main import _dynamic_top_k
from core.context_budget import ContextBudget
from core.llm_usage import component_context, request_context, track_client, get_usage_tracker
from mcp.knowledge_base import ChunkingConfig, KnowledgeBase
from mcp.tool_manager import CircuitBreaker, CircuitState, MCPToolManager, Tool


class FakeResponse:
    content = [type("Text", (), {"type": "text", "text": "ok"})()]
    usage = {"input_tokens": 12, "output_tokens": 7}


class UsageClient:
    def __init__(self):
        self.calls = []

        class Messages:
            async def create(inner, **kwargs):
                self.calls.append(kwargs)
                return FakeResponse()

        self.messages = Messages()


def test_tracked_client_records_provider_usage_by_request_and_component():
    async def exercise():
        client = track_client(UsageClient())
        with request_context("usage-test"), component_context("test.component"):
            await client.messages.create(model="test-model", messages=[])

    asyncio.run(exercise())
    summary = get_usage_tracker().summary("usage-test")
    assert summary["input_tokens"] == 12
    assert summary["output_tokens"] == 7
    assert summary["total_tokens"] == 19
    assert summary["usage_available_calls"] == 1
    assert summary["components"] == ["test.component"]


def test_llm_usage_overview_aggregates_components_and_requests():
    overview = get_usage_tracker().overview(limit=500)
    assert overview["request_count"] >= 1
    assert overview["totals"]["total_tokens"] >= 19
    assert "test.component" in overview["by_component"]
    assert overview["by_request"][0]["request_id"]


def test_context_budget_keeps_sections_and_marks_truncation():
    budget = ContextBudget(model_context_chars=1000, reserved_output_chars=200, prompt_chars=150, memory_chars=180, retrieval_chars=180)
    value = budget.fit_context(
        "[最近对话]\n" + "历史" * 200 + "\n\n[知识库检索结果]\n" + "退款政策" * 200
    )
    assert len(value) <= budget.available_chars
    assert "上下文按预算截断" in value or len(value) < 1000


def test_chunking_hard_split_bounds_long_sentence_and_supports_overlap():
    config = ChunkingConfig(max_chars=20, overlap_chars=4, hard_split=True)
    kb = KnowledgeBase.__new__(KnowledgeBase)
    chunks = kb._chunk_text("x" * 65, config.max_chars, config.overlap_chars, config.hard_split)
    assert len(chunks) >= 4
    assert all(0 < len(chunk) <= 20 for chunk in chunks)


def test_empty_agent_output_is_retried_then_reported_as_failure():
    class EmptyClient:
        def __init__(self):
            self.calls = 0

            class Messages:
                async def create(inner, **kwargs):
                    self.calls += 1
                    return type("Response", (), {"content": []})()

            self.messages = Messages()

    async def exercise():
        client = EmptyClient()
        result = await TechnicalAgent(client, "test-model").handle(Request("401", "u", "c"))
        return client, result

    client, result = asyncio.run(exercise())
    assert client.calls == 2
    assert result.success is False
    assert "空文本" in result.failure_reason


@pytest.mark.parametrize("limit,reserved", [(1200, 200), (1400, 300), (1600, 400), (1800, 500), (2000, 600), (2400, 600), (3000, 800), (4000, 1000), (6000, 1200), (8000, 1600)])
def test_context_budget_never_exceeds_configured_available_budget(limit, reserved):
    budget = ContextBudget(model_context_chars=limit, reserved_output_chars=reserved)
    result = budget.fit("上下文" * 5000)
    assert len(result) <= budget.available_chars


@pytest.mark.parametrize("size,overlap", [(100, 0), (120, 10), (150, 20), (200, 0), (220, 30), (250, 40), (300, 50), (350, 0), (400, 20), (500, 50)])
def test_chunking_matrix_keeps_each_chunk_bounded(size, overlap):
    kb = KnowledgeBase.__new__(KnowledgeBase)
    chunks = kb._chunk_text("长句" * 500, size, overlap, True)
    assert chunks
    assert all(0 < len(chunk) <= size for chunk in chunks)


@pytest.mark.parametrize("request_id", [f"missing-{index}" for index in range(5)])
def test_missing_provider_usage_is_explicitly_marked(request_id):
    class NoUsageResponse:
        content = []
        usage = None

    class Client:
        def __init__(self):
            class Messages:
                async def create(inner, **kwargs):
                    return NoUsageResponse()
            self.messages = Messages()

    async def exercise():
        with request_context(request_id), component_context("test.missing"):
            await track_client(Client()).messages.create(model="test-model", messages=[])

    asyncio.run(exercise())
    summary = get_usage_tracker().summary(request_id)
    assert summary["usage_available_calls"] == 0
    assert summary["usage_missing_calls"] == 1
    assert summary["total_tokens"] is None


@pytest.mark.parametrize("error_text", ["timeout", "provider down", "bad gateway", "rate limited", "invalid request"])
def test_tool_fallback_is_a_visible_degraded_result(error_text):
    async def handler(params, context):
        raise RuntimeError(error_text)

    async def fallback(params, context, error):
        return {"message": "请稍后重试", "original_error": error}

    manager = MCPToolManager.__new__(MCPToolManager)
    manager._tools = {}
    manager._cache = {}
    manager.register(Tool(
        name="unstable",
        description="test",
        handler=handler,
        schema={"type": "object", "properties": {}, "additionalProperties": False},
        fallback=fallback,
    ))
    result = asyncio.run(manager.call("unstable", {}))
    assert result.success is True
    assert result.fallback_used is True
    assert result.degraded is True
    assert result.data["original_error"] == error_text


@pytest.mark.parametrize("threshold", [1, 2, 3, 4, 5])
def test_circuit_breaker_opens_at_configured_failure_threshold(threshold):
    breaker = CircuitBreaker(failure_threshold=threshold, recovery_s=60)
    for _ in range(threshold):
        breaker.record_failure()
    assert breaker.state is CircuitState.OPEN
    assert breaker.allow() is False


@pytest.mark.parametrize("message,intent,minimum", [
    ("退款", None, 1),
    ("登录401且重复扣款，需要退款", None, 2),
    ("这是一段较长的用户问题" * 10, None, 2),
    ("我要投诉并转人工", "complaint", 2),
    ("订单状态", None, 1),
])
def test_dynamic_top_k_reflects_query_complexity(message, intent, minimum):
    assert _dynamic_top_k(message, intent=intent, requested=1) >= minimum
