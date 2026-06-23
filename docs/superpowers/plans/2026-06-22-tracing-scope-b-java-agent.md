# Tracing Scope B — Java Agent Joins the Trace Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** The Java/Spring Boot Fundamentals agent extracts the orchestrator's W3C `traceparent` from the inbound A2A message metadata and emits a server span (child of the orchestrator's client span) with a nested LLM span, so the orchestrator → Java-agent → LLM spans share one `trace_id`.

**Architecture:** A manual OpenTelemetry Java SDK layer mirroring `common/telemetry.py`: a `TracingConfig` builds an `OpenTelemetry` SDK (W3C propagator; OTLP exporter only when `OTEL_EXPORTER_OTLP_ENDPOINT` is set, else no-op), and a `Telemetry` helper does `extract(carrier)` + `serverSpan(name, carrier)`. The controller opens the server span from `params.metadata`; the service opens the LLM span around the Anthropic call inside it.

**Tech Stack:** Java 21, Spring Boot 3.3.5 (Web), `anthropic-java` 2.9.0, OpenTelemetry Java SDK (BOM-managed), JUnit 5 + Mockito 5 (Spring Boot test) + `opentelemetry-sdk-testing` `InMemorySpanExporter`.

## Global Constraints

- **Verified wire path:** the orchestrator's injected `traceparent` arrives at **`params.metadata.traceparent`** (a string-keyed map) in the inbound JSON-RPC body. Confirmed empirically during planning. (`params.metadata` also encodes the orchestrator's *client* span, which is what the server span must parent to.)
- **Opt-in / no-op when `OTEL_EXPORTER_OTLP_ENDPOINT` is unset** (same env var and invariant as the Python side). No behavior change for key-free local runs/tests.
- **Best-effort tracing must never break request handling:** extraction is guarded (falls back to current context); spans `recordException` + set `ERROR` status on a thrown operation, then rethrow.
- **Standard span tree only** (parity with Scope A): one server span + one LLM span. **No token/cost capture, no metrics** — those are Scope C.
- **Span naming/attribute parity with Python:** server span = the agent card's `name` (`"Fundamentals Analyst"`) with attribute `agent.name`; LLM span = `chat claude-sonnet-4-6` with attribute `gen_ai.request.model`.
- **Anthropic call shape unchanged:** model `claude-sonnet-4-6`, `maxTokens` 1024, `system`, single user message — no temperature/top_p/top_k/budget_tokens/thinking (these 400 on current models). The span only *wraps* the existing call.
- **No Python changes; no changes to the all-Python path.** The orchestrator already injects toward `:9001`.
- **Public portfolio repo:** keep Claude/AI authorship attribution OUT of commit messages and tracked docs. Strip any `Co-Authored-By` trailer. Naming `claude-sonnet-4-6` / the Anthropic Java SDK as the stack is fine.
- **Key-free tests:** `mvn -f agents/fundamentals-java/pom.xml test` stays green with no `ANTHROPIC_API_KEY` (LLM mocked/stubbed). Baseline is 9 passing; each task adds tests — the binding requirement is *all green + the new test passes*; report the actual count.
- **Test command:** `mvn -f agents/fundamentals-java/pom.xml test`. The Python suite (`.venv/bin/python -m pytest -q`, 26 passing) must remain untouched and green.

## File Structure

- `agents/fundamentals-java/pom.xml` (modify) — add the OTel BOM + `opentelemetry-api`, `opentelemetry-sdk`, `opentelemetry-exporter-otlp`, and `opentelemetry-sdk-testing` (test).
- `agents/fundamentals-java/src/main/java/com/tradingfirm/fundamentals/TracingConfig.java` (create) — OTel SDK setup; OTLP-or-no-op by env; `OpenTelemetry` + `Tracer` beans.
- `.../fundamentals/Telemetry.java` (create) — `extract(Map)` + `serverSpan(name, Map)` helper.
- `.../fundamentals/A2AController.java` (modify) — inject `Telemetry`; open the server span around the handler.
- `.../fundamentals/FundamentalsService.java` (modify) — inject `Tracer`; wrap the Anthropic call in the LLM span; add a `MODEL` constant.
- `.../fundamentals/dto/JsonRpcRequest.java` (modify) — add `Map<String,String> metadata` to `Params`.
- `src/test/java/.../TelemetryTest.java` (create) — `serverSpan` continuation unit test + `TracingConfig` no-op test.
- `src/test/java/.../TracingContinuationTest.java` (create) — server-span continuation (Task 2) + LLM-span nesting (Task 3).
- `src/test/java/.../A2AControllerTest.java` (modify) — `@Import` the OTel beans so the controller's new dependency resolves (also serves as the no-op-safety proof).
- `src/test/java/.../FundamentalsServiceTest.java` (modify) — pass a no-op `Tracer` to the new constructor.
- `README.md` + `docs/superpowers/specs/2026-06-19-trading-agents-a2a-design.md` §10 (modify) — Java agent now in the trace.

