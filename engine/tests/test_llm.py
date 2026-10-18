import pytest

from vault_engine.app import RerankError, parse_scores
from vault_engine.config import ModelRef
from vault_engine.providers import ProviderError, chat_content, chat_payload

LMS = ModelRef(provider="lmstudio", model="google/gemma-4-e4b")
OLL = ModelRef(provider="ollama", model="qwen3:8b")


def test_reasoning_disabled_by_default():
    assert chat_payload(LMS, [], 0.1, 100, reasoning=False)["reasoning_effort"] == "none"
    assert chat_payload(OLL, [], 0.1, 100, reasoning=False)["think"] is False
    assert "reasoning_effort" not in chat_payload(LMS, [], 0.1, 100, reasoning=True)


def test_empty_answer_after_token_budget_is_an_error():
    data = {"choices": [{"message": {"content": ""}, "finish_reason": "length"}]}
    with pytest.raises(ProviderError, match="token budget"):
        chat_content(LMS, data)


def test_think_blocks_removed():
    data = {"choices": [{"message": {"content": "<think>hmm</think>\nRisposta"}, "finish_reason": "stop"}]}
    assert chat_content(LMS, data) == "Risposta"


@pytest.mark.parametrize(
    "reply",
    ['{"scores": [10, 0]}', '```json\n{\n  "scores": [\n    10,\n    0\n  ]\n}\n```', 'Ecco: {"scores": ["10", "0"]}'],
)
def test_parse_scores_formats(reply):
    assert parse_scores(reply, 2) == [10.0, 0.0]


@pytest.mark.parametrize(
    ("status", "body", "payload", "expected"),
    [
        (200, {"ok": 1}, {}, "ok"),
        (400, {"error": 'Failed to load model "bge-m3". Error: Operation canceled.'}, {}, "retry"),
        (503, {"error": "busy"}, {}, "retry"),
        (400, {"error": {"message": "Unrecognized key: reasoning_effort"}}, {"reasoning_effort": "none"}, "drop-reasoning"),
        (400, {"error": "context length exceeded"}, {"reasoning_effort": "none"}, "fail"),
        (404, {"error": "model not found"}, {}, "fail"),
    ],
)
def test_retry_decision(status, body, payload, expected):
    import httpx

    from vault_engine.providers import _retry_decision

    resp = httpx.Response(status, json=body, request=httpx.Request("POST", "http://x"))
    assert _retry_decision(resp, payload) == expected


@pytest.mark.parametrize("reply", ["", "nessun json", '{"scores": [1]}', '{"voti": [1, 2]}'])
def test_parse_scores_rejects_bad_replies(reply):
    with pytest.raises(RerankError):
        parse_scores(reply, 2)
