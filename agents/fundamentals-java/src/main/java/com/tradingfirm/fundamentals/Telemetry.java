package com.tradingfirm.fundamentals;

import io.opentelemetry.api.OpenTelemetry;
import io.opentelemetry.api.trace.Span;
import io.opentelemetry.api.trace.Tracer;
import io.opentelemetry.context.Context;
import io.opentelemetry.context.propagation.TextMapGetter;
import org.springframework.stereotype.Component;

import java.util.Map;

/** Extracts remote W3C trace context from a metadata carrier and opens a child span. */
@Component
public class Telemetry {

    private static final TextMapGetter<Map<String, String>> GETTER = new TextMapGetter<>() {
        @Override
        public Iterable<String> keys(Map<String, String> carrier) {
            return carrier.keySet();
        }
        @Override
        public String get(Map<String, String> carrier, String key) {
            return carrier == null ? null : carrier.get(key);
        }
    };

    private final OpenTelemetry openTelemetry;
    private final Tracer tracer;

    public Telemetry(OpenTelemetry openTelemetry, Tracer tracer) {
        this.openTelemetry = openTelemetry;
        this.tracer = tracer;
    }

    /** Best-effort: returns the current context if the carrier is empty or extraction fails. */
    public Context extract(Map<String, String> carrier) {
        if (carrier == null || carrier.isEmpty()) {
            return Context.current();
        }
        try {
            return openTelemetry.getPropagators().getTextMapPropagator()
                    .extract(Context.current(), carrier, GETTER);
        } catch (RuntimeException e) {
            return Context.current();
        }
    }

    public Span serverSpan(String name, Map<String, String> carrier) {
        return tracer.spanBuilder(name).setParent(extract(carrier)).startSpan();
    }
}
