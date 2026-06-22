"""LangGraph orchestrator. Nodes call remote A2A agents; runs the predefined flow."""
from typing import TypedDict

from langgraph.graph import END, START, StateGraph

from agents.debate.logic import parse_recommendation
from common import telemetry
from orchestrator.a2a_client import call_agent

SEP = "\n\nSENTIMENT:\n"

DEFAULT_URLS = {
    "fundamentals": "http://127.0.0.1:9001",
    "sentiment": "http://127.0.0.1:9002",
    "debate": "http://127.0.0.1:9003",
}


class State(TypedDict, total=False):
    ticker: str
    fundamentals: str | None
    sentiment: str | None
    memo: str | None
    recommendation: str | None


def build_graph(urls: dict):
    async def gather_fundamentals(state: State) -> dict:
        return {"fundamentals": await call_agent(urls["fundamentals"], state["ticker"], agent_name="fundamentals")}

    async def gather_sentiment(state: State) -> dict:
        return {"sentiment": await call_agent(urls["sentiment"], state["ticker"], agent_name="sentiment")}

    async def debate(state: State) -> dict:
        joined = f"FUNDAMENTALS:\n{state['fundamentals']}{SEP}{state['sentiment']}"
        memo = await call_agent(urls["debate"], joined, agent_name="debate")
        return {"memo": memo, "recommendation": parse_recommendation(memo)}

    g = StateGraph(State)
    g.add_node("gather_fundamentals", gather_fundamentals)
    g.add_node("gather_sentiment", gather_sentiment)
    g.add_node("debate", debate)
    g.add_edge(START, "gather_fundamentals")
    g.add_edge(START, "gather_sentiment")
    g.add_edge("gather_fundamentals", "debate")
    g.add_edge("gather_sentiment", "debate")
    g.add_edge("debate", END)
    return g.compile()


async def run(ticker: str, urls: dict[str, str] | None = None) -> State:
    graph = build_graph(urls or DEFAULT_URLS)
    with telemetry.tracer(__name__).start_as_current_span(f"analyze {ticker}") as span:
        span.set_attribute("ticker", ticker)
        return await graph.ainvoke({"ticker": ticker})
