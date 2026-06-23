# Tracing Milestone — Scope C: Langfuse Viewer + Token/Cost

**Date:** 2026-06-23
**Status:** Approved (design) — pending spec review before implementation
**Author:** Divyam
**Milestone:** Tracing, **Scope C — see the cross-language trace tree, with token usage and derived cost, in a self-hosted Langfuse.** Builds on Scope A (Python end-to-end continuation) and Scope B (Java agent in the trace), both merged and pushed. OTel **metrics** and structlog logging are explicitly deferred to a later milestone.

## 1. Purpose & Goal

Scopes A and B made the distributed trace continuous and cross-language (orchestrator root → A2A client span → agent server span → LLM span, one `trace_id`, across Python agents and the Java/Spring agent) — but proven only by in-memory span tests. Nothing yet *renders* the trace, and the LLM spans carry no token/cost data. Scope C delivers the payoff: a **self-hosted Langfuse** that ingests the existing OTLP export and shows the whole trace tree with **per-call token usage, derived cost, latency, and the actual prompt/response** for each LLM generation.

The headline insight: Scopes A and B already built OTLP exporters in both languages (gated on `OTEL_EXPORTER_OTLP_ENDPOINT`), and Langfuse v3 ingests OTLP natively and derives cost from the model id + token counts. So Scope C is mostly (a) adding token-usage and input/output attributes to the LLM spans and (b) standing up Langfuse and pointing the exporters at it with auth — **no Langfuse SDK in either language.**

### Success criterion

Two parts:
1. **Automated (key-free, backend-free):** unit tests assert that each LLM span — Python (`common/llm.py`) and Java (`FundamentalsService`) — carries `gen_ai.usage.input_tokens` and `gen_ai.usage.output_tokens` (from the Anthropic response `usage`) and the input/output text attributes, with a mocked client supplying known usage; and the Java `OTEL_EXPORTER_OTLP_HEADERS` parser maps `Authorization=Basic …` correctly. Existing suites stay green (Python 26, Java 13).
2. **Manual (live verification, D):** a documented runbook — `docker compose up` Langfuse, set the OTLP endpoint + auth env, run `scripts/run_all_java.sh AAPL` — and confirm in the Langfuse UI **one trace** spanning the orchestrator and all agents (incl. the Java agent), with token counts, a derived cost, and the prompt/memo text on each generation.

### Scope (decided during brainstorming)

- **A + B + D:** Langfuse docker viewer + token/cost **and** prompt/response text on the LLM spans (both languages) + live verification.
- **Out:** OTel **metrics** (meters/counters/histograms — a separate OTel API surface), structlog JSON logging, and "debate turns as nested observations" (not applicable: the debate agent is a single LLM call). These are a later milestone.
- Telemetry stays **opt-in / no-op** when `OTEL_EXPORTER_OTLP_ENDPOINT` is unset.

## 2. Approach (decided during brainstorming)

**OTLP-native to a self-hosted Langfuse.** Rejected: the **Langfuse SDKs** (old §10.2 wording) — would add two SDK deps and two new code paths and discard the OTLP exporters Scopes A/B already built. Rejected: a **lightweight viewer (Jaeger)** — shows spans but not token/cost or an LLM-generation view, defeating Scope C's point (kept only as a mental fallback if Langfuse proves too heavy).

- Token usage → OTel GenAI semantic-convention attributes; Langfuse derives cost from `gen_ai.request.model` + the counts.
- Prompt/response text → Langfuse-native input/output attributes (see §4).
- Langfuse authenticated via an `Authorization: Basic <base64(public:secret)>` header on the OTLP export.

## 3. Token & I/O attribute conventions

| Attribute | Value | Set in |
|---|---|---|
| `gen_ai.request.model` | model id (already set in Scopes A/B) | both |
| `gen_ai.usage.input_tokens` | `resp.usage.input_tokens` (Py) / `message.usage().inputTokens()` (Java) | both |
| `gen_ai.usage.output_tokens` | `resp.usage.output_tokens` (Py) / `.outputTokens()` (Java) | both |
| `langfuse.observation.input` | the prompt text sent to the model | both |
| `langfuse.observation.output` | the returned completion text | both |

Token attributes are set as integers; Langfuse maps the `gen_ai.usage.*` keys to usage and computes cost via its model-price table (note: a brand-new model id may need a one-time custom model/price entry in the Langfuse UI — a config step in the runbook, not code). The `langfuse.observation.input/output` keys are Langfuse-native and reliably mapped; the live-verification step (D) confirms the rendering and the keys are adjusted there if Langfuse's mapping differs.

## 4. Components & Boundaries

