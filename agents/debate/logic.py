import re

from common.llm import MODEL_DEBATE, complete

_DISCLAIMER = "\n\n---\nThis is a technical demo of agent coordination. Not financial advice."

_SYSTEM = (
    "You are a research analyst. Argue the bull case and the bear case, then decide. "
    "End your reply with a final line exactly of the form 'RECOMMENDATION: BUY' "
    "(or HOLD or SELL). This is a technical demo, not financial advice."
)


def parse_recommendation(memo: str) -> str:
    # Primary: anchor on RECOMMENDATION: lines; last match wins so corrections override.
    matches = re.findall(r"RECOMMENDATION:\s*(BUY|HOLD|SELL)", memo, re.IGNORECASE)
    if matches:
        return matches[-1].upper()

    # Fallback: whole-memo substring scan for bare label words.
    upper = memo.upper()
    for label in ("BUY", "SELL", "HOLD"):
        if label in upper:
            return label
    return "HOLD"


def synthesize(fundamentals: str, sentiment: str) -> str:
    prompt = (
        "Fundamentals analyst report:\n"
        f"{fundamentals}\n\n"
        "News & sentiment analyst report:\n"
        f"{sentiment}\n\n"
        "Debate the bull vs bear case, weigh both reports, and produce a short memo. "
        "End with 'RECOMMENDATION: BUY|HOLD|SELL'."
    )
    memo = complete(prompt, model=MODEL_DEBATE, system=_SYSTEM)
    return memo + _DISCLAIMER