---

### Task 1: OTel dependencies + `TracingConfig` + `Telemetry` helper

**Files:**
- Modify: `agents/fundamentals-java/pom.xml`
- Create: `.../fundamentals/TracingConfig.java`, `.../fundamentals/Telemetry.java`
- Test: `src/test/java/com/tradingfirm/fundamentals/TelemetryTest.java`

**Interfaces:**
- Produces:
  - `OpenTelemetry` + `Tracer` Spring beans from `TracingConfig` (`Tracer` named `"fundamentals-java"`; W3C propagator; OTLP exporter only when `OTEL_EXPORTER_OTLP_ENDPOINT` set).
  - `Telemetry` (`@Component`): `Context extract(Map<String,String> carrier)` and `Span serverSpan(String name, Map<String,String> carrier)` (starts a child of the extracted context; best-effort).

- [ ] **Step 1: Confirm the baseline**

Run: `mvn -f agents/fundamentals-java/pom.xml -q test 2>&1 | tail -20`
Expected: existing tests pass (baseline ~9). Note the exact count.

- [ ] **Step 2: Add OTel dependencies to `pom.xml`**

Add a `<dependencyManagement>` block (before `<dependencies>`) importing the OTel BOM, and the four dependencies. Insert into `agents/fundamentals-java/pom.xml`:

```xml
    <dependencyManagement>
        <dependencies>
            <dependency>
                <groupId>io.opentelemetry</groupId>
                <artifactId>opentelemetry-bom</artifactId>
                <version>1.43.0</version>
                <type>pom</type>
                <scope>import</scope>
            </dependency>
        </dependencies>
    </dependencyManagement>
```

And inside `<dependencies>`:

```xml
        <dependency>
            <groupId>io.opentelemetry</groupId>
            <artifactId>opentelemetry-api</artifactId>
        </dependency>
        <dependency>
            <groupId>io.opentelemetry</groupId>
            <artifactId>opentelemetry-sdk</artifactId>
        </dependency>
        <dependency>
            <groupId>io.opentelemetry</groupId>
            <artifactId>opentelemetry-exporter-otlp</artifactId>
        </dependency>
        <dependency>
            <groupId>io.opentelemetry</groupId>
            <artifactId>opentelemetry-sdk-testing</artifactId>
            <scope>test</scope>
        </dependency>
```

Run: `mvn -f agents/fundamentals-java/pom.xml -q dependency:resolve 2>&1 | tail -5`
Expected: resolves cleanly. If `1.43.0` fails to resolve, bump to the latest available `opentelemetry-bom` (mirrors how M3 resolved the `anthropic-java` version) and note it in the report.

- [ ] **Step 3: Write the failing `Telemetry` test**

Create `src/test/java/com/tradingfirm/fundamentals/TelemetryTest.java`:

```java
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

        SpanData captured = exporter.getFinishedSpans().stream()
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
```

- [ ] **Step 4: Run test to verify it fails**

Run: `mvn -f agents/fundamentals-java/pom.xml -q -Dtest=TelemetryTest test 2>&1 | tail -20`
Expected: COMPILE FAILURE — `Telemetry` and `TracingConfig` do not exist yet.

- [ ] **Step 5: Implement `TracingConfig`**

Create `src/main/java/com/tradingfirm/fundamentals/TracingConfig.java`:

```java
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
            OtlpHttpSpanExporter exporter = OtlpHttpSpanExporter.builder()
                    .setEndpoint(base + "/v1/traces")
                    .build();
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
}
```

- [ ] **Step 6: Implement `Telemetry`**

Create `src/main/java/com/tradingfirm/fundamentals/Telemetry.java`:

```java
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
```

- [ ] **Step 7: Run the test to verify it passes**

Run: `mvn -f agents/fundamentals-java/pom.xml -q -Dtest=TelemetryTest test 2>&1 | tail -20`
Expected: 2 tests pass.

