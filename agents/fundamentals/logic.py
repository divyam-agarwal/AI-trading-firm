from common.llm import MODEL_ANALYST, complete

from . import data

_SYSTEM = "You are a fundamentals analyst. Be concise. This is a technical demo, not financial advice."


def analyze(ticker: str) -> str:
    facts = data.load(ticker)
    prompt = (
        f"Given these fundamentals for {facts['ticker']}: {facts}. "
        "Summarize the valuation picture in 3-4 sentences and state whether fundamentals "
        "look attractive, neutral, or expensive."
    )
    return complete(prompt, model=MODEL_ANALYST, system=_SYSTEM)
