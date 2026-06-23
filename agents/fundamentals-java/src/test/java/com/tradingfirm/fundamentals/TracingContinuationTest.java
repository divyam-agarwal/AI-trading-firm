package com.tradingfirm.fundamentals;

import com.tradingfirm.fundamentals.dto.A2AMessage;
import com.tradingfirm.fundamentals.dto.JsonRpcRequest;
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
import org.junit.jupiter.api.BeforeEach;
import org.junit.jupiter.api.Test;

import java.util.HashMap;
import java.util.List;
import java.util.Map;

import static org.junit.jupiter.api.Assertions.*;
import static org.mockito.ArgumentMatchers.any;
import static org.mockito.Mockito.mock;
import static org.mockito.Mockito.when;

class TracingContinuationTest {

    private InMemorySpanExporter exporter;
    private OpenTelemetry otel;
    private Tracer tracer;
    private Telemetry telemetry;

    @BeforeEach
    void setUp() {
        exporter = InMemorySpanExporter.create();
        SdkTracerProvider tp = SdkTracerProvider.builder()
                .addSpanProcessor(SimpleSpanProcessor.create(exporter))
                .build();
        otel = OpenTelemetrySdk.builder()
                .setTracerProvider(tp)
                .setPropagators(ContextPropagators.create(W3CTraceContextPropagator.getInstance()))
                .build();
        tracer = otel.getTracer("test");
        telemetry = new Telemetry(otel, tracer);
    }

    /** Build a metadata carrier carrying a remote traceparent, like the orchestrator sends. */
    private Map<String, String> remoteCarrier(String[] outIds) {
        Span remote = tracer.spanBuilder("orchestrator-client").startSpan();
        Map<String, String> carrier = new HashMap<>();
        try (Scope s = remote.makeCurrent()) {
            otel.getPropagators().getTextMapPropagator()
                    .inject(Context.current(), carrier, (c, k, v) -> c.put(k, v));
        }
        remote.end();
        outIds[0] = remote.getSpanContext().getTraceId();
        outIds[1] = remote.getSpanContext().getSpanId();
        return carrier;
    }

    private JsonRpcRequest request(Map<String, String> metadata) {
        return new JsonRpcRequest(
                "SendMessage",
                new JsonRpcRequest.Params(
                        new A2AMessage("m1", "ROLE_USER", List.of(new A2AMessage.Part("AAPL"))),
                        null, metadata),
                "req-1", "2.0");
    }

    @Test
    void serverSpanParentsIntoOrchestratorTrace() {
        String[] ids = new String[2];
        Map<String, String> carrier = remoteCarrier(ids);

        FundamentalsService service = mock(FundamentalsService.class);
        when(service.analyze(any())).thenReturn("ok");
        A2AController controller = new A2AController(service, telemetry);

        controller.rpc(request(carrier));

        SpanData server = exporter.getFinishedSpanItems().stream()
                .filter(s -> s.getName().equals("Fundamentals Analyst"))
                .findFirst().orElseThrow();
        assertEquals(ids[0], server.getTraceId());
        assertEquals(ids[1], server.getParentSpanId());
        assertEquals("Fundamentals Analyst", server.getAttributes().get(
                io.opentelemetry.api.common.AttributeKey.stringKey("agent.name")));
    }
}
