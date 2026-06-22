import pytest
from opentelemetry import trace
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import SimpleSpanProcessor
from opentelemetry.sdk.trace.export.in_memory_span_exporter import InMemorySpanExporter


@pytest.fixture(scope="session")
def _provider_with_exporter():
    """Attach one InMemorySpanExporter to the global TracerProvider.

    OTel's set_tracer_provider is set-once per process, so we attach our
    exporter to whatever real provider exists (or install one if none does)
    rather than replacing it.
    """
    # OTel's set_tracer_provider is set-once per process: once any provider is
    # installed, later set_tracer_provider calls are silently ignored. So we
    # attach our exporter to whatever global provider exists (installing one
    # only if none is set), which keeps span capture order-independent across
    # the suite.
    provider = trace.get_tracer_provider()
    if not isinstance(provider, TracerProvider):
        provider = TracerProvider()
        trace.set_tracer_provider(provider)
    exporter = InMemorySpanExporter()
    provider.add_span_processor(SimpleSpanProcessor(exporter))
    return exporter


@pytest.fixture
def span_exporter(_provider_with_exporter):
    """Per-test handle to captured spans; cleared at the start of each test."""
    _provider_with_exporter.clear()
    return _provider_with_exporter