- [ ] **Step 8: Run the full Java suite (no regression)**

Run: `mvn -f agents/fundamentals-java/pom.xml -q test 2>&1 | tail -20`
Expected: all green (baseline + 2 new). Report the count.

- [ ] **Step 9: Commit**

```bash
git add agents/fundamentals-java/pom.xml \
        agents/fundamentals-java/src/main/java/com/tradingfirm/fundamentals/TracingConfig.java \
        agents/fundamentals-java/src/main/java/com/tradingfirm/fundamentals/Telemetry.java \
        agents/fundamentals-java/src/test/java/com/tradingfirm/fundamentals/TelemetryTest.java
git commit -m "feat(java-tracing): add OTel SDK setup and a server-span continuation helper"
```

---

### Task 2: Deserialize `metadata` + open the server span in `A2AController`

**Files:**
- Modify: `.../fundamentals/dto/JsonRpcRequest.java`
- Modify: `.../fundamentals/A2AController.java`
- Modify: `src/test/java/.../A2AControllerTest.java`
- Test: `src/test/java/.../TracingContinuationTest.java` (create)

**Interfaces:**
- Consumes: `Telemetry.serverSpan(name, carrier)` (Task 1).
- Produces: `A2AController(FundamentalsService service, Telemetry telemetry)` constructor; every `SendMessage` request opens a server span named `"Fundamentals Analyst"` (attribute `agent.name`) parented to `params.metadata`, with the handler running inside it. `JsonRpcRequest.Params` gains `Map<String,String> metadata`.

- [ ] **Step 1: Add `metadata` to the request DTO**

Replace `src/main/java/com/tradingfirm/fundamentals/dto/JsonRpcRequest.java`:

```java
package com.tradingfirm.fundamentals.dto;

import java.util.Map;

/** Inbound JSON-RPC request. Unknown fields are ignored by Spring's Jackson
 *  (fail-on-unknown-properties is false by default in Spring Boot).
 *  The orchestrator injects the W3C traceparent at params.metadata. */
public record JsonRpcRequest(String method, Params params, String id, String jsonrpc) {
    public record Params(A2AMessage message, Object configuration, Map<String, String> metadata) {}
}
```

- [ ] **Step 2: Write the failing server-span continuation test**

Create `src/test/java/com/tradingfirm/fundamentals/TracingContinuationTest.java`:

```java
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

        SpanData server = exporter.getFinishedSpans().stream()
                .filter(s -> s.getName().equals("Fundamentals Analyst"))
                .findFirst().orElseThrow();
        assertEquals(ids[0], server.getTraceId());
        assertEquals(ids[1], server.getParentSpanId());
        assertEquals("Fundamentals Analyst", server.getAttributes().get(
                io.opentelemetry.api.common.AttributeKey.stringKey("agent.name")));
    }
}
```

- [ ] **Step 3: Run test to verify it fails**

Run: `mvn -f agents/fundamentals-java/pom.xml -q -Dtest=TracingContinuationTest test 2>&1 | tail -20`
Expected: COMPILE FAILURE — `A2AController` has no `(FundamentalsService, Telemetry)` constructor yet.

- [ ] **Step 4: Open the server span in `A2AController`**

Replace `src/main/java/com/tradingfirm/fundamentals/A2AController.java`:

