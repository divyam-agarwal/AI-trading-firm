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
