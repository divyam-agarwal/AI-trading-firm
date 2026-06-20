"""End-to-end contract test for the A2A client wrapper.

Starts a real wrapper-built agent in-process (no LLM — handler is a fixed echo)
and verifies that call_agent returns the reply text.
"""
import threading
import time

import pytest
import uvicorn

from common.a2a_server import build_agent_app
from orchestrator.a2a_client import call_agent


def _serve(app, port):
    server = uvicorn.Server(uvicorn.Config(app, host="127.0.0.1", port=port, log_level="warning"))
    threading.Thread(target=server.run, daemon=True).start()
    # Readiness poll instead of fixed sleep
    while not server.started:
        time.sleep(0.05)
    return server


@pytest.mark.asyncio
async def test_call_agent_round_trip():
    app = build_agent_app(
        name="Stub",
        description="d",
        skill_id="s",
        skill_name="s",
        url="http://127.0.0.1:9111/",
        handler=lambda text: f"REPLY[{text}]",
    )
    server = _serve(app, 9111)
    try:
        out = await call_agent("http://127.0.0.1:9111", "ping")
        assert "REPLY[ping]" in out
    finally:
        server.should_exit = True