```java
package com.tradingfirm.fundamentals;

import com.tradingfirm.fundamentals.dto.A2AMessage;
import com.tradingfirm.fundamentals.dto.AgentCard;
import com.tradingfirm.fundamentals.dto.JsonRpcRequest;
import com.tradingfirm.fundamentals.dto.JsonRpcResponse;
import io.opentelemetry.api.trace.Span;
import io.opentelemetry.api.trace.StatusCode;
import io.opentelemetry.context.Scope;
import org.springframework.web.bind.annotation.GetMapping;
import org.springframework.web.bind.annotation.PostMapping;
import org.springframework.web.bind.annotation.RequestBody;
import org.springframework.web.bind.annotation.RestController;

import java.util.List;
import java.util.Map;
import java.util.UUID;

@RestController
public class A2AController {

    private static final String AGENT_NAME = AgentCard.fundamentals().name();

    private final FundamentalsService service;
    private final Telemetry telemetry;

    public A2AController(FundamentalsService service, Telemetry telemetry) {
        this.service = service;
        this.telemetry = telemetry;
    }

    @GetMapping("/.well-known/agent-card.json")
    public AgentCard agentCard() {
        return AgentCard.fundamentals();
    }

    @PostMapping("/")
    public JsonRpcResponse rpc(@RequestBody JsonRpcRequest request) {
        if (!"SendMessage".equals(request.method())) {
            return JsonRpcResponse.error(-32601, "Method not found", request.id());
        }
        String text = userText(request);
        Map<String, String> metadata =
                request.params() != null ? request.params().metadata() : null;

        // Continue the orchestrator's trace; the handler runs inside the server span
        // so the LLM span nests under it. Tracing is best-effort.
        Span span = telemetry.serverSpan(AGENT_NAME, metadata);
        span.setAttribute("agent.name", AGENT_NAME);
        String reply;
        try (Scope scope = span.makeCurrent()) {
            reply = service.analyze(text);
        } catch (RuntimeException e) {
            span.recordException(e);
            span.setStatus(StatusCode.ERROR);
            throw e;
        } finally {
            span.end();
        }

        A2AMessage out = new A2AMessage(
                UUID.randomUUID().toString(),
                "ROLE_AGENT",
                List.of(new A2AMessage.Part(reply)));
        return JsonRpcResponse.ok(out, request.id());
    }

    /** Concatenate the text of all parts in the inbound message. */
    private static String userText(JsonRpcRequest request) {
        StringBuilder sb = new StringBuilder();
        if (request.params() != null && request.params().message() != null
                && request.params().message().parts() != null) {
            for (A2AMessage.Part p : request.params().message().parts()) {
                if (p.text() != null) {
                    sb.append(p.text());
                }
            }
        }
        return sb.toString();
    }
}
```

- [ ] **Step 5: Keep `A2AControllerTest` green by importing the OTel beans**

`A2AControllerTest` is a `@WebMvcTest`, which won't pick up `Telemetry`/`TracingConfig` by component scan. Add an `@Import` so the controller's new dependency resolves (the SDK is no-op in tests since the env var is unset — this also serves as the no-op-safety proof). In `src/test/java/com/tradingfirm/fundamentals/A2AControllerTest.java`, add the import and annotation:

Add to the imports:
```java
import org.springframework.context.annotation.Import;
```

Change the class annotation from:
```java
@WebMvcTest(A2AController.class)
class A2AControllerTest {
```
to:
```java
@WebMvcTest(A2AController.class)
@Import({TracingConfig.class, Telemetry.class})
class A2AControllerTest {
```

(No assertions change — the existing `sendMessageReturnsAgentReplyEnvelope` test now also proves the RPC returns the correct reply under live, no-op tracing.)

- [ ] **Step 6: Run the continuation + controller tests**

Run: `mvn -f agents/fundamentals-java/pom.xml -q -Dtest=TracingContinuationTest,A2AControllerTest test 2>&1 | tail -20`
Expected: all pass (continuation server-span test + the 3 controller tests).

- [ ] **Step 7: Run the full Java suite**

Run: `mvn -f agents/fundamentals-java/pom.xml -q test 2>&1 | tail -20`
Expected: all green. Report the count.

- [ ] **Step 8: Commit**

```bash
git add agents/fundamentals-java/src/main/java/com/tradingfirm/fundamentals/dto/JsonRpcRequest.java \
        agents/fundamentals-java/src/main/java/com/tradingfirm/fundamentals/A2AController.java \
        agents/fundamentals-java/src/test/java/com/tradingfirm/fundamentals/A2AControllerTest.java \
        agents/fundamentals-java/src/test/java/com/tradingfirm/fundamentals/TracingContinuationTest.java
git commit -m "feat(java-tracing): extract traceparent from request metadata and open a server span"
```

---

### Task 3: LLM span in `FundamentalsService`

**Files:**
- Modify: `.../fundamentals/FundamentalsService.java`
- Modify: `src/test/java/.../FundamentalsServiceTest.java`
- Test: `src/test/java/.../TracingContinuationTest.java` (add the nesting test)

**Interfaces:**
- Consumes: `Tracer` bean (Task 1); the server span made current by `A2AController` (Task 2).
- Produces: `FundamentalsService(AnthropicClient client, Tracer tracer)` constructor; the Anthropic call is wrapped in an LLM span named `chat claude-sonnet-4-6` (attribute `gen_ai.request.model`), nested under the current span.

- [ ] **Step 1: Write the failing LLM-span nesting test**

