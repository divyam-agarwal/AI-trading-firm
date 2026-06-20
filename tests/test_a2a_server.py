import httpx
import pytest
import threading
import time
import uvicorn

from common.a2a_server import build_agent_app


def _serve(app, port):
    server = uvicorn.Server(uvicorn.Config(app, host="127.0.0.1", port=port, log_level="warning"))
    threading.Thread(target=server.run, daemon=True).start()
    while not server.started:
        time.sleep(0.05)
    return server


def test_agent_card_served():
    app = build_agent_app(
        name="T", description="d", skill_id="s", skill_name="s",
        url="http://127.0.0.1:9101/", handler=lambda text: f"got:{text}",
    )
    server = _serve(app, 9101)
    try:
        r = httpx.get("http://127.0.0.1:9101/.well-known/agent-card.json", timeout=5)
        assert r.status_code == 200
        assert r.json()["name"] == "T"
    finally:
        server.should_exit = True
