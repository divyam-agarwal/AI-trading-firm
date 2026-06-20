import threading
import time

import pytest
import uvicorn

from common.a2a_server import build_agent_app
from orchestrator.graph import run


def _serve(app, port):
    server = uvicorn.Server(uvicorn.Config(app, host="127.0.0.1", port=port, log_level="warning"))
    threading.Thread(target=server.run, daemon=True).start()
    # Poll until the server has actually started (avoids a fixed sleep)
    while not server.started:
        time.sleep(0.05)
    return server


@pytest.mark.asyncio
async def test_full_graph_with_stub_agents():
    servers = []
    servers.append(_serve(build_agent_app(
        name="F", description="d", skill_id="f", skill_name="f",
        url="http://127.0.0.1:9201/", handler=lambda t: "fundamentals look attractive",
    ), 9201))
    servers.append(_serve(build_agent_app(
        name="S", description="d", skill_id="s", skill_name="s",
        url="http://127.0.0.1:9202/", handler=lambda t: "sentiment positive",
    ), 9202))
    # Debate stub echoes the joined input so we can assert fan-out + join happened.
    servers.append(_serve(build_agent_app(
        name="D", description="d", skill_id="d", skill_name="d",
        url="http://127.0.0.1:9203/",
        handler=lambda t: f"{t}\nRECOMMENDATION: BUY",
    ), 9203))
    urls = {
        "fundamentals": "http://127.0.0.1:9201",
        "sentiment": "http://127.0.0.1:9202",
        "debate": "http://127.0.0.1:9203",
    }
    try:
        state = await run("AAPL", urls)
        assert state["fundamentals"] == "fundamentals look attractive"
        assert state["sentiment"] == "sentiment positive"
        # join: the debate input must have contained BOTH analyst reports
        assert "fundamentals look attractive" in state["memo"]
        assert "sentiment positive" in state["memo"]
        assert state["recommendation"] == "BUY"
    finally:
        for s in servers:
            s.should_exit = True
