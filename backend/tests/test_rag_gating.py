import pytest

from api.main import _should_use_knowledge
from core.intent_recognizer import IntentCategory


@pytest.mark.parametrize(
    ("message", "intent"),
    [
        ("你好", IntentCategory.GREETING),
        ("谢谢你的帮助", IntentCategory.FEEDBACK),
        ("我要转人工", IntentCategory.HUMAN_HANDOFF),
        ("", IntentCategory.OTHER),
    ],
)
def test_non_business_requests_skip_rag(message, intent):
    assert _should_use_knowledge(message, intent) is False


@pytest.mark.parametrize(
    ("message", "intent"),
    [
        ("退款多久到账？", IntentCategory.REFUND),
        ("登录一直报 401", IntentCategory.TECHNICAL_LOGIN),
        ("我的订单什么时候到？", IntentCategory.LOGISTICS),
        ("为什么被重复扣款？", IntentCategory.PAYMENT_ISSUE),
    ],
)
def test_business_requests_enable_rag(message, intent):
    assert _should_use_knowledge(message, intent) is True

