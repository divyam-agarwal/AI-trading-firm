from common.a2a_server import build_agent_app, run_agent
from common.telemetry import setup

from .logic import synthesize

PORT = 9003
SEP = "\n\nSENTIMENT:\n"


def _handler(text: str) -> str:
    fundamentals, _, sentiment = text.partition(SEP)
    fundamentals = fundamentals.removeprefix("FUNDAMENTALS:\n")
    return synthesize(fundamentals, sentiment)


def app():
    setup("debate-agent")
    return build_agent_app(
        name="Research & Debate Analyst",
        description="Bull-vs-bear synthesis into a BUY/HOLD/SELL memo. Demo only, not financial advice.",
        skill_id="synthesize",
        skill_name="Synthesize Memo",
        url=f"http://127.0.0.1:{PORT}/",
        handler=_handler,
    )


if __name__ == "__main__":
    run_agent(app(), host="127.0.0.1", port=PORT)
