from common.a2a_server import build_agent_app, run_agent
from common.telemetry import setup

from .logic import analyze

PORT = 9001


def app():
    setup("fundamentals-agent")
    return build_agent_app(
        name="Fundamentals Analyst",
        description="Evaluates company financials and valuation. Demo only, not financial advice.",
        skill_id="analyze_fundamentals",
        skill_name="Analyze Fundamentals",
        url=f"http://127.0.0.1:{PORT}/",
        handler=analyze,
    )


if __name__ == "__main__":
    run_agent(app(), host="127.0.0.1", port=PORT)
