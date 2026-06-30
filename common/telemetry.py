"""OpenTelemetry + Langfuse setup. No-op when env vars are unset."""
import os
from contextlib import contextmanager

from opentelemetry import trace
from opentelemetry.context import Context
from opentelemetry.propagate import extract as _otel_extract
from opentelemetry.propagate import inject as _otel_inject
from opentelemetry.sdk.resources import Resource
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import BatchSpanProcessor, SpanExporter, SpanExportResult

_CONFIGURED = False

# The a2a-sdk instruments itself with OpenTelemetry under this single scope name
# (its INSTRUMENTING_MODULE_NAME), emitting a2a.server.* / a2a.client.* spans that
# form stray traces. Our own spans use module-name scopes, so an exact-match drop
# here never touches them.
SUPPRESSED_SCOPES = frozenset({"a2a-python-sdk"})


def _scope_name(span) -> "str | None":
    scope = getattr(span, "instrumentation_scope", None)
    return getattr(scope, "name", None) if scope is not None else None


class _FilteringSpanExporter(SpanExporter):
    """Wrap a SpanExporter, dropping spans whose instrumentation scope is in
    SUPPRESSED_SCOPES before delegating the rest."""

    def __init__(self, inner: SpanExporter) -> None:
        self._inner = inner

    def export(self, spans):
        kept = [s for s in spans if _scope_name(s) not in SUPPRESSED_SCOPES]
        if not kept:
            return SpanExportResult.SUCCESS
        return self._inner.export(kept)

    def shutdown(self):
        return self._inner.shutdown()

    def force_flush(self, timeout_millis: int = 30_000) -> bool:
        return self._inner.force_flush(timeout_millis)


def setup(service_name: str) -> None:
    global _CONFIGURED
    if _CONFIGURED:
        return
    provider = TracerProvider(resource=Resource.create({"service.name": service_name}))
    endpoint = os.getenv("OTEL_EXPORTER_OTLP_ENDPOINT")
    if endpoint:
        from opentelemetry.exporter.otlp.proto.http.trace_exporter import OTLPSpanExporter
        # Wrap the OTLP exporter to drop the a2a-sdk's self-instrumentation noise.
        # (OTel's TracerProvider already registers an atexit flush by default, so no
        # explicit flush handler is needed here.)
        exporter = _FilteringSpanExporter(OTLPSpanExporter())
        provider.add_span_processor(BatchSpanProcessor(exporter))
    trace.set_tracer_provider(provider)
    _CONFIGURED = True


def tracer(name: str) -> trace.Tracer:
    return trace.get_tracer(name)


def inject(carrier: dict) -> dict:
    _otel_inject(carrier)
    return carrier


def extract(carrier: dict) -> Context:
    return _otel_extract(carrier)


@contextmanager
def server_span(name: str, carrier: dict):
    """Continue a remote trace: extract context from *carrier* and run the
    enclosed block inside a child span made current.

    Best-effort: if extraction fails the block still runs (under a new span).
    Exceptions raised inside the block are recorded on the span and re-raised.
    """
    try:
        ctx = _otel_extract(carrier or {})
    except Exception:
        ctx = None
    with trace.get_tracer(__name__).start_as_current_span(name, context=ctx) as span:
        try:
            yield span
        except Exception as exc:
            span.record_exception(exc)
            span.set_status(trace.Status(trace.StatusCode.ERROR, str(exc)))
            raise