Add this test to `src/test/java/com/tradingfirm/fundamentals/TracingContinuationTest.java` (the imports for `mock`/`when`/`any` are already present from Task 2; add the Anthropic + `Message`/`MessageService` imports at the top):

Add imports:
```java
import com.anthropic.client.AnthropicClient;
import com.anthropic.models.messages.Message;
import com.anthropic.services.blocking.MessageService;
```

Add the test method:
```java
    @Test
    void llmSpanNestsUnderServerSpan() {
        String[] ids = new String[2];
        Map<String, String> carrier = remoteCarrier(ids);

        // Mock the Anthropic call chain; empty content -> reply "" (we assert the span tree,
        // not the text). Mockito 5 (Spring Boot 3.3) mocks final classes inline.
        Message message = mock(Message.class);
        when(message.content()).thenReturn(List.of());
        MessageService messages = mock(MessageService.class);
        when(messages.create(any())).thenReturn(message);
        AnthropicClient client = mock(AnthropicClient.class);
        when(client.messages()).thenReturn(messages);

        FundamentalsService service = new FundamentalsService(client, tracer);
        A2AController controller = new A2AController(service, telemetry);

        controller.rpc(request(carrier));

        SpanData server = exporter.getFinishedSpans().stream()
                .filter(s -> s.getName().equals("Fundamentals Analyst"))
                .findFirst().orElseThrow();
        SpanData llm = exporter.getFinishedSpans().stream()
                .filter(s -> s.getName().equals("chat claude-sonnet-4-6"))
                .findFirst().orElseThrow();

        assertEquals(ids[0], server.getTraceId());
        assertEquals(ids[0], llm.getTraceId());
        assertEquals(server.getSpanId(), llm.getParentSpanId());
        assertEquals("claude-sonnet-4-6", llm.getAttributes().get(
                io.opentelemetry.api.common.AttributeKey.stringKey("gen_ai.request.model")));
    }
```

- [ ] **Step 2: Run test to verify it fails**

Run: `mvn -f agents/fundamentals-java/pom.xml -q -Dtest=TracingContinuationTest test 2>&1 | tail -25`
Expected: COMPILE FAILURE — `FundamentalsService` has no `(AnthropicClient, Tracer)` constructor; once compiling, the `chat claude-sonnet-4-6` span is absent.

(If Mockito cannot mock `Message`/`MessageService` due to type finality or an overloaded `create`, build a real `Message` via its builder, or use `mock(AnthropicClient.class, RETURNS_DEEP_STUBS)` + `when(client.messages().create(any())).thenReturn(message)`. Note the chosen approach in the report.)

- [ ] **Step 3: Wrap the Anthropic call in an LLM span**

Replace `src/main/java/com/tradingfirm/fundamentals/FundamentalsService.java`:

```java
package com.tradingfirm.fundamentals;

import com.anthropic.client.AnthropicClient;
import com.anthropic.models.messages.Message;
import com.anthropic.models.messages.MessageCreateParams;
import io.opentelemetry.api.trace.Span;
import io.opentelemetry.api.trace.StatusCode;
import io.opentelemetry.api.trace.Tracer;
import io.opentelemetry.context.Scope;
import org.springframework.context.annotation.Lazy;
import org.springframework.stereotype.Service;

@Service
public class FundamentalsService {

    public static final String SYSTEM =
            "You are a fundamentals analyst. Be concise. This is a technical demo, not financial advice.";

    static final String MODEL = "claude-sonnet-4-6";

    private final AnthropicClient client;
    private final Tracer tracer;

    public FundamentalsService(@Lazy AnthropicClient client, Tracer tracer) {
        this.client = client;
        this.tracer = tracer;
    }

    public String analyze(String ticker) {
        FundamentalsData.Facts facts = FundamentalsData.load(ticker);
        if (stubEnabled()) {
            return "[stub] Fundamentals summary for " + facts.ticker()
                    + ": valuation neutral. Demo only, not financial advice.";
        }
        String prompt = buildPrompt(facts);
        // Minimal request: model + maxTokens + system + user message ONLY.
        // No temperature/top_p/top_k/budget_tokens/thinking (these 400 on current models).
        MessageCreateParams params = MessageCreateParams.builder()
                .model(MODEL)
                .maxTokens(1024L)
                .system(SYSTEM)
                .addUserMessage(prompt)
                .build();
        Span span = tracer.spanBuilder("chat " + MODEL).startSpan();
        span.setAttribute("gen_ai.request.model", MODEL);
        try (Scope scope = span.makeCurrent()) {
            Message message = client.messages().create(params);
            return extractText(message);
        } catch (RuntimeException e) {
            span.recordException(e);
            span.setStatus(StatusCode.ERROR);
            throw e;
        } finally {
            span.end();
        }
    }

    String buildPrompt(FundamentalsData.Facts f) {
        String facts = String.format(
                "{'ticker': '%s', 'pe_ratio': %s, 'revenue_growth': %s, 'debt_to_equity': %s, 'fcf_yield': %s}",
                f.ticker(), f.peRatio(), f.revenueGrowth(), f.debtToEquity(), f.fcfYield());
        return "Given these fundamentals for " + f.ticker() + ": " + facts + ". "
                + "Summarize the valuation picture in 3-4 sentences and state whether fundamentals "
                + "look attractive, neutral, or expensive.";
    }

    private static boolean stubEnabled() {
        String v = System.getenv("FUNDAMENTALS_LLM_STUB");
        return "1".equals(v) || "true".equalsIgnoreCase(v);
    }

    /**
     * Concatenate the text of all text blocks in the response.
     * ContentBlock.text() returns Optional<TextBlock>; TextBlock.text() returns String directly.
     */
    private static String extractText(Message message) {
        StringBuilder sb = new StringBuilder();
        message.content().forEach(block ->
                block.text().ifPresent(t -> sb.append(t.text())));
        return sb.toString();
    }
}
```

