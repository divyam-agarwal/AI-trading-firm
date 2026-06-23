package com.tradingfirm.fundamentals;

import io.opentelemetry.api.OpenTelemetry;
import io.opentelemetry.api.common.AttributeKey;
import io.opentelemetry.api.common.Attributes;
import io.opentelemetry.api.trace.Tracer;
import io.opentelemetry.api.trace.propagation.W3CTraceContextPropagator;
import io.opentelemetry.context.propagation.ContextPropagators;
import io.opentelemetry.exporter.otlp.http.trace.OtlpHttpSpanExporter;
import io.opentelemetry.sdk.OpenTelemetrySdk;
import io.opentelemetry.sdk.resources.Resource;
import io.opentelemetry.sdk.trace.SdkTracerProvider;
import io.opentelemetry.sdk.trace.SdkTracerProviderBuilder;
import io.opentelemetry.sdk.trace.export.BatchSpanProcessor;
import java.util.LinkedHashMap;
import java.util.Map;
import org.springframework.context.annotation.Bean;
import org.springframework.context.annotation.Configuration;

/**
 * OpenTelemetry SDK setup. Mirror of common/telemetry.py: opt-in / no-op.
 * An OTLP exporter is attached ONLY when OTEL_EXPORTER_OTLP_ENDPOINT is set;
 * otherwise spans are created but not exported (negligible overhead).
 */
@Configuration
public class TracingConfig {

    @Bean
    public OpenTelemetry openTelemetry() {
        Resource resource = Resource.getDefault().merge(Resource.create(
                Attributes.of(AttributeKey.stringKey("service.name"), "fundamentals-java")));
        SdkTracerProviderBuilder builder = SdkTracerProvider.builder().setResource(resource);

        String endpoint = System.getenv("OTEL_EXPORTER_OTLP_ENDPOINT");
        if (endpoint != null && !endpoint.isBlank()) {
            String base = endpoint.endsWith("/") ? endpoint.substring(0, endpoint.length() - 1) : endpoint;
            var exporterBuilder = OtlpHttpSpanExporter.builder().setEndpoint(base + "/v1/traces");
            parseHeaders(System.getenv("OTEL_EXPORTER_OTLP_HEADERS")).forEach(exporterBuilder::addHeader);
            OtlpHttpSpanExporter exporter = exporterBuilder.build();
            builder.addSpanProcessor(BatchSpanProcessor.builder(exporter).build());
        }

        return OpenTelemetrySdk.builder()
                .setTracerProvider(builder.build())
                .setPropagators(ContextPropagators.create(W3CTraceContextPropagator.getInstance()))
                .build();
    }

    @Bean
    public Tracer tracer(OpenTelemetry openTelemetry) {
        return openTelemetry.getTracer("fundamentals-java");
    }

    /** Parse OTEL_EXPORTER_OTLP_HEADERS ("k=v,k2=v2") into a header map.
     *  Splits on the first '=' so base64 '=' padding in values is preserved. */
    static Map<String, String> parseHeaders(String raw) {
        Map<String, String> headers = new LinkedHashMap<>();
        if (raw == null || raw.isBlank()) {
            return headers;
        }
        for (String pair : raw.split(",")) {
            int eq = pair.indexOf('=');
            if (eq > 0) {
                headers.put(pair.substring(0, eq).trim(), pair.substring(eq + 1).trim());
            }
        }
        return headers;
    }
}
