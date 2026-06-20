"""Single Claude entry point. Model ids and request shape live here."""
import functools

import anthropic

MODEL_ANALYST = "claude-sonnet-4-6"
MODEL_DEBATE = "claude-opus-4-8"


@functools.lru_cache(maxsize=1)
def _client() -> anthropic.Anthropic:
    return anthropic.Anthropic()


def complete(prompt: str, *, model: str, system: str | None = None, max_tokens: int = 16000) -> str:
    kwargs = {"model": model, "max_tokens": max_tokens, "messages": [{"role": "user", "content": prompt}]}
    if system is not None:
        kwargs["system"] = system
    resp = _client().messages.create(**kwargs)
    return next((b.text for b in resp.content if b.type == "text"), "")