- **`common/llm.py`** — inside the existing LLM span in `complete()`, after the Anthropic call: set the two `gen_ai.usage.*` attributes from `resp.usage`, and `langfuse.observation.input` = prompt / `langfuse.observation.output` = the returned text. **Best-effort/guarded**: wrapped so a missing or non-numeric `usage` never breaks the call and the existing mocked-client tests (whose `MagicMock` usage is not an int) stay green — only set token attributes when the values are real ints.
- **`agents/fundamentals-java/.../FundamentalsService.java`** — inside the existing LLM span: the same four attributes from `message.usage()` and the prompt/`extractText` result, guarded.
- **`agents/fundamentals-java/.../TracingConfig.java`** — parse `OTEL_EXPORTER_OTLP_HEADERS` (comma-separated `key=value` pairs — the same env var Python's OTLP exporter reads automatically) and `addHeader(...)` on the `OtlpHttpSpanExporter`, inside the existing `endpoint != null && !endpoint.isBlank()` branch. A small static parse helper, unit-tested in isolation.
- **`docker/langfuse/docker-compose.yml`** + **`.env.langfuse.example`** + a runbook — Langfuse's official self-host compose, an env template (public/secret keys, the OTLP endpoint, the `Authorization` header), and step-by-step live-verification instructions.
- **`pyproject.toml`** — remove the now-unused `langfuse` Python dependency (we go OTLP-native; leaving it would mislead a reader into thinking the SDK is used).
- **Python OTLP auth** needs no code change: the HTTP `OTLPSpanExporter` auto-reads `OTEL_EXPORTER_OTLP_HEADERS`.

## 5. Data Flow

```
LLM span "chat <model>"
   +gen_ai.request.model  +gen_ai.usage.input_tokens  +gen_ai.usage.output_tokens
   +langfuse.observation.input (prompt)  +langfuse.observation.output (completion)
        │
        ├─ Python: HTTP OTLPSpanExporter (auto-reads OTEL_EXPORTER_OTLP_HEADERS)
        └─ Java:   OtlpHttpSpanExporter + parsed Authorization header
                                    │
                                    ▼   OTLP /v1/traces  (Authorization: Basic …)
                                 Langfuse  →  one trace tree across orchestrator + Python + Java agents,
                                              with token counts, derived cost, latency, prompt/response
```

## 6. Error Handling / No-op

- Token/IO capture is **best-effort**: guarded so a missing/odd `usage` or a serialization issue never breaks the LLM call or the request.
- Unset `OTEL_EXPORTER_OTLP_ENDPOINT`: exporter not built (Java) / no-op (Python) exactly as today — attributes are still set on the local span (cheap), just not exported. No behavior change for key-free tests or quick runs.
- Langfuse unreachable/down: OTLP export is best-effort (batch processor; failures logged, dropped) and never blocks the agents.

## 7. Testing Strategy

- **Token + I/O attributes (Python):** extend `tests/test_llm.py` — mocked client returns a response with known `usage` (input/output token ints) and a text block; assert the LLM span carries `gen_ai.usage.input_tokens`/`output_tokens` and `langfuse.observation.input`/`output`, and that `complete()` still returns the text. Also assert the guard: a response with no usable `usage` does not break `complete()` (existing tests).
- **Token + I/O attributes (Java):** extend the Java tracing test — mocked `AnthropicClient` whose `Message.usage()` returns known token counts; assert the LLM span carries the same four attributes.
- **Java header parser:** unit-test the `OTEL_EXPORTER_OTLP_HEADERS` → `Map`/headers parser (`"Authorization=Basic abc,X=y"` → two headers; empty/blank → none).
- **Compose syntax:** `docker compose -f docker/langfuse/docker-compose.yml config` parses without error (a cheap structural check; no containers started in CI).
- **Live verification (D):** manual runbook — the only proof that Langfuse renders cost/tree; documented as a checklist, not automated.
- **No regression:** Python 26 + Java 13 (plus the new tests) stay green; suites key-free.

## 8. Files Touched

- `common/llm.py` — token + I/O attributes on the LLM span (guarded).
- `agents/fundamentals-java/src/main/java/com/tradingfirm/fundamentals/FundamentalsService.java` — same four attributes (guarded).
- `agents/fundamentals-java/src/main/java/com/tradingfirm/fundamentals/TracingConfig.java` — parse + attach `OTEL_EXPORTER_OTLP_HEADERS`.
- `docker/langfuse/docker-compose.yml`, `docker/langfuse/.env.langfuse.example`, and a runbook (`docker/langfuse/README.md`).
- `pyproject.toml` — drop the unused `langfuse` dependency.
- `tests/test_llm.py` and the Java tracing test — token/IO attribute tests + the header-parser test.
- `README.md` and `docs/superpowers/specs/2026-06-19-trading-agents-a2a-design.md` §10.2 — update wording: Langfuse is OTLP-native (no Langfuse SDK); token/cost + prompt/response now captured; the docker-compose lives under `docker/langfuse/`.

## 9. Out of Scope (deferred)

- **OTel metrics** (MeterProvider; per-agent request counts, A2A-call durations, LLM token totals) — separate API surface, operational dashboards rather than the trace tree. A later milestone.
- **structlog JSON logging** carrying `trace_id`.
- Automated assertion that Langfuse *renders* cost/tree (inherently a live, manual check).

## 10. Risks & Notes

- **Langfuse v3 compose is heavyweight** (web + worker + postgres + clickhouse + redis + minio). It is the official supported local stack; `docker compose up` handles it, and the app stays fully functional/no-op without it. If it proves impractical on the demo machine, Jaeger is a fallback for *tree-only* viewing (no cost) — not the goal.
- **Langfuse I/O attribute keys:** `langfuse.observation.input/output` are the chosen Langfuse-native keys; the live-verification step confirms rendering and adjusts if Langfuse's OTLP mapping expects different keys. Token/cost via `gen_ai.usage.*` is the well-established mapping.
- **New-model pricing:** Langfuse may not have a built-in price for `claude-sonnet-4-6`/`claude-opus-4-8`; if cost shows as zero, add a custom model+price in the Langfuse UI (runbook note). Token counts render regardless.
- **Anthropic usage accessors:** Python `resp.usage.input_tokens`/`output_tokens` (confirmed present); Java `message.usage().inputTokens()`/`outputTokens()` — pin exact accessors in the plan; the implementer adapts to the resolved SDK as in Scope B.
- **Test-mock fragility:** the existing Python `test_llm.py` mocks use `MagicMock` whose `.usage` is not an int — the guard (only set token attrs when values are real ints) is what keeps those tests green; the new test supplies real int usage.
- **Disclaimer unchanged:** technical demo of agent coordination, not financial advice.
