# Tracing Scope C — Langfuse Viewer + Token/Cost Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Surface per-call token usage and prompt/response text on the LLM spans (Python and Java), authenticate the Java OTLP exporter, and ship a self-hosted Langfuse docker-compose + runbook so the cross-language trace tree renders with token counts and derived cost.

**Architecture:** Add OTel GenAI-semantic-convention attributes (`gen_ai.usage.input_tokens`/`output_tokens`) plus Langfuse-native I/O attributes (`langfuse.observation.input`/`output`) to the existing LLM spans, best-effort/guarded. Extend the Java `TracingConfig` to parse `OTEL_EXPORTER_OTLP_HEADERS` and attach an `Authorization` header to the OTLP exporter (Python's exporter auto-reads that env var). Vendor Langfuse's official self-host docker-compose + a runbook for live verification.

**Tech Stack:** Python 3.13 (anthropic SDK, OpenTelemetry), Java 21 / Spring Boot 3.3.5 (anthropic-java 2.9.0, OpenTelemetry Java SDK 1.43.0), Langfuse v3 self-hosted via Docker Compose, pytest + JUnit 5/Mockito, `InMemorySpanExporter`.

## Global Constraints

- **Best-effort tracing must never break request handling:** token/IO capture is guarded so a missing/non-numeric `usage` (or any serialization issue) never breaks the LLM call. Only set the integer token attributes when the values are real ints/longs.
- **Opt-in / no-op when `OTEL_EXPORTER_OTLP_ENDPOINT` is unset:** attributes are still set on the local span (cheap), just not exported. No behavior change for key-free tests or quick runs. The Java auth header is attached only inside the existing "endpoint set" branch.
- **Attribute keys (exact, both languages):** `gen_ai.request.model` (already set), `gen_ai.usage.input_tokens`, `gen_ai.usage.output_tokens`, `langfuse.observation.input` (prompt text), `langfuse.observation.output` (completion text).
- **Anthropic call shape unchanged:** Python `claude-sonnet-4-6`/`claude-opus-4-8`, `max_tokens` as-is; Java `claude-sonnet-4-6`, `maxTokens(1024L)`, `system`, single user message. No temperature/top_p/top_k/budget_tokens/thinking. The spans only *read* the response and *wrap* the existing call.
- **Java agent must NOT import a2a-sdk.** No new SDK dependencies in either language (we go OTLP-native; no Langfuse SDK).
- **Public portfolio repo:** keep Claude/AI authorship attribution OUT of commit messages and tracked docs. Strip any `Co-Authored-By`. Naming `claude-sonnet-4-6`/`claude-opus-4-8`/Anthropic SDK/OpenTelemetry as the stack is fine.
- **Key-free tests:** `.venv/bin/python -m pytest -q` (baseline 26) and `mvn -f agents/fundamentals-java/pom.xml test` (baseline 13) stay green with no `ANTHROPIC_API_KEY`. Each task adds tests — the binding requirement is *all green + the new test passes*; report the actual count.
- **OTel Java InMemorySpanExporter uses `getFinishedSpanItems()`** (not `getFinishedSpans()`).
- **Commands:** `python` is NOT on PATH — use `.venv/bin/python`. Java: `mvn -f agents/fundamentals-java/pom.xml test` (~30-60s; be patient, no short timeouts).

## File Structure

- `common/llm.py` (modify) — guarded token + I/O attributes on the LLM span.
- `agents/fundamentals-java/.../FundamentalsService.java` (modify) — same four attributes, guarded.
- `agents/fundamentals-java/.../TracingConfig.java` (modify) — parse `OTEL_EXPORTER_OTLP_HEADERS` + `addHeader` on the exporter.
- `docker/langfuse/docker-compose.yml` (create, vendored) + `docker/langfuse/.env.langfuse.example` (create) + `docker/langfuse/README.md` (create, runbook).
- `pyproject.toml` (modify) — drop the unused `langfuse` dependency.
- `tests/test_llm.py` (modify) — Python token/IO attribute test.
- `agents/fundamentals-java/.../TracingContinuationTest.java` (modify) — Java token/IO attribute test.
- `agents/fundamentals-java/.../TracingConfigTest.java` (create) — header-parser unit test.
- `README.md` + `docs/superpowers/specs/2026-06-19-trading-agents-a2a-design.md` §10.2 (modify) — wording.

---

### Task 1: Python token + I/O attributes on the LLM span

**Files:**
- Modify: `common/llm.py`
- Test: `tests/test_llm.py`

**Interfaces:**
- Produces: `complete()` sets `langfuse.observation.input` (the prompt), and after the call `langfuse.observation.output` (the returned text), `gen_ai.usage.input_tokens`, `gen_ai.usage.output_tokens` (only when `resp.usage.input_tokens`/`output_tokens` are real ints). Return value unchanged.

- [ ] **Step 1: Write the failing test**

Add to `tests/test_llm.py`:

```python
def test_complete_records_usage_and_io(span_exporter):
    fake_block = MagicMock(type="text", text="the memo")
    fake_resp = MagicMock(content=[fake_block])
    # Real ints for usage so the guard sets them; MagicMock would be skipped.
    fake_resp.usage = MagicMock(input_tokens=12, output_tokens=34)
    fake_client = MagicMock()
    fake_client.messages.create.return_value = fake_resp

    with patch.object(llm, "_client", return_value=fake_client):
        out = llm.complete("the prompt", model=llm.MODEL_ANALYST)

    assert out == "the memo"
    span = next(s for s in span_exporter.get_finished_spans()
                if s.name == f"chat {llm.MODEL_ANALYST}")
    assert span.attributes["gen_ai.usage.input_tokens"] == 12
    assert span.attributes["gen_ai.usage.output_tokens"] == 34
    assert span.attributes["langfuse.observation.input"] == "the prompt"
    assert span.attributes["langfuse.observation.output"] == "the memo"


def test_complete_skips_usage_when_not_int(span_exporter):
    # A bare MagicMock usage (non-int tokens) must NOT set token attributes,
    # must NOT raise, and must NOT emit OTel "invalid attribute" warnings.
    fake_block = MagicMock(type="text", text="ok")
    fake_resp = MagicMock(content=[fake_block])  # .usage is an auto MagicMock
    fake_client = MagicMock()
    fake_client.messages.create.return_value = fake_resp
    with patch.object(llm, "_client", return_value=fake_client):
        out = llm.complete("p", model=llm.MODEL_ANALYST)
    assert out == "ok"
    span = next(s for s in span_exporter.get_finished_spans()
                if s.name == f"chat {llm.MODEL_ANALYST}")
    assert "gen_ai.usage.input_tokens" not in span.attributes
    assert "gen_ai.usage.output_tokens" not in span.attributes
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/bin/python -m pytest tests/test_llm.py::test_complete_records_usage_and_io -v`
Expected: FAIL — `KeyError: 'gen_ai.usage.input_tokens'` (attribute not set yet).

- [ ] **Step 3: Implement guarded usage + I/O capture**

Rewrite `common/llm.py` (add the `_set_usage` helper and the input/output attributes; everything else unchanged):

```python
"""Single Claude entry point. Model ids and request shape live here."""
import functools

import anthropic
from opentelemetry.trace import Span, Status, StatusCode

from common import telemetry

MODEL_ANALYST = "claude-sonnet-4-6"
MODEL_DEBATE = "claude-opus-4-8"


@functools.lru_cache(maxsize=1)
def _client() -> anthropic.Anthropic:
    return anthropic.Anthropic()


def _set_usage(span: Span, resp) -> None:
    """Best-effort: record token usage on the span when present as real ints."""
    usage = getattr(resp, "usage", None)
    if usage is None:
        return
    for field, key in (
        ("input_tokens", "gen_ai.usage.input_tokens"),
        ("output_tokens", "gen_ai.usage.output_tokens"),
    ):
        value = getattr(usage, field, None)
        if isinstance(value, int) and not isinstance(value, bool):
            span.set_attribute(key, value)


def complete(prompt: str, *, model: str, system: str | None = None, max_tokens: int = 16000) -> str:
    kwargs = {"model": model, "max_tokens": max_tokens, "messages": [{"role": "user", "content": prompt}]}
    if system is not None:
        kwargs["system"] = system
    with telemetry.tracer(__name__).start_as_current_span(f"chat {model}") as span:
        span.set_attribute("gen_ai.request.model", model)
        span.set_attribute("langfuse.observation.input", prompt)
        try:
            resp = _client().messages.create(**kwargs)
        except Exception as exc:
            span.record_exception(exc)
            span.set_status(Status(StatusCode.ERROR, str(exc)))
            raise
        text = next((b.text for b in resp.content if b.type == "text"), "")
        span.set_attribute("langfuse.observation.output", text)
        _set_usage(span, resp)
        return text
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `.venv/bin/python -m pytest tests/test_llm.py -v`
Expected: PASS (5 tests; output pristine — no "invalid attribute" warnings).

- [ ] **Step 5: Run the full Python suite**

Run: `.venv/bin/python -m pytest -q`
Expected: `28 passed` (26 + 2 new).

- [ ] **Step 6: Commit**

```bash
git add common/llm.py tests/test_llm.py
git commit -m "feat(telemetry): record token usage and prompt/response on the LLM span"
```

---

### Task 2: Java token + I/O attributes on the LLM span

**Files:**
- Modify: `agents/fundamentals-java/src/main/java/com/tradingfirm/fundamentals/FundamentalsService.java`
- Test: `agents/fundamentals-java/src/test/java/com/tradingfirm/fundamentals/TracingContinuationTest.java`

**Interfaces:**
- Produces: `analyze()` sets `langfuse.observation.input` (the prompt) before the call, and after it `langfuse.observation.output` (the reply) + `gen_ai.usage.input_tokens`/`output_tokens` from `message.usage()`, guarded (a null/odd usage never breaks the call).

- [ ] **Step 1: Write the failing test**

Add this test to `TracingContinuationTest.java` (the file already has `setUp`, `remoteCarrier`, `request`, and the Anthropic mock imports from Scope B; add an import for `com.anthropic.models.messages.Usage` and reuse `getFinishedSpanItems()`):

Add import near the other Anthropic imports:
```java
import com.anthropic.models.messages.Usage;
```

Add the test method:
```java
    @Test
    void llmSpanRecordsUsageAndIo() {
        String[] ids = new String[2];
        Map<String, String> carrier = remoteCarrier(ids);

        Usage usage = mock(Usage.class);
        when(usage.inputTokens()).thenReturn(12L);
        when(usage.outputTokens()).thenReturn(34L);
        Message message = mock(Message.class);
        when(message.content()).thenReturn(List.of());
        when(message.usage()).thenReturn(usage);
        MessageService messages = mock(MessageService.class);
        when(messages.create(any())).thenReturn(message);
        AnthropicClient client = mock(AnthropicClient.class);
        when(client.messages()).thenReturn(messages);

        FundamentalsService service = new FundamentalsService(client, tracer);
        A2AController controller = new A2AController(service, telemetry);
        controller.rpc(request(carrier));

        SpanData llm = exporter.getFinishedSpanItems().stream()
                .filter(s -> s.getName().equals("chat claude-sonnet-4-6"))
                .findFirst().orElseThrow();
        var attrs = llm.getAttributes();
        assertEquals(12L, attrs.get(io.opentelemetry.api.common.AttributeKey.longKey("gen_ai.usage.input_tokens")));
        assertEquals(34L, attrs.get(io.opentelemetry.api.common.AttributeKey.longKey("gen_ai.usage.output_tokens")));
        assertNotNull(attrs.get(io.opentelemetry.api.common.AttributeKey.stringKey("langfuse.observation.input")));
        // content() is empty -> output is "" but the attribute is still set
        assertNotNull(attrs.get(io.opentelemetry.api.common.AttributeKey.stringKey("langfuse.observation.output")));
    }
```

- [ ] **Step 2: Run test to verify it fails**

Run: `mvn -f agents/fundamentals-java/pom.xml -q -Dtest=TracingContinuationTest#llmSpanRecordsUsageAndIo test 2>&1 | tail -20`
Expected: FAIL — the `gen_ai.usage.input_tokens` attribute is null (not set yet).

- [ ] **Step 3: Implement guarded usage + I/O capture**

In `FundamentalsService.java`, set the input attribute before the call and capture output + usage after. Replace the span block in `analyze` (lines ~44-55) with:

```java
        Span span = tracer.spanBuilder("chat " + MODEL).startSpan();
        span.setAttribute("gen_ai.request.model", MODEL);
        span.setAttribute("langfuse.observation.input", prompt);
        try (Scope scope = span.makeCurrent()) {
            Message message = client.messages().create(params);
            String reply = extractText(message);
            span.setAttribute("langfuse.observation.output", reply);
            setUsage(span, message);
            return reply;
        } catch (RuntimeException e) {
            span.recordException(e);
            span.setStatus(StatusCode.ERROR);
            throw e;
        } finally {
            span.end();
        }
```

And add this private helper (below `extractText`):

```java
    /** Best-effort: record token usage on the span when available. */
    private static void setUsage(Span span, Message message) {
        try {
            Usage usage = message.usage();
            span.setAttribute("gen_ai.usage.input_tokens", usage.inputTokens());
            span.setAttribute("gen_ai.usage.output_tokens", usage.outputTokens());
        } catch (RuntimeException e) {
            // best-effort: never let usage capture break the call
        }
    }
```

Add the import at the top:
```java
import com.anthropic.models.messages.Usage;
```

(If the resolved `anthropic-java` exposes usage differently — e.g. `usage.inputTokens()` returns `Optional<Long>` or `Long` — adapt minimally so the two `setAttribute(String, long)` calls receive a `long`; the guard already swallows runtime surprises. Note any adaptation in the report.)

- [ ] **Step 4: Run the test to verify it passes**

Run: `mvn -f agents/fundamentals-java/pom.xml -q -Dtest=TracingContinuationTest test 2>&1 | tail -20`
Expected: all `TracingContinuationTest` cases pass, including the new one. (The Scope B `llmSpanNestsUnderServerSpan` test mocks a `Message` without usage → `message.usage()` is null → `setUsage` catches the NPE and skips — still green.)

- [ ] **Step 5: Run the full Java suite**

Run: `mvn -f agents/fundamentals-java/pom.xml -q test 2>&1 | tail -20`
Expected: all green (was 13, now 14). Report the count.

- [ ] **Step 6: Commit**

```bash
git add agents/fundamentals-java/src/main/java/com/tradingfirm/fundamentals/FundamentalsService.java \
        agents/fundamentals-java/src/test/java/com/tradingfirm/fundamentals/TracingContinuationTest.java
git commit -m "feat(java-tracing): record token usage and prompt/response on the LLM span"
```

---

### Task 3: Java OTLP `Authorization` header (`TracingConfig`)

**Files:**
- Modify: `agents/fundamentals-java/src/main/java/com/tradingfirm/fundamentals/TracingConfig.java`
- Test: `agents/fundamentals-java/src/test/java/com/tradingfirm/fundamentals/TracingConfigTest.java` (create)

**Interfaces:**
- Produces: `static Map<String,String> parseHeaders(String raw)` — parses comma-separated `key=value` pairs (split on the FIRST `=` so base64 `==` padding in values survives; null/blank → empty map). The exporter gets each header via `addHeader` inside the existing endpoint branch.

- [ ] **Step 1: Write the failing test**

Create `agents/fundamentals-java/src/test/java/com/tradingfirm/fundamentals/TracingConfigTest.java`:

```java
package com.tradingfirm.fundamentals;

import org.junit.jupiter.api.Test;

import java.util.Map;

import static org.junit.jupiter.api.Assertions.*;

class TracingConfigTest {

    @Test
    void parsesCommaSeparatedHeadersSplittingOnFirstEquals() {
        // base64 basic-auth values contain '=' padding; must split on the first '=' only.
        Map<String, String> headers =
                TracingConfig.parseHeaders("Authorization=Basic cGs6c2s=,X-Scope=demo");
        assertEquals("Basic cGs6c2s=", headers.get("Authorization"));
        assertEquals("demo", headers.get("X-Scope"));
        assertEquals(2, headers.size());
    }

    @Test
    void blankOrNullYieldsNoHeaders() {
        assertTrue(TracingConfig.parseHeaders(null).isEmpty());
        assertTrue(TracingConfig.parseHeaders("").isEmpty());
        assertTrue(TracingConfig.parseHeaders("   ").isEmpty());
    }
}
```

- [ ] **Step 2: Run test to verify it fails**

Run: `mvn -f agents/fundamentals-java/pom.xml -q -Dtest=TracingConfigTest test 2>&1 | tail -20`
Expected: COMPILE FAILURE — `parseHeaders` does not exist yet.

- [ ] **Step 3: Implement the parser and wire it into the exporter**

In `TracingConfig.java`, add imports:
```java
import java.util.LinkedHashMap;
import java.util.Map;
```

Add the parser method (package-private static, so the test can call it):
```java
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
```

And attach the headers inside the existing endpoint branch — replace the exporter construction:
```java
            String base = endpoint.endsWith("/") ? endpoint.substring(0, endpoint.length() - 1) : endpoint;
            var exporterBuilder = OtlpHttpSpanExporter.builder().setEndpoint(base + "/v1/traces");
            parseHeaders(System.getenv("OTEL_EXPORTER_OTLP_HEADERS")).forEach(exporterBuilder::addHeader);
            OtlpHttpSpanExporter exporter = exporterBuilder.build();
            builder.addSpanProcessor(BatchSpanProcessor.builder(exporter).build());
```

- [ ] **Step 4: Run the test to verify it passes**

Run: `mvn -f agents/fundamentals-java/pom.xml -q -Dtest=TracingConfigTest test 2>&1 | tail -20`
Expected: 2 tests pass.

- [ ] **Step 5: Run the full Java suite**

Run: `mvn -f agents/fundamentals-java/pom.xml -q test 2>&1 | tail -20`
Expected: all green (was 14, now 16 — two new). Report the count.

- [ ] **Step 6: Commit**

```bash
git add agents/fundamentals-java/src/main/java/com/tradingfirm/fundamentals/TracingConfig.java \
        agents/fundamentals-java/src/test/java/com/tradingfirm/fundamentals/TracingConfigTest.java
git commit -m "feat(java-tracing): attach OTLP Authorization header from OTEL_EXPORTER_OTLP_HEADERS"
```

---

### Task 4: Langfuse self-host docker-compose + env template + runbook

**Files:**
- Create: `docker/langfuse/docker-compose.yml` (vendored from upstream)
- Create: `docker/langfuse/.env.langfuse.example`
- Create: `docker/langfuse/README.md` (runbook + live-verification checklist)

**Interfaces:** None (infra/docs). Deliverable: a compose file that `docker compose config` validates, an env template, and a runbook.

- [ ] **Step 1: Vendor the official Langfuse self-host compose**

Obtain Langfuse's official self-host `docker-compose.yml` from the upstream source (`https://github.com/langfuse/langfuse/blob/main/docker-compose.yml`, the file referenced by `https://langfuse.com/self-hosting/docker-compose`) and save it verbatim to `docker/langfuse/docker-compose.yml`. **Pin every image to a specific version tag** (replace any `:latest` with the current pinned tag shown in the upstream file, e.g. `langfuse/langfuse:3`, `clickhouse/clickhouse-server:<tag>`, `postgres:<tag>`, `redis:<tag>`, `minio/minio:<tag>`). Do not hand-edit service definitions beyond pinning tags. If the upstream URL is unreachable, report NEEDS_CONTEXT rather than hand-authoring the stack.

- [ ] **Step 2: Validate compose syntax**

Run: `docker compose -f docker/langfuse/docker-compose.yml config >/dev/null && echo OK`
Expected: `OK` (no parse error). If `docker` is unavailable in this environment, report that and skip to Step 3 (the runbook documents validation).

- [ ] **Step 3: Create the env template**

Create `docker/langfuse/.env.langfuse.example`:

```bash
# Langfuse self-host — copy to .env.langfuse and fill in, or export these before running the agents.
# After `docker compose up`, open http://localhost:3000, create a project, and copy its API keys here.

# The agents export OTLP to Langfuse's trace ingestion endpoint. Our exporters append /v1/traces,
# so point at the base OTEL path (NOT including /v1/traces):
OTEL_EXPORTER_OTLP_ENDPOINT=http://localhost:3000/api/public/otel

# Basic auth = base64("<public_key>:<secret_key>"). Generate with:
#   echo -n 'pk-lf-xxxx:sk-lf-xxxx' | base64
# Then set (note the literal "Authorization=" key; value is "Basic <token>"):
OTEL_EXPORTER_OTLP_HEADERS=Authorization=Basic <base64_public_colon_secret>
```

- [ ] **Step 4: Write the runbook**

Create `docker/langfuse/README.md`:

```markdown
# Langfuse viewer (self-hosted) — Scope C live verification

Renders the cross-language distributed trace (orchestrator → Python agents → Java agent → LLM
generations) with token counts, derived cost, latency, and the prompt/response per generation.
The app runs fully without this; tracing is no-op unless `OTEL_EXPORTER_OTLP_ENDPOINT` is set.

## 1. Start Langfuse

```bash
docker compose -f docker/langfuse/docker-compose.yml up -d
```

Wait until http://localhost:3000 is up (first start pulls images + initializes ClickHouse/Postgres —
can take a few minutes). Create an account (local), create an Organization + Project.

## 2. Get API keys and set the OTLP env

In the project: Settings → API Keys → create. Then:

```bash
cp docker/langfuse/.env.langfuse.example docker/langfuse/.env.langfuse
# edit it: paste the OTEL_EXPORTER_OTLP_HEADERS base64 of "<public>:<secret>"
echo -n 'pk-lf-...:sk-lf-...' | base64   # value after "Basic "
```

## 3. Run the firm with tracing on

```bash
set -a; source .env; source docker/langfuse/.env.langfuse; set +a
./scripts/run_all_java.sh AAPL
```

## 4. Verify in Langfuse

In the Langfuse UI → Tracing → Traces, open the latest trace and confirm:
- **One trace** spans the orchestrator root, the two Python agents, AND the Java Fundamentals agent
  (service `fundamentals-java`), with a server span and a nested `chat …` generation under each agent.
- Each `chat …` generation shows **input/output tokens** and the **prompt/response text**.
- A **cost** is shown per generation. If cost is $0, the model id isn't in Langfuse's price table:
  Settings → Models → add `claude-sonnet-4-6` / `claude-opus-4-8` with input/output prices, then re-run.

## 5. Stop

```bash
docker compose -f docker/langfuse/docker-compose.yml down        # keep data
docker compose -f docker/langfuse/docker-compose.yml down -v     # wipe volumes
```
```

- [ ] **Step 5: Commit**

```bash
git add docker/langfuse/
git commit -m "feat(observability): self-host Langfuse compose, env template, and live-verification runbook"
```

---

### Task 5: Docs + drop the unused `langfuse` dependency

**Files:**
- Modify: `pyproject.toml`
- Modify: `README.md`
- Modify: `docs/superpowers/specs/2026-06-19-trading-agents-a2a-design.md` (§10.2)

**Interfaces:** None.

- [ ] **Step 1: Remove the unused `langfuse` dependency**

First confirm it is unused: `grep -rn "import langfuse\|from langfuse" common/ orchestrator/ agents/ tests/` → expect no matches. Then remove the `langfuse` entry from the dependencies array in `pyproject.toml` (remove only that one line; leave all other dependencies and the `[project.optional-dependencies] dev` list intact).

- [ ] **Step 2: Verify the suite still passes without it**

Run: `.venv/bin/python -m pytest -q`
Expected: `28 passed` (the package is still installed in the venv but nothing imports it; the suite is unaffected). Report the count.

- [ ] **Step 3: Update the README Observability bullet**

In `README.md`, replace the Observability bullet:

Old:
```
- **Observability** — distributed tracing (OpenTelemetry) and LLM observability (Langfuse). The orchestrator and all agents — Python and the Java/Spring agent — share one trace: the orchestrator opens a root span and injects W3C trace context into each A2A call, and every agent server (including the Java agent via the OpenTelemetry Java SDK) extracts it from the message metadata and parents its server and LLM spans into the same trace. A Langfuse viewer with token/cost lands in a later milestone.
```

New:
```
- **Observability** — distributed tracing (OpenTelemetry) into a self-hosted **Langfuse**. The orchestrator and all agents — Python and the Java/Spring agent — share one trace: the orchestrator opens a root span and injects W3C trace context into each A2A call, and every agent server extracts it and parents its server and LLM spans into the same trace. The LLM spans carry token usage and the prompt/response, and Langfuse (OTLP-native; no SDK) renders the cross-language tree with derived cost. Run it locally via `docker/langfuse/` (see its README); fully no-op when `OTEL_EXPORTER_OTLP_ENDPOINT` is unset.
```

- [ ] **Step 4: Update the design spec §10.2**

In `docs/superpowers/specs/2026-06-19-trading-agents-a2a-design.md`, replace the §10.2 bullets:

Old:
```
### 10.2 LLM / agent observability — Langfuse
- Captures per-LLM-call **token usage, cost, latency, and prompt/response**, plus the bull-vs-bear **debate turns** as nested observations.
- Langfuse is OTel-native, so it receives the same trace tree; the orchestrator's LangGraph run and each agent's LLM calls appear under one trace.
- Open-source and self-hostable via Docker (no SaaS lock-in); the Java agent uses the Langfuse Java SDK so it is covered too.
- Run locally via a `docker-compose` for Langfuse (added under `scripts/`); falls back to no-op exporters when Langfuse env vars are absent, so the app runs without it.
```

New:
```
### 10.2 LLM / agent observability — Langfuse
- Each LLM span carries **token usage** (`gen_ai.usage.input_tokens`/`output_tokens`) and the **prompt/response** (`langfuse.observation.input`/`output`); Langfuse derives **cost** from the model id + token counts.
- Langfuse is **OTel-native**: it ingests the same OTLP export both agents already emit, so the orchestrator's LangGraph run and every agent's LLM call (Python and Java) appear under one trace — no Langfuse SDK in either language.
- Open-source and self-hosted via Docker (no SaaS lock-in). Authentication is a `Basic` `Authorization` header on the OTLP export (`OTEL_EXPORTER_OTLP_HEADERS`).
- Run locally via the compose + runbook under `docker/langfuse/`; falls back to no-op exporters when `OTEL_EXPORTER_OTLP_ENDPOINT` is unset, so the app runs without it.
```

- [ ] **Step 5: Verify both suites are green**

Run: `.venv/bin/python -m pytest -q 2>&1 | tail -1 && mvn -f agents/fundamentals-java/pom.xml -q test 2>&1 | grep -iE "Tests run: [0-9]+, Fail|BUILD" | tail -2`
Expected: Python `28 passed`; Java all green (16).

- [ ] **Step 6: Commit**

```bash
git add pyproject.toml README.md docs/superpowers/specs/2026-06-19-trading-agents-a2a-design.md
git commit -m "docs: Langfuse is OTLP-native with token/cost + prompt/response; drop unused dep"
```

---

## Final verification (after all tasks)

- [ ] `.venv/bin/python -m pytest -q` → `28 passed`, no `ANTHROPIC_API_KEY`.
- [ ] `mvn -f agents/fundamentals-java/pom.xml test` → all green (16), no key.
- [ ] `git log --oneline` shows no `Co-Authored-By` / AI-attribution trailers.
- [ ] `grep -rn "import a2a\|from a2a" common/ orchestrator/` → only `common/a2a_server.py` and `orchestrator/a2a_client.py`. `grep -rn "langfuse" common/ orchestrator/ agents/ tests/` → no imports (docs/compose references only).
- [ ] (Manual, needs Docker + key) Live verification per `docker/langfuse/README.md`: one trace tree across orchestrator + Python + Java agents with token counts, cost, and prompt/response.

## Self-Review (completed by plan author)

**Spec coverage:** §3 attribute table → Tasks 1 (Python) + 2 (Java). §4 components: `llm.py` → Task 1; `FundamentalsService` → Task 2; `TracingConfig` header parsing → Task 3; `docker/langfuse/` → Task 4; drop `langfuse` dep → Task 5. §6 best-effort/no-op → guards in Tasks 1-2, endpoint-branch in Task 3. §7 testing → token/IO tests (1,2), header parser (3), `docker compose config` (4), live runbook (4); §1 success criterion part 1 (automated attrs + parser) → Tasks 1-3, part 2 (live) → Task 4 runbook. §8 files → all mapped. §9 out-of-scope (metrics/structlog) → not present.

**Placeholder scan:** No TBD/TODO/"handle edge cases". Every code step shows full code; every run step has an exact command + expected output. The one vendored artifact (upstream Langfuse compose, Task 4) is a fetch-and-pin instruction with a NEEDS_CONTEXT fallback, not hand-authored — appropriate for third-party infra.

**Type consistency:** attribute keys `gen_ai.usage.input_tokens`/`output_tokens`, `langfuse.observation.input`/`output` identical across Python and Java tasks and their tests; Python `_set_usage(span, resp)`; Java `setUsage(Span, Message)` + `parseHeaders(String) -> Map<String,String>`; OTLP env `OTEL_EXPORTER_OTLP_ENDPOINT` (base, exporters append `/v1/traces`) and `OTEL_EXPORTER_OTLP_HEADERS` (`k=v` comma list) consistent across Task 3, Task 4 env template, and the runbook.
