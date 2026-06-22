# Tracing Scope A — Python End-to-End Trace Continuation Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make distributed tracing real across the Python processes so the orchestrator root span, each A2A client span, each agent server span, and each LLM span share one `trace_id` with correct parent/child links.

**Architecture:** Add one `server_span(name, carrier)` helper to `common/telemetry.py` that extracts the remote W3C context and opens a child span. Wire four instrumentation points — root span (orchestrator), client span (A2A client, where `inject()` already runs), server span (A2A server, child of `extract(context.metadata)`), and LLM span (`llm.complete`) — so the whole tree is continuous. All tracing is best-effort and no-op when `OTEL_EXPORTER_OTLP_ENDPOINT` is unset.

**Tech Stack:** Python 3.13, OpenTelemetry SDK (already a dependency), a2a-sdk 1.1.0, LangGraph, pytest + pytest-asyncio (`asyncio_mode = "auto"`), `InMemorySpanExporter` for span assertions.

## Global Constraints

- **SDK isolation:** No new `a2a-sdk` imports anywhere. `a2a-sdk` stays confined to `common/a2a_server.py` and `orchestrator/a2a_client.py`. Reading `context.metadata` inside `a2a_server.py` is allowed (it is the SDK wrapper).
- **Opt-in / no-op telemetry:** Behavior must not change when `OTEL_EXPORTER_OTLP_ENDPOINT` is unset. Spans are created but not exported; quick local runs and key-free tests are unaffected.
- **Best-effort tracing:** Tracing must never break request handling. Context extraction is wrapped in `try/except`; spans `record_exception` + set `ERROR` status when the wrapped operation raises, then re-raise.
- **Models (exact strings, no date suffixes, no `temperature`/`budget_tokens`/prefills):** `claude-sonnet-4-6` (analysts), `claude-opus-4-8` (debate).
- **Key-free test suite:** `.venv/bin/python -m pytest -q` must stay green (currently **20 passed**) with no `ANTHROPIC_API_KEY`. LLM calls are mocked.
- **Public-repo rule:** Keep "Claude"/AI attribution out of commit messages and tracked docs. Strip any `Co-Authored-By` trailer before committing. Naming `claude-sonnet-4-6` / `claude-opus-4-8` / "Anthropic SDK" as the stack is fine.
- **Commands:** `python` is NOT on PATH — use `.venv/bin/python`. Run tests with `.venv/bin/python -m pytest -q`.
- **a2a-sdk truth source:** The `# VERIFIED API:` block at the top of `scripts/spike_helloworld.py`, not online docs.

## Design note — root span location (deviation from spec §8)

