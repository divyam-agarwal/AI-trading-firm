"""Single Claude entry point. Model ids and request shape live here."""
import functools

import anthropic
from opentelemetry.trace import Status, StatusCode

from common import telemetry

MODEL_ANALYST = "claude-sonnet-4-6"
MODEL_DEBATE = "claude-opus-4-8"


@functools.lru_cache(maxsize=1)
def _client() -> anthropic.Anthropic:
    return anthropic.Anthropic()


def complete(prompt: str, *, model: str, system: str | None = None, max_tokens: int = 16000) -> str:
    kwargs = {"model": model, "max_tokens": max_tokens, "messages": [{"role": "user", "content": prompt}]}
    if system is not None:
        kwargs["system"] = system
    with telemetry.tracer(__name__).start_as_current_span(f"chat {model}") as span:
        span.set_attribute("gen_ai.request.model", model)
        try:
            resp = _client().messages.create(**kwargs)
        except Exception as exc:
            span.record_exception(exc)
            span.set_status(Status(StatusCode.ERROR, str(exc)))
            raise
        return next((b.text for b in resp.content if b.type == "text"), "")
