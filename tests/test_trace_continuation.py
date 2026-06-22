import threading
import time

import pytest
import uvicorn

from common import telemetry
from common.a2a_server import build_agent_app
from orchestrator.a2a_client import call_agent
from orchestrator.graph import run


def _serve(app, port):
    server = uvicorn.Server(uvicorn.Config(app, host="127.0.0.1", port=port, log_level="warning"))
    threading.Thread(target=server.run, daemon=True).start()
    while not server.started:
        time.sleep(0.05)
    return server


@pytest.mark.asyncio
async def test_server_span_parents_into_orchestrator_trace(span_exporter):
    app = build_agent_app(
        name="contagent", description="d", skill_id="c", skill_name="c",
        url="http://127.0.0.1:9331/", handler=lambda t: "ok",
    )
    server = _serve(app, 9331)
    tr = telemetry.tracer("test")
    try:
        with tr.start_as_current_span("analyze-root") as root:
            root_tid = root.get_span_context().trace_id
            await call_agent("http://127.0.0.1:9331", "ping", agent_name="contagent")
    finally:
        server.should_exit = True

    spans = {s.name: s for s in span_exporter.get_finished_spans()}
    client = spans["a2a SendMessage"]
    server_span = spans["contagent"]
    assert client.context.trace_id == root_tid
    assert server_span.context.trace_id == root_tid
    assert server_span.parent is not None
    assert server_span.parent.span_id == client.context.span_id