- [ ] **Step 4: Fix the existing `FundamentalsServiceTest` constructor calls**

`FundamentalsServiceTest` constructs the service with a single null arg. Update it to pass a no-op `Tracer`. In `src/test/java/com/tradingfirm/fundamentals/FundamentalsServiceTest.java`:

Add the import:
```java
import io.opentelemetry.api.OpenTelemetry;
```

Change:
```java
    private final FundamentalsService service = new FundamentalsService(null);
```
to:
```java
    private final FundamentalsService service =
            new FundamentalsService(null, OpenTelemetry.noop().getTracer("test"));
```

- [ ] **Step 5: Run the affected tests**

Run: `mvn -f agents/fundamentals-java/pom.xml -q -Dtest=TracingContinuationTest,FundamentalsServiceTest test 2>&1 | tail -25`
Expected: all pass (server-span + LLM-nesting continuation tests; both service prompt tests).

- [ ] **Step 6: Run the full Java suite**

Run: `mvn -f agents/fundamentals-java/pom.xml -q test 2>&1 | tail -20`
Expected: all green. Report the count.

- [ ] **Step 7: Commit**

```bash
git add agents/fundamentals-java/src/main/java/com/tradingfirm/fundamentals/FundamentalsService.java \
        agents/fundamentals-java/src/test/java/com/tradingfirm/fundamentals/FundamentalsServiceTest.java \
        agents/fundamentals-java/src/test/java/com/tradingfirm/fundamentals/TracingContinuationTest.java
git commit -m "feat(java-tracing): emit an LLM span around the Anthropic call"
```

---

### Task 4: Update docs (README + design spec §10)

**Files:**
- Modify: `README.md:15`
- Modify: `docs/superpowers/specs/2026-06-19-trading-agents-a2a-design.md` (§10.1, second bullet)

**Interfaces:** None (documentation only).

- [ ] **Step 1: Update README**

In `README.md`, replace the Observability bullet (line 15):

Old:
```
- **Observability** — distributed tracing (OpenTelemetry) and LLM observability (Langfuse). The Python orchestrator and both Python agents share one trace: the orchestrator opens a root span, injects W3C trace context into each A2A call, and the agent servers extract it and parent their server and LLM spans into the same trace. The Java/Spring agent joining the trace, plus a Langfuse viewer with token/cost, land in later milestones.
```

New:
```
- **Observability** — distributed tracing (OpenTelemetry) and LLM observability (Langfuse). The orchestrator and all agents — Python and the Java/Spring agent — share one trace: the orchestrator opens a root span and injects W3C trace context into each A2A call, and every agent server (including the Java agent via the OpenTelemetry Java SDK) extracts it from the message metadata and parents its server and LLM spans into the same trace. A Langfuse viewer with token/cost lands in a later milestone.
```

- [ ] **Step 2: Update the design spec §10.1**

