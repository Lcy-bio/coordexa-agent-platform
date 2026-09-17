import asyncio
from types import SimpleNamespace

from agents.agent_orchestrator import AgentType
from core.intent_recognizer import IntentCategory, UrgencyLevel
from evaluation.evaluator import EndToEndEvaluator, QualityScores


class FakeRecognizer:
    async def recognize(self, message, history=None):
        return SimpleNamespace(
            intent=IntentCategory.REFUND,
            intent_group="billing",
            entities={"order_id": ["A12345"]},
            urgency=UrgencyLevel.LOW,
            confidence=0.92,
        )


class FakeOrchestrator:
    def __init__(self):
        self.requests = []

    async def run(self, request):
        self.requests.append(request)
        return SimpleNamespace(
            response="已进入退款核验流程。",
            agent_type=AgentType.BILLING,
            intent=request.intent,
        )


class FakeJudge:
    def __init__(self, scores):
        self.scores = scores

    async def judge(self, question, response, context=None):
        return self.scores


def make_evaluator(scores):
    orchestrator = FakeOrchestrator()
    evaluator = EndToEndEvaluator(
        orchestrator=orchestrator,
        recognizer=FakeRecognizer(),
        api_key="test-key",
        model="test-model",
    )
    evaluator._judge = FakeJudge(scores)
    return evaluator, orchestrator


def test_dialog_evaluation_recognizes_intent_before_routing():
    evaluator, orchestrator = make_evaluator(QualityScores(0.9, 0.9, 0.8, 0.9))

    report = asyncio.run(evaluator.run(dialog_cases=[{"question": "订单号 A12345，我想退款"}]))

    assert orchestrator.requests[0].intent is IntentCategory.REFUND
    assert orchestrator.requests[0].intent_group == "billing"
    assert orchestrator.requests[0].entities["order_id"] == ["A12345"]
    assert report.avg_scores["judge_success_rate"] == 1.0
    assert report.avg_scores["relevance"] == 0.9


def test_failed_judge_is_excluded_from_quality_average():
    evaluator, _ = make_evaluator(
        QualityScores(0.5, 0.5, 0.5, 0.5, judge_failed=True, error="invalid json")
    )

    report = asyncio.run(evaluator.run(dialog_cases=[{"question": "订单号 A12345，我想退款"}]))

    assert report.avg_scores["judge_success_rate"] == 0.0
    assert "relevance" not in report.avg_scores
    assert report.results[0].passed is False
    assert "Judge 调用失败" in report.results[0].detail

