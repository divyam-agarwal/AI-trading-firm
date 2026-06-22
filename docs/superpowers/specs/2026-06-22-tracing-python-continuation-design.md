# Tracing Milestone — Scope A: Python End-to-End Trace Continuation

**Date:** 2026-06-22
**Status:** Approved (design) — pending spec review before implementation
**Author:** Divyam
**Milestone:** Tracing (the "one trace spans all agents" goal), **Scope A — Python end-to-end only**. The Java agent joining the trace (Scope B) and a Langfuse viewer backend (Scope C) are explicitly deferred to follow-up milestones.

## 1. Purpose & Goal

Make distributed tracing across the Python processes **real**. Phase 1 left tracing ~20% built:

- `common/telemetry.py` has `setup()` / `inject()` / `extract()` / `tracer()`, but
- the **orchestrator opens no real root span** (spans exist only in tests), so the client's `inject()` serializes an *empty* context;
- the **server never calls `extract()`** — `common/a2a_server.py` ignores the incoming `traceparent`, so agent-side spans don't attach to the orchestrator's trace (this is Phase-1 deferred item #2);
- Langfuse is a dependency with zero wiring code.

Scope A delivers a continuous trace tree spanning the orchestrator and both Python agents, backend-agnostic (no Docker, no Langfuse), proven by an in-memory span-exporter test.

### Success criterion

An in-process test with an `InMemorySpanExporter` asserts that the **orchestrator root span, the A2A client spans, the agent server spans, and the LLM spans all share one `trace_id`**, with correct parent/child relationships (server span is a child of the client-injected context; LLM span is a child of the server span). The pre-existing 18 tests stay green; the full suite remains key-free.

### Scope (decided during brainstorming)

- **Scope A only.** The Java agent extracting the `traceparent` and emitting spans into the same trace (Scope B), and a Langfuse `docker-compose` viewer with token/cost (Scope C), are **out of scope** here — clean follow-ups that build on this foundation.
- **Standard span tree** (decided): root span + one A2A client span per call + one agent server span per request + one LLM span per `complete()`. **No token/cost capture and no metrics** — those belong to the Langfuse milestone.
- Telemetry stays **opt-in / no-op** when `OTEL_EXPORTER_OTLP_ENDPOINT` is unset (Phase-1 invariant).

## 2. Verified Foundation (de-risked during brainstorming)

The server-side `RequestContext` exposes the incoming metadata map directly as **`context.metadata`**. A probe injected `{"traceparent": "00-0af7651916cd43dd8448eb211c80319c-b7ad6b7169203331-01"}` into the client's `SendMessageRequest.metadata`, and the server's executor saw `context.metadata == {'traceparent': '00-0af7…-01'}` verbatim. So server-side extraction is:

```python
carrier = dict(context.metadata or {})
ctx = telemetry.extract(carrier)   # -> OTel Context with the remote span as parent
```

(`context.call_context.state['headers']` also carries the raw HTTP headers as a fallback, but `context.metadata` is exactly the carrier the client populates — no header parsing needed.)

## 3. Instrumentation Points (the standard tree)

| Span | Where | Name | Key attributes |
|---|---|---|---|
| **Root** | `orchestrator/main.py` — wrap `graph.ainvoke`, made current | `analyze <ticker>` | `ticker` |
| **A2A client** | `orchestrator/a2a_client.py` `call_agent` — around the send; existing `inject()` runs *inside* it | `a2a SendMessage` | `server.url`, `a2a.method="SendMessage"`, optional `agent.name` |
| **Server** | `common/a2a_server.py` `_FunctionExecutor.execute` — child of `extract(context.metadata)`, handler runs inside | server name from the card `name` | `agent.name` |
| **LLM** | `common/llm.py` `complete` — around the Anthropic call | `chat <model>` | `gen_ai.request.model`, latency, status |

Because `complete()` runs inside the agent process within the server span's context, the LLM span becomes a child of the server span, which is a child of the orchestrator's client span — one unbroken trace.

The A2A client span makes the existing `inject()` meaningful: with a span current, the written `traceparent` is non-empty, so the server's `extract()` has something to continue.

## 4. Components & Boundaries

- **`common/telemetry.py` stays the single OTel module.** Add one helper — a context manager `server_span(name, carrier)` that does `extract` + start-as-current child span — so `a2a_server.py` stays thin and the extract/attach mechanics live in one place. Keep `setup`/`inject`/`extract`/`tracer` as-is.
- **SDK isolation preserved.** No new `a2a-sdk` imports anywhere; `context.metadata` is read inside the existing `a2a_server.py` wrapper (an allowed SDK-touching module). `a2a_client.py` already imports `telemetry.inject`.
- **No agent `server.py` changes.** The server-span name derives from the `name` already passed to `build_agent_app`.
- Each instrumentation point is independently understandable: the client span only adds context to the send; the server span only continues the trace and wraps the handler; the LLM span only times the model call.

## 5. Data Flow

```
root(orchestrator: analyze AAPL)
  └─ a2a client span (SendMessage → :9001)   ──traceparent in request.metadata──▶  fundamentals agent process
       server span (child via extract(context.metadata))
         └─ llm span (chat claude-sonnet-4-6)
  └─ a2a client span (SendMessage → :9002)   ──────────────────────────────────▶  sentiment agent process
       server span → llm span
  └─ a2a client span (SendMessage → :9003)   ──────────────────────────────────▶  debate agent process
       server span → llm span (claude-opus-4-8)
```

One `trace_id` throughout; each agent's work parents into the orchestrator's trace.

## 6. Error Handling

- All tracing is **best-effort and must never break request handling**: extraction and span creation are wrapped in `try/except` (mirrors the existing `inject()` try/except in `a2a_client.py`). A telemetry failure logs/ignores and proceeds.
- Spans `record_exception` and set ERROR status when the wrapped operation raises, then re-raise.
- Unset `OTEL_EXPORTER_OTLP_ENDPOINT`: spans are created but not exported (negligible overhead), exactly as today — no behavior change for quick local runs or tests that don't configure an exporter.

## 7. Testing Strategy

- **Trace continuation test** (extends `tests/test_trace_propagation.py` or a new `tests/test_trace_continuation.py`): configure a global `TracerProvider` + `InMemorySpanExporter` (the pattern Phase 1's trace test already uses); open a root span; spin up a **real in-process agent** via `build_agent_app` with a **stub handler (no LLM)**; call `call_agent` within the root span; assert the captured **server span shares the root span's `trace_id`** and its parent is the client-injected context. This is the core proof of server-side continuation.
- **LLM-span unit test**: mock the Anthropic client; assert `complete()` emits a span carrying `gen_ai.request.model` and still returns the text.
- **No regression**: the existing 18 tests stay green; full suite key-free (`python -m pytest -q`).

## 8. Files Touched

- `common/telemetry.py` — add the `server_span(name, carrier)` helper.
- `common/a2a_server.py` — extract `context.metadata` + open the server span in `_FunctionExecutor.execute`.
- `common/llm.py` — LLM span around the Anthropic call in `complete()`.
- `orchestrator/a2a_client.py` — client span around the send in `call_agent` (optional `agent.name` param).
- `orchestrator/main.py` — root span around `graph.ainvoke`.
- `tests/` — the continuation test + LLM-span test.
- `README.md` and `docs/superpowers/specs/2026-06-19-trading-agents-a2a-design.md` §10 — update the "Phase 1 is client-side-injection-only" wording to "Python agents now continue the orchestrator's trace server-side; the Java agent joins the trace in a later milestone."

## 9. Out of Scope (deferred)

- **Scope B — Java agent in the trace:** OTel Java in the Spring Boot agent, extracting the `traceparent` from the A2A request metadata and emitting child spans. The Java agent currently ignores incoming metadata (fine; B handles it).
- **Scope C — Langfuse viewer:** `docker-compose` for Langfuse + OTLP wiring to *see* the trace tree with token/cost, plus OTel metrics (spec §10.3). Token/cost capture on LLM spans lands here, not in Scope A.

## 10. Risks & Notes

- **Context propagation across LangGraph's parallel async nodes:** the root-span context must reach the concurrent `gather_fundamentals` / `gather_sentiment` coroutines so their client spans parent correctly. OTel uses `contextvars`, which asyncio copies into tasks at creation — this is expected to work, but the continuation test explicitly asserts parent/child `trace_id` so any propagation gap is caught, not assumed.
- **`context.metadata` shape:** verified (§2), so the milestone's main unknown is closed.
- **Disclaimer unchanged:** this is a technical demo of agent coordination, not financial advice.
