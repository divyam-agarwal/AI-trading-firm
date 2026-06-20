"""OpenTelemetry + Langfuse setup. No-op when env vars are unset."""
import os

from opentelemetry import context as otel_context
from opentelemetry import trace
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


def tracer(name: str):
    return trace.get_tracer(name)


def inject(carrier: dict) -> dict:
    _otel_inject(carrier)
    return carrier


def extract(carrier: dict):
    return _otel_extract(carrier)
