import threading
import time

import pytest
import uvicorn
from opentelemetry import trace
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import SimpleSpanProcessor
from opentelemetry.sdk.trace.export.in_memory_span_exporter import InMemorySpanExporter

from common import telemetry
from common.a2a_server import build_agent_app
from orchestrator.a2a_client import call_agent


def _serve(app, port):
    server = uvicorn.Server(uvicorn.Config(app, host="127.0.0.1", port=port, log_level="warning"))
    threading.Thread(target=server.run, daemon=True).start()
    while not server.started:
        time.sleep(0.05)
    return server


@pytest.mark.asyncio
async def test_client_injects_traceparent_that_carries_trace_id():
    # Force a real SDK provider with an in-memory exporter for this test.
    # Deliberately bypasses telemetry.setup() so the _CONFIGURED guard doesn't interfere.
    provider = TracerProvider()
    exporter = InMemorySpanExporter()
    provider.add_span_processor(SimpleSpanProcessor(exporter))
    trace.set_tracer_provider(provider)

    app = build_agent_app(
        name="P", description="d", skill_id="p", skill_name="p",
        url="http://127.0.0.1:9311/", handler=lambda t: "ok",
    )
    server = _serve(app, 9311)
    try:
        tr = trace.get_tracer("test")
        with tr.start_as_current_span("orchestrator-request") as span:
            expected_trace_id = span.get_span_context().trace_id
            carrier = telemetry.inject({})
            await call_agent("http://127.0.0.1:9311", "ping")
        # The injected carrier must encode the active trace id in its traceparent.
        assert "traceparent" in carrier
        assert format(expected_trace_id, "032x") in carrier["traceparent"]
    finally:
        server.should_exit = True
