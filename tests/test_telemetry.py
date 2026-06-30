import types
from unittest.mock import MagicMock

from opentelemetry.sdk.trace.export import SpanExportResult

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


class _RecordingExporter:
    """Inner exporter stub: records the span batches it receives."""

    def __init__(self):
        self.exported = []
        self.shutdown_called = False
        self.flushed = False

    def export(self, spans):
        self.exported.append(list(spans))
        return SpanExportResult.SUCCESS

    def shutdown(self):
        self.shutdown_called = True

    def force_flush(self, timeout_millis=30000):
        self.flushed = True
        return True


def _span(scope_name):
    """A minimal stand-in for a ReadableSpan carrying an instrumentation scope."""
    return types.SimpleNamespace(
        instrumentation_scope=types.SimpleNamespace(name=scope_name)
    )


def test_filtering_exporter_drops_a2a_scope_keeps_ours():
    inner = _RecordingExporter()
    exp = telemetry._FilteringSpanExporter(inner)
    a2a, ours = _span("a2a-python-sdk"), _span("common.llm")
    result = exp.export([a2a, ours])
    assert result == SpanExportResult.SUCCESS
    assert inner.exported == [[ours]]  # only our span forwarded


def test_filtering_exporter_short_circuits_when_all_dropped():
    inner = _RecordingExporter()
    exp = telemetry._FilteringSpanExporter(inner)
    result = exp.export([_span("a2a-python-sdk")])
    assert result == SpanExportResult.SUCCESS
    assert inner.exported == []  # inner.export never called when nothing remains


def test_filtering_exporter_keeps_span_with_missing_scope():
    inner = _RecordingExporter()
    exp = telemetry._FilteringSpanExporter(inner)
    span = types.SimpleNamespace(instrumentation_scope=None)  # defensive: no scope
    exp.export([span])
    assert inner.exported == [[span]]  # kept, no crash


def test_filtering_exporter_delegates_shutdown_and_flush():
    inner = _RecordingExporter()
    exp = telemetry._FilteringSpanExporter(inner)
    exp.shutdown()
    assert inner.shutdown_called
    assert exp.force_flush(1000) is True
    assert inner.flushed


def test_setup_wraps_exporter_and_registers_flush(monkeypatch):
    # Force the endpoint branch to run again in-process.
    monkeypatch.setattr(telemetry, "_CONFIGURED", False)
    monkeypatch.setenv("OTEL_EXPORTER_OTLP_ENDPOINT", "http://localhost:4318")

    # Stub the OTLP exporter at its import source so no network client is built.
    import opentelemetry.exporter.otlp.proto.http.trace_exporter as otlp_mod
    monkeypatch.setattr(otlp_mod, "OTLPSpanExporter", lambda *a, **k: object())

    # Spy on BatchSpanProcessor to capture the exporter it is constructed with.
    captured = {}

    class _SpyBSP:
        def __init__(self, exporter):
            captured["exporter"] = exporter

    monkeypatch.setattr(telemetry, "BatchSpanProcessor", _SpyBSP)

    # Keep the global provider untouched (avoids OTel "Overriding" warning noise).
    monkeypatch.setattr(telemetry.trace, "set_tracer_provider", lambda provider: None)

    reg = MagicMock()
    monkeypatch.setattr(telemetry.atexit, "register", reg)

    telemetry.setup("svc")

    assert isinstance(captured["exporter"], telemetry._FilteringSpanExporter)
    assert reg.call_count == 1
    assert getattr(reg.call_args[0][0], "__name__", "") == "shutdown"


def test_setup_without_endpoint_registers_no_flush(monkeypatch):
    monkeypatch.setattr(telemetry, "_CONFIGURED", False)
    monkeypatch.delenv("OTEL_EXPORTER_OTLP_ENDPOINT", raising=False)
    monkeypatch.setattr(telemetry.trace, "set_tracer_provider", lambda provider: None)

    reg = MagicMock()
    monkeypatch.setattr(telemetry.atexit, "register", reg)

    telemetry.setup("svc")

    assert reg.call_count == 0  # no flush handler when telemetry is off
