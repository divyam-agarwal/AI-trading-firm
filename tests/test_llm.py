from unittest.mock import MagicMock, patch

from common import llm


def test_complete_returns_first_text_block():
    fake_block = MagicMock(type="text", text="hello world")
    fake_resp = MagicMock(content=[fake_block])
    fake_client = MagicMock()
    fake_client.messages.create.return_value = fake_resp

    with patch.object(llm, "_client", return_value=fake_client):
        out = llm.complete("hi", model=llm.MODEL_ANALYST)

    assert out == "hello world"
    _, kwargs = fake_client.messages.create.call_args
    assert kwargs["model"] == "claude-sonnet-4-6"
    assert kwargs["max_tokens"] == 16000


def test_complete_empty_when_no_text_block():
    fake_resp = MagicMock(content=[])
    fake_client = MagicMock()
    fake_client.messages.create.return_value = fake_resp
    with patch.object(llm, "_client", return_value=fake_client):
        assert llm.complete("hi", model=llm.MODEL_DEBATE) == ""
