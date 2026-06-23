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


def test_complete_emits_llm_span(span_exporter):
    fake_block = MagicMock(type="text", text="hi there")
    fake_resp = MagicMock(content=[fake_block])
    fake_client = MagicMock()
    fake_client.messages.create.return_value = fake_resp

    with patch.object(llm, "_client", return_value=fake_client):
        out = llm.complete("q", model=llm.MODEL_ANALYST)

    assert out == "hi there"
    spans = [s for s in span_exporter.get_finished_spans()
             if s.name == f"chat {llm.MODEL_ANALYST}"]
    assert len(spans) == 1
    assert spans[0].attributes["gen_ai.request.model"] == llm.MODEL_ANALYST


def test_complete_records_usage_and_io(span_exporter):
    fake_block = MagicMock(type="text", text="the memo")
    fake_resp = MagicMock(content=[fake_block])
    # Real ints for usage so the guard sets them; MagicMock would be skipped.
    fake_resp.usage = MagicMock(input_tokens=12, output_tokens=34)
    fake_client = MagicMock()
    fake_client.messages.create.return_value = fake_resp

    with patch.object(llm, "_client", return_value=fake_client):
        out = llm.complete("the prompt", model=llm.MODEL_ANALYST)

    assert out == "the memo"
    span = next(s for s in span_exporter.get_finished_spans()
                if s.name == f"chat {llm.MODEL_ANALYST}")
    assert span.attributes["gen_ai.usage.input_tokens"] == 12
    assert span.attributes["gen_ai.usage.output_tokens"] == 34
    assert span.attributes["langfuse.observation.input"] == "the prompt"
    assert span.attributes["langfuse.observation.output"] == "the memo"


def test_complete_skips_usage_when_not_int(span_exporter):
    # A bare MagicMock usage (non-int tokens) must NOT set token attributes,
    # must NOT raise, and must NOT emit OTel "invalid attribute" warnings.
    fake_block = MagicMock(type="text", text="ok")
    fake_resp = MagicMock(content=[fake_block])  # .usage is an auto MagicMock
    fake_client = MagicMock()
    fake_client.messages.create.return_value = fake_resp
    with patch.object(llm, "_client", return_value=fake_client):
        out = llm.complete("p", model=llm.MODEL_ANALYST)
    assert out == "ok"
    span = next(s for s in span_exporter.get_finished_spans()
                if s.name == f"chat {llm.MODEL_ANALYST}")
    assert "gen_ai.usage.input_tokens" not in span.attributes
    assert "gen_ai.usage.output_tokens" not in span.attributes
