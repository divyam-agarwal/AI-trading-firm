from common.llm import MODEL_ANALYST, complete

_SYSTEM = "You are a news & sentiment analyst. Be concise. This is a technical demo, not financial advice."

_MOCK_HEADLINES = {
    "AAPL": ["Apple unveils new product line", "Analysts split on services growth"],
    "TSLA": ["EV demand cools in key markets", "Tesla beats delivery estimates"],
}
_DEFAULT_HEADLINES = ["Company reports in line with expectations", "Sector outlook mixed"]


def analyze(ticker: str) -> str:
    headlines = _MOCK_HEADLINES.get(ticker.upper(), _DEFAULT_HEADLINES)
    prompt = (
        f"Recent headlines for {ticker.upper()}: {headlines}. "
        "Summarize the news sentiment in 2-3 sentences and label it positive, neutral, or negative."
    )
    return complete(prompt, model=MODEL_ANALYST, system=_SYSTEM)
