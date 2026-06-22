from common import telemetry


def test_inject_then_extract_roundtrips_a_span(monkeypatch):
    monkeypatch.delenv("OTEL_EXPORTER_OTLP_ENDPOINT", raising=False)
    telemetry.setup("test-svc")
    tr = telemetry.tracer("t")
    with tr.start_as_current_span("parent"):
        carrier = telemetry.inject({})
    # A started span must produce a W3C traceparent header.
    assert "traceparent" in carrier
    # extract returns a context object (opaque) without raising.
    ctx = telemetry.extract(carrier)
    assert ctx is not None


def test_setup_is_idempotent(monkeypatch):
    monkeypatch.delenv("OTEL_EXPORTER_OTLP_ENDPOINT", raising=False)
    telemetry.setup("svc-a")
    telemetry.setup("svc-a")  # must not raise


def test_server_span_continues_remote_trace(span_exporter):
    from common import telemetry

    tr = telemetry.tracer("remote")
    with tr.start_as_current_span("remote-root") as root:
        carrier = telemetry.inject({})
        root_ctx = root.get_span_context()

    # Server side: continue the trace from the carrier alone.
    with telemetry.server_span("agent-server", carrier) as span:
        assert span.get_span_context().trace_id == root_ctx.trace_id

    finished = {s.name: s for s in span_exporter.get_finished_spans()}
    server = finished["agent-server"]
    assert server.context.trace_id == root_ctx.trace_id
    assert server.parent is not None
    assert server.parent.span_id == root_ctx.span_id