The spec §3/§8 names `orchestrator/main.py` for the root span. This plan places it in `orchestrator/graph.run()` instead, wrapping `graph.ainvoke` directly. Rationale: `run()` is the actual async invocation site, so (a) the root span is current in the same async context that LangGraph copies into its parallel node tasks — no reliance on context propagation across the `asyncio.run` boundary — and (b) it is directly testable in-loop (Task 5's propagation test calls `await run(...)`), which is what proves spec §10's contextvars-across-async-tasks concern. `main.py` is unchanged: it still calls `setup("orchestrator")` then `asyncio.run(run(ticker))`, so the live path gets the root span for free. This is functionally "root span around `graph.ainvoke`, made current" as the spec requires.

## File Structure

- `common/telemetry.py` (modify) — add `server_span(name, carrier)` contextmanager. Keep `setup`/`tracer`/`inject`/`extract` unchanged.
- `common/a2a_server.py` (modify) — thread `name` into `_FunctionExecutor`; in `execute`, read `context.metadata` (guarded) and run the handler inside `telemetry.server_span(name, carrier)`.
- `common/llm.py` (modify) — wrap the Anthropic call in `complete()` in an LLM span.
- `orchestrator/a2a_client.py` (modify) — wrap the send in `call_agent` in a client span; add keyword-only `agent_name` param.
- `orchestrator/graph.py` (modify) — open the root span in `run()`; pass `agent_name=` on each `call_agent`.
- `tests/conftest.py` (create) — `span_exporter` fixture that attaches an `InMemorySpanExporter` to the global TracerProvider (works around OTel's set-once provider).
- `tests/test_telemetry.py` (modify) — add `server_span` continuation unit test.
- `tests/test_llm.py` (modify) — add LLM-span test.
- `tests/test_a2a_client.py` (modify) — add client-span test.
- `tests/test_trace_continuation.py` (create) — single-agent server-side continuation test + full-graph one-trace propagation test.

---

### Task 1: `server_span` helper + test-infra fixture

**Files:**
- Modify: `common/telemetry.py`
- Create: `tests/conftest.py`
- Test: `tests/test_telemetry.py`

**Interfaces:**
- Consumes: existing `common.telemetry` (`_otel_extract`, `trace`).
- Produces:
  - `telemetry.server_span(name: str, carrier: dict) -> ContextManager[Span]` — extracts remote context from `carrier`, opens a child span made current, yields it; records + ERROR-statuses any exception raised inside and re-raises; best-effort on extraction failure.
  - pytest fixture `span_exporter` (function-scoped) yielding an `InMemorySpanExporter` wired to the global TracerProvider, cleared before each use.

**Why the fixture:** OTel's `trace.set_tracer_provider` is set-once per process. Code under test calls `trace.get_tracer(...)` (the global provider), so tests must read spans from an exporter attached to that global provider — not a freshly-replaced one (which OTel would silently ignore). The fixture attaches one `InMemorySpanExporter` to whatever global provider exists and `clear()`s it per test.

- [ ] **Step 1: Create the test fixture**

Create `tests/conftest.py`:

```python
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
```

- [ ] **Step 2: Write the failing test**

Add to `tests/test_telemetry.py`:

```python
def test_server_span_continues_remote_trace(span_exporter):
    from common import telemetry

    tr = telemetry.tracer("remote")
    with tr.start_as_current_span("remote-root") as root:
        carrier = telemetry.inject({})
        root_ctx = root.get_span_context()

    # Server side: continue the trace from the carrier alone.
    with telemetry.server_span("agent-server", carrier) as span:
        assert span.get_span_context().trace_id == root_ctx.trace_id

    finished = {s.name: s for s in span_exporter.get_finished_spans()}
    server = finished["agent-server"]
    assert server.context.trace_id == root_ctx.trace_id
    assert server.parent is not None
    assert server.parent.span_id == root_ctx.span_id
```

- [ ] **Step 3: Run test to verify it fails**

Run: `.venv/bin/python -m pytest tests/test_telemetry.py::test_server_span_continues_remote_trace -v`
Expected: FAIL with `AttributeError: module 'common.telemetry' has no attribute 'server_span'`.

- [ ] **Step 4: Implement `server_span`**

In `common/telemetry.py`, add `from contextlib import contextmanager` to the imports, then append:

```python
@contextmanager
def server_span(name: str, carrier: dict):
    """Continue a remote trace: extract context from *carrier* and run the
    enclosed block inside a child span made current.

    Best-effort: if extraction fails the block still runs (under a new span).
    Exceptions raised inside the block are recorded on the span and re-raised.
    """
    try:
        ctx = _otel_extract(carrier or {})
    except Exception:
        ctx = None
    with trace.get_tracer(__name__).start_as_current_span(name, context=ctx) as span:
        try:
            yield span
        except Exception as exc:
            span.record_exception(exc)
            span.set_status(trace.Status(trace.StatusCode.ERROR, str(exc)))
            raise
```

- [ ] **Step 5: Run test to verify it passes**

Run: `.venv/bin/python -m pytest tests/test_telemetry.py -v`
Expected: PASS (3 tests in the file).

- [ ] **Step 6: Run the full suite (no regression)**

Run: `.venv/bin/python -m pytest -q`
Expected: `21 passed` (20 prior + 1 new).

- [ ] **Step 7: Commit**

```bash
git add common/telemetry.py tests/conftest.py tests/test_telemetry.py
git commit -m "feat(telemetry): add server_span helper to continue remote traces"
```

---

### Task 2: LLM span in `common/llm.py`

**Files:**
- Modify: `common/llm.py`
- Test: `tests/test_llm.py`

**Interfaces:**
- Consumes: `telemetry.tracer` (Task 1's module, unchanged signature).
- Produces: every `complete(prompt, *, model, ...)` call emits a span named `f"chat {model}"` with attribute `gen_ai.request.model = model`; return value unchanged (first text block or `""`).

- [ ] **Step 1: Write the failing test**

Add to `tests/test_llm.py`:

```python
def test_complete_emits_llm_span(span_exporter):
    fake_block = MagicMock(type="text", text="hi there")
    fake_resp = MagicMock(content=[fake_block])
    fake_client = MagicMock()
    fake_client.messages.create.return_value = fake_resp

    with patch.object(llm, "_client", return_value=fake_client):
        out = llm.complete("q", model=llm.MODEL_ANALYST)

    assert out == "hi there"
    spans = [s for s in span_exporter.get_finished_spans()
             if s.name == f"chat {llm.MODEL_ANALYST}"]
    assert len(spans) == 1
    assert spans[0].attributes["gen_ai.request.model"] == llm.MODEL_ANALYST
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/bin/python -m pytest tests/test_llm.py::test_complete_emits_llm_span -v`
Expected: FAIL — no span named `chat claude-sonnet-4-6` is captured (list is empty).

- [ ] **Step 3: Implement the LLM span**

Rewrite `common/llm.py` body. Add imports and wrap the call:

```python
"""Single Claude entry point. Model ids and request shape live here."""
import functools

import anthropic
from opentelemetry.trace import Status, StatusCode

from common import telemetry

MODEL_ANALYST = "claude-sonnet-4-6"
MODEL_DEBATE = "claude-opus-4-8"


@functools.lru_cache(maxsize=1)
def _client() -> anthropic.Anthropic:
    return anthropic.Anthropic()


def complete(prompt: str, *, model: str, system: str | None = None, max_tokens: int = 16000) -> str:
    kwargs = {"model": model, "max_tokens": max_tokens, "messages": [{"role": "user", "content": prompt}]}
    if system is not None:
        kwargs["system"] = system
    with telemetry.tracer(__name__).start_as_current_span(f"chat {model}") as span:
        span.set_attribute("gen_ai.request.model", model)
        try:
            resp = _client().messages.create(**kwargs)
        except Exception as exc:
            span.record_exception(exc)
            span.set_status(Status(StatusCode.ERROR, str(exc)))
            raise
        return next((b.text for b in resp.content if b.type == "text"), "")
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `.venv/bin/python -m pytest tests/test_llm.py -v`
Expected: PASS (3 tests: the 2 existing + the new span test).

- [ ] **Step 5: Run the full suite**

Run: `.venv/bin/python -m pytest -q`
Expected: `22 passed`.

- [ ] **Step 6: Commit**

```bash
git add common/llm.py tests/test_llm.py
git commit -m "feat(llm): emit a span per Claude completion"
```

---

### Task 3: Client span in `orchestrator/a2a_client.py` + thread agent names

**Files:**
- Modify: `orchestrator/a2a_client.py`
- Modify: `orchestrator/graph.py`
- Test: `tests/test_a2a_client.py`

**Interfaces:**
- Consumes: `telemetry.inject`, `telemetry.tracer`.
- Produces: `call_agent(base_url: str, text: str, *, agent_name: str | None = None) -> str`. Each call emits a span named `"a2a SendMessage"` with attributes `server.url` (= `base_url`), `a2a.method = "SendMessage"`, and `agent.name` (only when `agent_name` is given). `inject({})` runs inside this span, so the outgoing `traceparent` encodes the client span. Return value unchanged.

- [ ] **Step 1: Write the failing test**

Add to `tests/test_a2a_client.py`:

```python
async def test_call_agent_emits_client_span(span_exporter):
    app = build_agent_app(
        name="P", description="d", skill_id="p", skill_name="p",
        url="http://127.0.0.1:9321/", handler=lambda t: "ok",
    )
    server = _serve(app, 9321)
    try:
        out = await call_agent("http://127.0.0.1:9321", "ping", agent_name="probe")
    finally:
        server.should_exit = True

    assert out == "ok"
    spans = [s for s in span_exporter.get_finished_spans() if s.name == "a2a SendMessage"]
    assert len(spans) == 1
    attrs = spans[0].attributes
    assert attrs["server.url"] == "http://127.0.0.1:9321"
    assert attrs["a2a.method"] == "SendMessage"
    assert attrs["agent.name"] == "probe"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/bin/python -m pytest tests/test_a2a_client.py::test_call_agent_emits_client_span -v`
Expected: FAIL — `TypeError: call_agent() got an unexpected keyword argument 'agent_name'`.

- [ ] **Step 3: Implement the client span**

In `orchestrator/a2a_client.py`, change the telemetry import and wrap the send. Replace:

```python
from common.telemetry import inject
```

with:

```python
from opentelemetry.trace import Status, StatusCode

from common.telemetry import inject, tracer
```

Then replace the `call_agent` definition (keep `_text_of` as-is) with:

```python
async def call_agent(base_url: str, text: str, *, agent_name: str | None = None) -> str:
    """Resolve the agent card at *base_url*, send *text*, and return the reply.

    Wrapped in an "a2a SendMessage" client span; W3C trace context is injected
    into the outgoing message metadata (best-effort) inside that span, so the
    agent-side spans join the orchestrator's trace.

    Args:
        base_url: Root URL of the remote A2A agent (e.g. ``"http://host:9111"``).
        text: User message text to send.
        agent_name: Optional logical agent name, recorded as the ``agent.name``
            span attribute.

    Returns:
        Concatenated text of all reply parts received from the agent.
    """
    with tracer(__name__).start_as_current_span("a2a SendMessage") as span:
        span.set_attribute("server.url", base_url)
        span.set_attribute("a2a.method", "SendMessage")
        if agent_name:
            span.set_attribute("agent.name", agent_name)
        try:
            async with httpx.AsyncClient(timeout=60) as http:
                # Resolve the agent card from the well-known endpoint
                card = await A2ACardResolver(http, base_url=base_url).get_agent_card()

                # ClientConfig(streaming=False, httpx_client=http) passes our 60s-timeout client
                client = ClientFactory(ClientConfig(streaming=False, httpx_client=http)).create(card)

                # Build the outgoing message
                msg = new_text_message(text, role=Role.ROLE_USER)
                request = SendMessageRequest(message=msg)

                # Inject W3C trace context into SendMessageRequest metadata (best-effort).
                # inject runs inside the client span, so traceparent encodes this span.
                try:
                    carrier: dict[str, str] = inject({})
                    if carrier:
                        request.metadata.update(carrier)
                except Exception:
                    pass

                chunks: list[str] = []
                async for stream_response in client.send_message(request):
                    chunks.append(_text_of(stream_response))

                return "".join(c for c in chunks if c)
        except Exception as exc:
            span.record_exception(exc)
            span.set_status(Status(StatusCode.ERROR, str(exc)))
            raise
```

- [ ] **Step 4: Pass agent names from the graph**

In `orchestrator/graph.py`, update the three `call_agent` calls inside `build_graph` to pass `agent_name`:

```python
    async def gather_fundamentals(state: State) -> dict:
        return {"fundamentals": await call_agent(urls["fundamentals"], state["ticker"], agent_name="fundamentals")}

    async def gather_sentiment(state: State) -> dict:
        return {"sentiment": await call_agent(urls["sentiment"], state["ticker"], agent_name="sentiment")}

    async def debate(state: State) -> dict:
        joined = f"FUNDAMENTALS:\n{state['fundamentals']}{SEP}{state['sentiment']}"
        memo = await call_agent(urls["debate"], joined, agent_name="debate")
        return {"memo": memo, "recommendation": parse_recommendation(memo)}
```

- [ ] **Step 5: Run tests to verify they pass**

Run: `.venv/bin/python -m pytest tests/test_a2a_client.py -v`
Expected: PASS (2 tests: round-trip + new client-span test).

- [ ] **Step 6: Run the full suite**

Run: `.venv/bin/python -m pytest -q`
Expected: `23 passed`.

- [ ] **Step 7: Commit**

```bash
git add orchestrator/a2a_client.py orchestrator/graph.py tests/test_a2a_client.py
git commit -m "feat(a2a): wrap each A2A send in a client span with agent attributes"
```

---

### Task 4: Server span in `common/a2a_server.py` (server-side continuation)

**Files:**
- Modify: `common/a2a_server.py`
- Create: `tests/test_trace_continuation.py`

**Interfaces:**
- Consumes: `telemetry.server_span` (Task 1), `call_agent` with `agent_name` (Task 3).
- Produces: every served request opens a server span named after the agent card's `name`, parented to the trace context extracted from `context.metadata`; the handler (and any LLM span it creates) runs inside that span. `_FunctionExecutor.__init__` now takes `(handler, name)`.

- [ ] **Step 1: Write the failing test**

Create `tests/test_trace_continuation.py`:

```python
import threading
import time

import pytest
import uvicorn

from common import telemetry
from common.a2a_server import build_agent_app
from orchestrator.a2a_client import call_agent
from orchestrator.graph import run


def _serve(app, port):
    server = uvicorn.Server(uvicorn.Config(app, host="127.0.0.1", port=port, log_level="warning"))
    threading.Thread(target=server.run, daemon=True).start()
    while not server.started:
        time.sleep(0.05)
    return server


@pytest.mark.asyncio
async def test_server_span_parents_into_orchestrator_trace(span_exporter):
    app = build_agent_app(
        name="contagent", description="d", skill_id="c", skill_name="c",
        url="http://127.0.0.1:9331/", handler=lambda t: "ok",
    )
    server = _serve(app, 9331)
    tr = telemetry.tracer("test")
    try:
        with tr.start_as_current_span("analyze-root") as root:
            root_tid = root.get_span_context().trace_id
            await call_agent("http://127.0.0.1:9331", "ping", agent_name="contagent")
    finally:
        server.should_exit = True

    spans = {s.name: s for s in span_exporter.get_finished_spans()}
    client = spans["a2a SendMessage"]
    server_span = spans["contagent"]
    assert client.context.trace_id == root_tid
    assert server_span.context.trace_id == root_tid
    assert server_span.parent is not None
    assert server_span.parent.span_id == client.context.span_id
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/bin/python -m pytest tests/test_trace_continuation.py::test_server_span_parents_into_orchestrator_trace -v`
Expected: FAIL — `KeyError: 'contagent'` (no server span is created yet).

- [ ] **Step 3: Implement the server span**

In `common/a2a_server.py`, add `from common import telemetry` to the imports. Replace the `_FunctionExecutor` class with:

```python
class _FunctionExecutor(AgentExecutor):
    """Wraps a plain ``handler(text: str) -> str`` callable as an A2A executor."""

    def __init__(self, handler: Callable[[str], str], name: str) -> None:
        self._handler = handler
        self._name = name

    async def execute(self, context: RequestContext, event_queue: EventQueue) -> None:
        text = context.get_user_input()
        # Read the incoming W3C carrier (verified to live on context.metadata).
        try:
            carrier = dict(context.metadata or {})
        except Exception:
            carrier = {}
        # Run the handler inside a server span that continues the remote trace,
        # so any LLM span created inside the handler parents into this span.
        with telemetry.server_span(self._name, carrier):
            result = self._handler(text)
        await event_queue.enqueue_event(new_text_message(result, role=Role.ROLE_AGENT))

    async def cancel(self, context: RequestContext, event_queue: EventQueue) -> None:
        raise NotImplementedError
```

Then in `build_agent_app`, pass `name` into the executor. Change:

```python
    request_handler = DefaultRequestHandler(
        agent_executor=_FunctionExecutor(handler),
        task_store=InMemoryTaskStore(),
        agent_card=card,
    )
```

to:

```python
    request_handler = DefaultRequestHandler(
        agent_executor=_FunctionExecutor(handler, name),
        task_store=InMemoryTaskStore(),
        agent_card=card,
    )
```

- [ ] **Step 4: Run the test to verify it passes**

Run: `.venv/bin/python -m pytest tests/test_trace_continuation.py -v`
Expected: PASS (1 test so far).

- [ ] **Step 5: Run the full suite**

Run: `.venv/bin/python -m pytest -q`
Expected: `24 passed`.

- [ ] **Step 6: Commit**

```bash
git add common/a2a_server.py tests/test_trace_continuation.py
git commit -m "feat(a2a): extract trace context server-side and open a server span per request"
```

---

### Task 5: Root span in `orchestrator/graph.run()` + full-graph propagation test

**Files:**
- Modify: `orchestrator/graph.py`
- Test: `tests/test_trace_continuation.py` (add the propagation test)

**Interfaces:**
- Consumes: `telemetry.tracer`; the client span (Task 3) and server span (Task 4).
- Produces: `run(ticker, urls=None)` opens a root span named `f"analyze {ticker}"` with attribute `ticker`, wrapping `graph.ainvoke`. All client and server spans produced during the run parent into this root span's trace.

- [ ] **Step 1: Write the failing test**

Add to `tests/test_trace_continuation.py`:

```python
@pytest.mark.asyncio
async def test_graph_runs_in_one_trace(span_exporter):
    servers = [
        _serve(build_agent_app(
            name="fundamentals", description="d", skill_id="f", skill_name="f",
            url="http://127.0.0.1:9341/", handler=lambda t: "fundamentals strong",
        ), 9341),
        _serve(build_agent_app(
            name="sentiment", description="d", skill_id="s", skill_name="s",
            url="http://127.0.0.1:9342/", handler=lambda t: "sentiment positive",
        ), 9342),
        _serve(build_agent_app(
            name="debate", description="d", skill_id="db", skill_name="db",
            url="http://127.0.0.1:9343/", handler=lambda t: "RECOMMENDATION: HOLD",
        ), 9343),
    ]
    urls = {
        "fundamentals": "http://127.0.0.1:9341",
        "sentiment": "http://127.0.0.1:9342",
        "debate": "http://127.0.0.1:9343",
    }
    try:
        await run("AAPL", urls)
    finally:
        for s in servers:
            s.should_exit = True

    spans = span_exporter.get_finished_spans()
    root = next(s for s in spans if s.name == "analyze AAPL")
    tid = root.context.trace_id
    assert root.attributes["ticker"] == "AAPL"

    client_spans = [s for s in spans if s.name == "a2a SendMessage"]
    server_spans = [s for s in spans if s.name in {"fundamentals", "sentiment", "debate"}]
    assert len(client_spans) == 3
    assert len(server_spans) == 3
    assert all(s.context.trace_id == tid for s in client_spans + server_spans)

    client_ids = {s.context.span_id for s in client_spans}
    assert all(s.parent is not None and s.parent.span_id in client_ids for s in server_spans)
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/bin/python -m pytest tests/test_trace_continuation.py::test_graph_runs_in_one_trace -v`
Expected: FAIL — `StopIteration`/`next(...)` finds no span named `analyze AAPL` (no root span yet).

- [ ] **Step 3: Implement the root span**

In `orchestrator/graph.py`, add `from common import telemetry` to the imports, then replace `run`:

```python
async def run(ticker: str, urls: dict[str, str] | None = None) -> State:
    graph = build_graph(urls or DEFAULT_URLS)
    with telemetry.tracer(__name__).start_as_current_span(f"analyze {ticker}") as span:
        span.set_attribute("ticker", ticker)
        return await graph.ainvoke({"ticker": ticker})
```

- [ ] **Step 4: Run the test to verify it passes**

Run: `.venv/bin/python -m pytest tests/test_trace_continuation.py -v`
Expected: PASS (2 tests).

- [ ] **Step 5: Run the full suite**

Run: `.venv/bin/python -m pytest -q`
Expected: `25 passed`.

- [ ] **Step 6: Commit**

```bash
git add orchestrator/graph.py tests/test_trace_continuation.py
git commit -m "feat(orchestrator): open a root span around the graph run"
```

---

### Task 6: Update docs (README + design spec §10)

**Files:**
- Modify: `README.md:15`
- Modify: `docs/superpowers/specs/2026-06-19-trading-agents-a2a-design.md` (§10.1, second bullet)

**Interfaces:** None (documentation only).

- [ ] **Step 1: Update README**

In `README.md`, replace the Observability bullet (line 15):

Old:
```
- **Observability** — distributed tracing (OpenTelemetry) and LLM observability (Langfuse). Phase 1 propagates W3C trace context across A2A calls (client-side injection into message metadata). Full cross-process span continuation — agent servers extracting and parenting spans into the same trace — lands with the Java agent in a later phase.
```

New:
```
- **Observability** — distributed tracing (OpenTelemetry) and LLM observability (Langfuse). The Python orchestrator and both Python agents share one trace: the orchestrator opens a root span, injects W3C trace context into each A2A call, and the agent servers extract it and parent their server and LLM spans into the same trace. The Java/Spring agent joining the trace, plus a Langfuse viewer with token/cost, land in later milestones.
```

- [ ] **Step 2: Update the design spec §10.1**

In `docs/superpowers/specs/2026-06-19-trading-agents-a2a-design.md`, replace the second bullet of §10.1:

Old:
```
- **W3C `traceparent` context is propagated across A2A boundaries (Phase 1: client-side injection only)** — the orchestrator injects trace context into outgoing A2A message metadata (best-effort). Phase 1 does *not* yet implement server-side extraction: agent servers do not extract and continue the trace, so spans from agent processes do not yet attach to the orchestrator's trace tree. Full cross-process span parenting — including the Java agent (Phase 2) appearing in the same trace — is a follow-up goal for a later phase.
```

New:
```
- **W3C `traceparent` context is propagated across A2A boundaries and continued server-side (Python agents).** The orchestrator opens a root span and injects trace context into outgoing A2A message metadata (best-effort); each Python agent server extracts it from the request metadata and starts its server span (and the nested LLM span) as children, so the orchestrator → Python-agent → LLM spans form one trace tree. The Java/Spring agent extracting the `traceparent` and emitting spans into the same trace is a follow-up milestone (Scope B).
```

- [ ] **Step 3: Verify the full suite is still green**

Run: `.venv/bin/python -m pytest -q`
Expected: `25 passed`.

- [ ] **Step 4: Commit**

```bash
git add README.md docs/superpowers/specs/2026-06-19-trading-agents-a2a-design.md
git commit -m "docs: Python agents now continue the orchestrator trace server-side"
```

---

## Final verification (after all tasks)

- [ ] `.venv/bin/python -m pytest -q` → `25 passed`, no `ANTHROPIC_API_KEY` set.
- [ ] `git log --oneline` shows no `Co-Authored-By` / AI-attribution trailers.
- [ ] `grep -rn "import a2a\|from a2a" common/ orchestrator/` shows a2a-sdk imports only in `common/a2a_server.py` and `orchestrator/a2a_client.py`.
- [ ] (Optional, needs key) Live run still works: `set -a; source .env; set +a; ./scripts/run_all.sh AAPL` → prints memo + recommendation.

## Self-Review (completed by plan author)

**Spec coverage:** §3 instrumentation points → Tasks 1–5 (root=Task 5, client=Task 3, server=Task 4, LLM=Task 2, helper=Task 1). §4 `server_span` helper → Task 1. §6 error handling (best-effort, record_exception+ERROR, re-raise) → built into `server_span`, LLM span, client span. §7 testing (continuation test, LLM-span test, no regression) → Tasks 1/2/4/5 tests. §8 files touched → all mapped. §1 success criterion (one trace_id across root/client/server/LLM with parent links) → Task 5 propagation test + Task 4 continuation test. §10 contextvars-across-async-tasks risk → Task 5 propagation test runs the real graph in-loop.

**Placeholder scan:** No TBD/TODO/"handle edge cases"; every code step shows full code; every run step shows exact command + expected output.

**Type consistency:** `server_span(name, carrier)`, `call_agent(base_url, text, *, agent_name=None)`, `_FunctionExecutor(handler, name)`, root span name `f"analyze {ticker}"`, client span `"a2a SendMessage"`, server span = card `name`, LLM span `f"chat {model}"` — used identically across tasks and tests.

**Known deviation from spec §8:** root span lives in `orchestrator/graph.run()`, not `main.py` (rationale documented above); functionally equivalent and more testable.
