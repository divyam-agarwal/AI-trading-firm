# Tracing Milestone — Scope B: Java Agent Joins the Trace

**Date:** 2026-06-22
**Status:** Approved (design) — pending spec review before implementation
**Author:** Divyam
**Milestone:** Tracing, **Scope B — the Java/Spring Boot Fundamentals agent extracts the orchestrator's `traceparent` and emits its own spans into the same trace.** Builds directly on Scope A (Python end-to-end continuation, merged). The Langfuse viewer + token/cost + metrics (Scope C) remain deferred.

## 1. Purpose & Goal

Scope A made distributed tracing continuous across the **Python** processes (orchestrator root span → A2A client span → Python agent server span → LLM span, one `trace_id`). The **Java/Spring Boot Fundamentals agent** (`agents/fundamentals-java/`, port 9001) currently ignores the incoming W3C trace context, so when it replaces the Python Fundamentals agent (the M3 interop swap), its work does **not** appear in the orchestrator's trace.

Scope B closes that gap: the Java agent **extracts** the `traceparent` from the inbound A2A message metadata and emits a **server span** (child of the orchestrator's client span) with a **nested LLM span** around the Anthropic call — so the orchestrator → Java-agent → LLM spans form one unbroken trace. This is the cross-tech-coordination money-shot for the tracing milestone: one trace spanning a Python orchestrator and a Java agent.

### Success criterion

A Java in-process test using OpenTelemetry's `InMemorySpanExporter` asserts that, given an inbound request whose metadata carries a known remote `traceparent`, the **Java server span and LLM span share that remote `trace_id`**, with correct parent/child relationships (server span's parent is the remote span; LLM span's parent is the server span). The pre-existing Java tests stay green; the Java suite remains key-free (LLM mocked/stubbed). Live cross-process viewing in a real backend is **deferred to Scope C**.

### Why message metadata, not HTTP headers (context)

The orchestrator injects `traceparent` into the **A2A message metadata** (`SendMessageRequest.metadata`), which the a2a-sdk serializes into the JSON-RPC body at `params.metadata` — established in Phase 1's client-side injection. This is the A2A protocol's first-class extension point for cross-cutting context: it is transport-agnostic (survives a JSON-RPC→gRPC binding swap) and keeps trace plumbing inside the A2A abstraction / SDK-wrapper modules. The consequence — and the reason Scope B is non-trivial — is that **standard OTel HTTP auto-instrumentation keys off the `traceparent` *header*, which is not sent.** So the Java agent must read the body metadata and re-parent manually, exactly as the Python server reads `context.metadata`.

## 2. Approach (decided during brainstorming)

**Manual OpenTelemetry Java SDK — the direct mirror of `common/telemetry.py`.** Rejected alternatives: the OTel `-javaagent` and `opentelemetry-spring-boot-starter` both auto-create an HTTP server span from request *headers* (absent here), yielding a disconnected root, and would *still* require custom body extraction — more moving parts for no benefit over the ~one config class the manual approach needs.

- Backend-agnostic, **opt-in / no-op when `OTEL_EXPORTER_OTLP_ENDPOINT` is unset** (same env var and invariant as Python).
- **Standard span tree** (parity with Scope A): one server span per request + one LLM span per Anthropic call. **No token/cost capture, no metrics** — those are Scope C.
- **No Python changes:** the orchestrator already injects `traceparent` toward every agent including the Java one on `:9001`. **No changes to the all-Python path.**

## 3. The de-risked / to-be-verified foundation

Scope A's analogous unknown ("does `context.metadata` carry the traceparent?") was verified by a probe before building. Scope B's main unknown is the JSON-RPC wire path: the orchestrator's injected `traceparent` is expected at **`params.metadata.traceparent`** in the inbound request body. Reasoning: the a2a-sdk maps `SendMessageRequest.metadata` (the field Phase-1 injection populates, and the source of the Python server's `context.metadata`) to `params.metadata` in the JSON-RPC payload. Confidence is high, but **the plan's first task is a probe**: capture the raw inbound JSON-RPC body from one real orchestrator→Java call (e.g. temporary logging or a captured request) and confirm the `traceparent` key and its path/casing. If it differs, the `JsonRpcRequest.Params.metadata` mapping is adjusted accordingly before any span code is built on it.

## 4. Instrumentation Points (the standard tree)

| Span | Where | Name | Key attributes |
|---|---|---|---|
| **Server** | `A2AController.rpc` — extract `params.metadata`, open as child, run handler inside | `fundamentals` | `agent.name` |
| **LLM** | `FundamentalsService.analyze` — around `client.messages().create(...)` | `chat claude-sonnet-4-6` | `gen_ai.request.model` |

Because `analyze()` runs inside the server span's scope, the LLM span becomes a child of the server span, which is a child of the orchestrator's client span (via the extracted remote context) — one unbroken trace. Span names and the `gen_ai.request.model` / `agent.name` attribute keys match the Python side for a consistent trace tree.

## 5. Components & Boundaries

Each unit is small, single-responsibility, and independently testable:

