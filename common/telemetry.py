"""OpenTelemetry + Langfuse setup. No-op when env vars are unset."""
import os
from contextlib import contextmanager

from opentelemetry import trace
from opentelemetry.context import Context
from opentelemetry.propagate import extract as _otel_extract
from opentelemetry.propagate import inject as _otel_inject
from opentelemetry.sdk.resources import Resource
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import BatchSpanProcessor

_CONFIGURED = False


def setup(service_name: str) -> None:
    global _CONFIGURED
    if _CONFIGURED:
        return
    provider = TracerProvider(resource=Resource.create({"service.name": service_name}))
    endpoint = os.getenv("OTEL_EXPORTER_OTLP_ENDPOINT")
    if endpoint:
        from opentelemetry.exporter.otlp.proto.http.trace_exporter import OTLPSpanExporter
        provider.add_span_processor(BatchSpanProcessor(OTLPSpanExporter()))
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
