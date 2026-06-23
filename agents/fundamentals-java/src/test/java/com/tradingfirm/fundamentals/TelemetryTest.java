package com.tradingfirm.fundamentals;

import io.opentelemetry.api.OpenTelemetry;
import io.opentelemetry.api.trace.Span;
import io.opentelemetry.api.trace.Tracer;
import io.opentelemetry.api.trace.propagation.W3CTraceContextPropagator;
import io.opentelemetry.context.Context;
import io.opentelemetry.context.Scope;
import io.opentelemetry.context.propagation.ContextPropagators;
import io.opentelemetry.sdk.OpenTelemetrySdk;
import io.opentelemetry.sdk.testing.exporter.InMemorySpanExporter;
import io.opentelemetry.sdk.trace.SdkTracerProvider;
import io.opentelemetry.sdk.trace.data.SpanData;
import io.opentelemetry.sdk.trace.export.SimpleSpanProcessor;
import org.junit.jupiter.api.Test;

import java.util.HashMap;
import java.util.Map;

import static org.junit.jupiter.api.Assertions.*;

class TelemetryTest {

    @Test
    void serverSpanContinuesRemoteTrace() {
        InMemorySpanExporter exporter = InMemorySpanExporter.create();
        SdkTracerProvider tp = SdkTracerProvider.builder()
                .addSpanProcessor(SimpleSpanProcessor.create(exporter))
                .build();
        OpenTelemetry otel = OpenTelemetrySdk.builder()
                .setTracerProvider(tp)
                .setPropagators(ContextPropagators.create(W3CTraceContextPropagator.getInstance()))
                .build();
        Tracer tracer = otel.getTracer("test");
        Telemetry telemetry = new Telemetry(otel, tracer);

        // Build a remote carrier exactly like the orchestrator's client span would.
        Span remote = tracer.spanBuilder("orchestrator-client").startSpan();
        Map<String, String> carrier = new HashMap<>();
        try (Scope s = remote.makeCurrent()) {
            otel.getPropagators().getTextMapPropagator()
                    .inject(Context.current(), carrier, (c, k, v) -> c.put(k, v));
        }
        remote.end();
        String remoteTraceId = remote.getSpanContext().getTraceId();
        String remoteSpanId = remote.getSpanContext().getSpanId();

        // Server side: continue the trace from the carrier alone.
        Span server = telemetry.serverSpan("Fundamentals Analyst", carrier);
        assertEquals(remoteTraceId, server.getSpanContext().getTraceId());
        server.end();

        SpanData captured = exporter.getFinishedSpanItems().stream()
                .filter(sd -> sd.getName().equals("Fundamentals Analyst"))
                .findFirst().orElseThrow();
        assertEquals(remoteTraceId, captured.getTraceId());
        assertEquals(remoteSpanId, captured.getParentSpanId());
    }

    @Test
    void tracingConfigBuildsNoopWhenEndpointUnset() {
        // No OTEL_EXPORTER_OTLP_ENDPOINT in the test env -> builds without an exporter, no throw.
        TracingConfig config = new TracingConfig();
        OpenTelemetry otel = config.openTelemetry();
        assertNotNull(otel);
        assertNotNull(config.tracer(otel));
    }
}