- **`TracingConfig`** (`@Configuration`) — the single place OTel SDK setup lives (mirrors `telemetry.setup()`). Builds an `OpenTelemetry` SDK with an `SdkTracerProvider` (resource `service.name = "fundamentals-java"`, W3C `TraceContextPropagator`); attaches a `BatchSpanProcessor` + OTLP span exporter **only when `OTEL_EXPORTER_OTLP_ENDPOINT` is set**, else no exporter (no-op). Exposes `OpenTelemetry` / `Tracer` beans.
- **`Telemetry`** helper — `Context extract(Map<String,String> carrier)` (propagator + a `TextMapGetter` over the map) and `serverSpan(name, metadata)` that starts a child span of the extracted context and makes it current. Mirror of `server_span`. Best-effort: extraction failure falls back to current/empty context.
- **`A2AController`** — reads `request.params().metadata()`, opens the server span via the helper, runs `service.analyze(text)` inside its scope, closes the span. SDK isolation note: this is plain Spring MVC (the Java agent does not use the Python a2a-sdk), so reading metadata here introduces no new coupling.
- **`FundamentalsService`** — wraps the existing `client.messages().create(params)` in the LLM span. The Anthropic request shape is **unchanged** (`claude-sonnet-4-6`, `maxTokens` 1024, `system`, single user message — no temperature/thinking/etc.). In stub mode (`FUNDAMENTALS_LLM_STUB`) there is no Anthropic call, hence no LLM span — consistent with Python stub handlers that never call `complete()`.
- **`JsonRpcRequest.Params`** — add `Map<String,String> metadata` so Jackson deserializes it (currently dropped as an unknown field).

## 6. Data Flow

```
orchestrator client span ──traceparent in params.metadata──▶ A2AController.rpc (Java :9001)
  extract(params.metadata) → remote context
  server span "fundamentals"              [agent.name]        (child of remote context)
    FundamentalsService.analyze
      llm span "chat claude-sonnet-4-6"    [gen_ai.request.model]  (child of server span)
        AnthropicClient.messages().create(...)
```

One `trace_id` continuous from the Python orchestrator through the Java agent and its LLM call.

## 7. Error Handling

- All tracing is **best-effort and must never break request handling.** Metadata extraction and span creation are wrapped in try/catch; a telemetry failure is ignored and the RPC proceeds (mirrors the Python `inject`/`server_span` guards).
- Spans `recordException` and set `ERROR` status when the wrapped operation throws, then rethrow — so the controller's existing JSON-RPC/error behavior is unchanged.
- Unset `OTEL_EXPORTER_OTLP_ENDPOINT`: spans are created but not exported (negligible overhead), no behavior change for quick local runs or key-free tests.

## 8. Testing Strategy

- Add `opentelemetry-sdk-testing` (test scope) for `InMemorySpanExporter`, and an OTel SDK build/exporter that tests can install.
- **Continuation test** (the core proof): build a `Tracer` wired to an `InMemorySpanExporter`; create a "remote" parent span and inject its context into a `Map<String,String>` carrier via the W3C propagator; drive the controller (or the extract + `serverSpan` helper + a mocked-LLM `analyze`) with that metadata; assert (a) the **server span shares the remote `trace_id`** and its parent is the remote span, and (b) with a **mocked `AnthropicClient`** returning a canned `Message`, the **LLM span is a child of the server span** and shares the `trace_id`. Mirrors Scope A's `test_trace_continuation.py` + `test_llm_span_nests_under_server_span`.
- **No-op safety test:** with no exporter configured (env unset), `rpc` still returns the correct reply text — tracing does not break handling.
- **No regression:** the existing Java tests stay green (`mvn -f agents/fundamentals-java/pom.xml test`); suite key-free (mock/stub, no `ANTHROPIC_API_KEY`).

## 9. Files Touched

- `agents/fundamentals-java/pom.xml` — add OTel deps: `opentelemetry-api`, `opentelemetry-sdk`, `opentelemetry-exporter-otlp`, `opentelemetry-sdk-testing` (test). (Use the OTel BOM for version alignment.)
- New: `TracingConfig.java` (SDK setup, OTLP-or-no-op) and `Telemetry.java` (extract + serverSpan helper).
- `A2AController.java` — extract metadata + open the server span around the handler.
- `FundamentalsService.java` — LLM span around the Anthropic call.
- `dto/JsonRpcRequest.java` — add `Map<String,String> metadata` to `Params`.
- `src/main/resources/application.properties` — optional OTel/service-name config (only if needed; env var drives behavior).
- Tests: the continuation test + no-op safety test (new test class, e.g. `TracingContinuationTest`); extend `A2AControllerTest` only if needed.
- `README.md` and `docs/superpowers/specs/2026-06-19-trading-agents-a2a-design.md` §10 — update the wording from "the Java agent joins the trace in a later milestone" to "the Java agent now extracts the `traceparent` and emits spans into the same trace."

## 10. Out of Scope (deferred)

- **Scope C — Langfuse viewer + token/cost + metrics:** `docker-compose` for Langfuse + OTLP wiring to *see* the trace tree, token/cost capture on the LLM spans (both Python and Java), and OTel metrics (design spec §10.3). Live cross-process verification of the trace tree lands here.
- No Python/orchestrator changes; no changes to the all-Python path.

## 11. Risks & Notes

- **Wire-path verification (§3):** the one real unknown; closed by the plan's first probe task before span code is written.
- **OTel SDK global vs. injected instance:** prefer a Spring-managed `OpenTelemetry`/`Tracer` bean over `GlobalOpenTelemetry` where practical, so tests can install an in-memory provider without process-global state leaking across tests (the Java analogue of Scope A's set-once provider care). The continuation test drives the same code path the live agent uses.
- **`claude-api` guardrail:** the Anthropic Java SDK call is only *wrapped* in a span; its request shape is unchanged. No new SDK call patterns are introduced.
- **Disclaimer unchanged:** this is a technical demo of agent coordination, not financial advice.
