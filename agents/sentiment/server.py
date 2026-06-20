from common.a2a_server import build_agent_app, run_agent
from common.telemetry import setup

from .logic import analyze

PORT = 9002


def app():
    setup("sentiment-agent")
    return build_agent_app(
        name="News & Sentiment Analyst",
        description="Summarizes recent news sentiment. Demo only, not financial advice.",
        skill_id="analyze_sentiment",
        skill_name="Analyze Sentiment",
        url=f"http://127.0.0.1:{PORT}/",
        handler=analyze,
    )


if __name__ == "__main__":
    run_agent(app(), host="127.0.0.1", port=PORT)
