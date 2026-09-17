import asyncio

from agents.agent_orchestrator import GeneralAgent, Request
from core.intent_recognizer import IntentCategory, IntentRecognizer
from memory.conversation_memory import MemoryManager
from monitor.performance_monitor import PerformanceMonitor


class BlockingClient:
    def __init__(self):
        self.started = asyncio.Event()
        self.release = asyncio.Event()

        class Messages:
            async def create(inner, **kwargs):
                self.started.set()
                await self.release.wait()
                text = type("TextBlock", (), {"type": "text", "text": "处理完成"})()
                return type("Response", (), {"content": [text]})()

        self.messages = Messages()


def test_agent_stats_only_count_completed_requests():
    async def exercise():
        client = BlockingClient()
        agent = GeneralAgent(client, "test-model")
        task = asyncio.create_task(agent.handle(Request("你好", "u1", "c1")))

        await client.started.wait()
        assert agent.stats.total == 0
        assert agent.stats.success_rate == 1.0

        client.release.set()
        response = await task
        assert response.success is True
        assert agent.stats.total == 1
        assert agent.stats.success == 1

    asyncio.run(exercise())


def test_threshold_alert_is_deduplicated_and_resolved():
    monitor = PerformanceMonitor(orchestrator=None, tool_manager=None)

    monitor._check_threshold("agent_avg_ms", 5000, "technical_0")
    monitor._check_threshold("agent_avg_ms", 6000, "technical_0")

    assert len(monitor._alerts) == 1
    assert monitor._alerts[0].value == 6000
    assert monitor._alerts[0].resolved is False

    monitor._check_threshold("agent_avg_ms", 1000, "technical_0")
    assert monitor._alerts[0].resolved is True

    monitor._check_threshold("agent_avg_ms", 4500, "technical_0")
    assert len(monitor._alerts) == 2
    assert monitor._alerts[-1].resolved is False


def test_episodic_memory_uses_chroma_compound_filter():
    async def exercise():
        memory = MemoryManager.__new__(MemoryManager)
        captured = []

        async def query(query_text, n_results, where):
            captured.append(where)
            return {"documents": [["记录1", "记录2", "记录3", "记录4", "记录5"]]}

        memory._query_episodic = query
        docs = await memory._search_episodic("u1", "c1", "上一笔订单")

        assert docs == ["记录1", "记录2", "记录3", "记录4", "记录5"]
        assert captured == [{
            "$and": [
                {"user_id": {"$eq": "u1"}},
                {"conv_id": {"$eq": "c1"}},
            ]
        }]

    asyncio.run(exercise())


def test_explicit_handoff_signal_overrides_broad_llm_escalation():
    recognizer = IntentRecognizer.__new__(IntentRecognizer)
    intent, confidence, scores = recognizer._vote(
        {"intent": IntentCategory.ESCALATION, "confidence": 0.95},
        {"intent": IntentCategory.ESCALATION, "confidence": 0.80},
        {"intent": IntentCategory.HUMAN_HANDOFF, "confidence": 0.50},
    )

    assert intent is IntentCategory.HUMAN_HANDOFF
    assert confidence == 0.50
    assert scores["explicit_handoff"] == 0.50