In `docs/superpowers/specs/2026-06-19-trading-agents-a2a-design.md`, replace the second bullet of §10.1:

Old:
```
- **W3C `traceparent` context is propagated across A2A boundaries and continued server-side (Python agents).** The orchestrator opens a root span and injects trace context into outgoing A2A message metadata (best-effort); each Python agent server extracts it from the request metadata and starts its server span (and the nested LLM span) as children, so the orchestrator → Python-agent → LLM spans form one trace tree. The Java/Spring agent extracting the `traceparent` and emitting spans into the same trace is a follow-up milestone (Scope B).
```

New:
```
- **W3C `traceparent` context is propagated across A2A boundaries and continued server-side by every agent — Python and Java.** The orchestrator opens a root span and injects trace context into outgoing A2A message metadata (best-effort); each agent server extracts it from the request metadata (`params.metadata`) and starts its server span (and the nested LLM span) as children. The Python agents use `common/telemetry.py`; the Java/Spring agent uses the OpenTelemetry Java SDK (manual extraction, since the `traceparent` rides in the message body, not HTTP headers). So the orchestrator → agent → LLM spans form one trace tree spanning both languages. A Langfuse viewer with token/cost (Scope C) is a follow-up.
```

- [ ] **Step 3: Verify the Java suite is still green and the Python suite untouched**

Run: `mvn -f agents/fundamentals-java/pom.xml -q test 2>&1 | tail -5 && .venv/bin/python -m pytest -q 2>&1 | tail -1`
Expected: Java all green; Python `26 passed`.

- [ ] **Step 4: Commit**

```bash
git add README.md docs/superpowers/specs/2026-06-19-trading-agents-a2a-design.md
git commit -m "docs: the Java agent now continues the orchestrator trace server-side"
```

---

## Final verification (after all tasks)

- [ ] `mvn -f agents/fundamentals-java/pom.xml test` → all green, no `ANTHROPIC_API_KEY` set.
- [ ] `.venv/bin/python -m pytest -q` → `26 passed` (Python untouched).
- [ ] `git log --oneline` shows no `Co-Authored-By` / AI-attribution trailers.
- [ ] `grep -rn "import a2a\|from a2a" common/ orchestrator/` shows a2a-sdk imports only in `common/a2a_server.py` and `orchestrator/a2a_client.py` (unchanged; the Java agent never used a2a-sdk).
- [ ] (Optional, needs key + a running OTLP/Langfuse backend — really Scope C) Live run: `set -a; source .env; set +a; OTEL_EXPORTER_OTLP_ENDPOINT=<endpoint> ./scripts/run_all_java.sh AAPL` and confirm one trace spans the orchestrator and the Java agent.

## Self-Review (completed by plan author)

**Spec coverage:** §2 manual OTel SDK → Task 1. §4 instrumentation points: server span → Task 2, LLM span → Task 3. §5 components (`TracingConfig`, `Telemetry`, controller, service, `Params.metadata`) → Tasks 1–3. §7 error handling (best-effort guard, recordException + ERROR + rethrow, no-op when env unset) → built into `Telemetry.extract`, the controller, and the service span. §8 testing (continuation test, LLM nesting, no-op safety, no regression) → Tasks 1–3 (no-op safety is the `@Import`'d `A2AControllerTest`). §9 files touched → all mapped. §1 success criterion (server + LLM spans share the remote trace_id with correct parents) → Task 3's `llmSpanNestsUnderServerSpan` + Task 2's `serverSpanParentsIntoOrchestratorTrace`. §3 verified wire path → folded into Global Constraints (no probe task needed; verified during planning).

**Placeholder scan:** No TBD/TODO/"handle edge cases"; every code step shows full code; every run step has an exact command + expected output. The one judgment call (Mockito mocking of the Anthropic chain) ships with a concrete primary approach plus a named fallback.

**Type consistency:** `Telemetry(OpenTelemetry, Tracer)` with `extract(Map<String,String>)`/`serverSpan(String, Map<String,String>)`; `A2AController(FundamentalsService, Telemetry)`; `FundamentalsService(AnthropicClient, Tracer)` with `MODEL = "claude-sonnet-4-6"`; server span `"Fundamentals Analyst"` (= `AgentCard.fundamentals().name()`) + `agent.name`; LLM span `"chat claude-sonnet-4-6"` + `gen_ai.request.model`; `JsonRpcRequest.Params(A2AMessage, Object, Map<String,String>)` — used consistently across tasks and tests.
