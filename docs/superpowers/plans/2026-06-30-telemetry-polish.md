# Telemetry Polish Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Drop the a2a-sdk's self-instrumentation spans before they reach the backend, only when telemetry is configured.

> **Update (2026-06-30): feature (a) "flush on exit" was DROPPED during implementation** —
> OTel's `TracerProvider` already registers an atexit flush by default (`shutdown_on_exit=True`),
> so an explicit `atexit.register` is redundant, and it does not fix the real Scope C loss (a
> SIGTERM kill, where atexit never runs). Task 2 below shipped only the exporter-wrapping half;
> the `atexit.register`/`shutdown_on_exit` lines and the two atexit wiring assertions were
> removed. See the spec's Decision note.

**Architecture:** A change confined to `common/telemetry.py`, inside the existing `if endpoint:` branch of `setup()`: a standalone `_FilteringSpanExporter` wraps the OTLP exporter and drops spans by instrumentation-scope name. No-op path unchanged. (The original design also added an `atexit.register(provider.shutdown)` flush — **superseded, see the Update note above**: OTel already registers that atexit by default, so it was dropped.)

**Tech Stack:** Python 3.13, OpenTelemetry SDK (`opentelemetry-sdk`, already a dep), `pytest` (dev). No new dependencies.

## Global Constraints

- **No new dependencies.** Use only `atexit` (stdlib) and the already-imported `opentelemetry.sdk.trace.export` symbols.
- **No-op invariant:** both behaviors live inside the existing `if endpoint:` branch and only activate when `OTEL_EXPORTER_OTLP_ENDPOINT` is set. When unset, `setup()` must register no atexit handler and wrap nothing.
- **Exact scope match:** suppress only the instrumentation scope name `"a2a-python-sdk"` (the a2a-sdk's `INSTRUMENTING_MODULE_NAME`). Our spans use module-name scopes (`common.llm`, `orchestrator.graph`, etc.) and must never be dropped.
- **No change to the public API** (`setup`/`tracer`/`inject`/`extract`/`server_span` keep their signatures) and no change to span creation, the agents, the orchestrator, or any Java file.
- **Key-free, network-free tests.** Patch the OTLP exporter; never touch the network. Test output must be pristine (no OTel "Overriding tracer provider" warnings) — wiring tests patch `trace.set_tracer_provider` to a no-op.
- **No AI/Claude attribution** in commit messages (public repo).
- Run from repo root with the venv active (`. .venv/bin/activate`); full suite is **46 passing** at the start and must stay green.

## File Structure

| File | Responsibility |
| --- | --- |
| `common/telemetry.py` | MODIFY. Add `import atexit`; extend the `opentelemetry.sdk.trace.export` import; add `SUPPRESSED_SCOPES`, `_scope_name`, and `_FilteringSpanExporter`; wrap the exporter and register the atexit flush inside the existing `if endpoint:` branch of `setup()`. |
| `tests/test_telemetry.py` | MODIFY. Add 3 isolation tests for `_FilteringSpanExporter` (Task 1) and 2 wiring tests for `setup()` (Task 2). |

Current `setup()` (for reference — Task 2 edits exactly this):

```python
def setup(service_name: str) -> None:
    global _CONFIGURED
    if _CONFIGURED:
        return
    provider = TracerProvider(resource=Resource.create({"service.name": service_name}))
    endpoint = os.getenv("OTEL_EXPORTER_OTLP_ENDPOINT")
    if endpoint:
        from opentelemetry.exporter.otlp.proto.http.trace_exporter import OTLPSpanExporter
        provider.add_span_processor(BatchSpanProcessor(OTLPSpanExporter()))
    trace.set_tracer_provider(provider)
    _CONFIGURED = True
```

---

### Task 1: `_FilteringSpanExporter`

**Files:**
- Modify: `common/telemetry.py` (imports + new class/helpers; `setup()` untouched in this task)
- Test: `tests/test_telemetry.py`

**Interfaces:**
- Consumes: nothing from other tasks.
- Produces:
  - `SUPPRESSED_SCOPES: frozenset[str]` — `frozenset({"a2a-python-sdk"})`.
  - `_scope_name(span) -> str | None` — best-effort read of `span.instrumentation_scope.name`; returns `None` if the scope (or attribute) is absent.
  - `_FilteringSpanExporter(SpanExporter)` — `__init__(self, inner: SpanExporter)`; `export(spans)` forwards only spans whose `_scope_name` is not in `SUPPRESSED_SCOPES` (returns `SpanExportResult.SUCCESS` without calling `inner.export` when nothing remains); `shutdown()` and `force_flush(timeout_millis=30000)` delegate to `inner`.

- [ ] **Step 1: Write the failing tests**

Add to the top of `tests/test_telemetry.py` (after the existing `from common import telemetry` line) the imports:

```python
import types

from opentelemetry.sdk.trace.export import SpanExportResult
```

Then append these tests to `tests/test_telemetry.py`:

```python
class _RecordingExporter:
    """Inner exporter stub: records the span batches it receives."""

    def __init__(self):
        self.exported = []
        self.shutdown_called = False
        self.flushed = False

    def export(self, spans):
        self.exported.append(list(spans))
        return SpanExportResult.SUCCESS

    def shutdown(self):
        self.shutdown_called = True

    def force_flush(self, timeout_millis=30000):
        self.flushed = True
        return True


def _span(scope_name):
    """A minimal stand-in for a ReadableSpan carrying an instrumentation scope."""
    return types.SimpleNamespace(
        instrumentation_scope=types.SimpleNamespace(name=scope_name)
    )


def test_filtering_exporter_drops_a2a_scope_keeps_ours():
    inner = _RecordingExporter()
    exp = telemetry._FilteringSpanExporter(inner)
    a2a, ours = _span("a2a-python-sdk"), _span("common.llm")
    result = exp.export([a2a, ours])
    assert result == SpanExportResult.SUCCESS
    assert inner.exported == [[ours]]  # only our span forwarded


def test_filtering_exporter_short_circuits_when_all_dropped():
    inner = _RecordingExporter()
    exp = telemetry._FilteringSpanExporter(inner)
    result = exp.export([_span("a2a-python-sdk")])
    assert result == SpanExportResult.SUCCESS
    assert inner.exported == []  # inner.export never called when nothing remains


def test_filtering_exporter_keeps_span_with_missing_scope():
    inner = _RecordingExporter()
    exp = telemetry._FilteringSpanExporter(inner)
    span = types.SimpleNamespace(instrumentation_scope=None)  # defensive: no scope
    exp.export([span])
    assert inner.exported == [[span]]  # kept, no crash


def test_filtering_exporter_delegates_shutdown_and_flush():
    inner = _RecordingExporter()
    exp = telemetry._FilteringSpanExporter(inner)
    exp.shutdown()
    assert inner.shutdown_called
    assert exp.force_flush(1000) is True
    assert inner.flushed
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python -m pytest tests/test_telemetry.py -k filtering_exporter -v`
Expected: FAIL with `AttributeError: module 'common.telemetry' has no attribute '_FilteringSpanExporter'`

- [ ] **Step 3: Write the implementation**

In `common/telemetry.py`, extend the export import (line 11) from:

```python
from opentelemetry.sdk.trace.export import BatchSpanProcessor
```

to:

```python
from opentelemetry.sdk.trace.export import BatchSpanProcessor, SpanExporter, SpanExportResult
```

and add `import atexit` to the stdlib imports near the top (after `import os`):

```python
import atexit
import os
```

Then add, after the `_CONFIGURED = False` line, the suppression set, helper, and exporter:

```python
# The a2a-sdk instruments itself with OpenTelemetry under this single scope name
# (its INSTRUMENTING_MODULE_NAME), emitting a2a.server.* / a2a.client.* spans that
# form stray traces. Our own spans use module-name scopes, so an exact-match drop
# here never touches them.
SUPPRESSED_SCOPES = frozenset({"a2a-python-sdk"})


def _scope_name(span) -> "str | None":
    scope = getattr(span, "instrumentation_scope", None)
    return getattr(scope, "name", None) if scope is not None else None


class _FilteringSpanExporter(SpanExporter):
    """Wrap a SpanExporter, dropping spans whose instrumentation scope is in
    SUPPRESSED_SCOPES before delegating the rest."""

    def __init__(self, inner: SpanExporter) -> None:
        self._inner = inner

    def export(self, spans):
        kept = [s for s in spans if _scope_name(s) not in SUPPRESSED_SCOPES]
        if not kept:
            return SpanExportResult.SUCCESS
        return self._inner.export(kept)

    def shutdown(self):
        return self._inner.shutdown()

    def force_flush(self, timeout_millis: int = 30_000) -> bool:
        return self._inner.force_flush(timeout_millis)
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `python -m pytest tests/test_telemetry.py -k filtering_exporter -v`
Expected: PASS (4 tests)

- [ ] **Step 5: Commit**

```bash
git add common/telemetry.py tests/test_telemetry.py
git commit -m "feat(telemetry): add _FilteringSpanExporter to drop a2a-sdk span noise"
```

---

### Task 2: Wire filtering + atexit flush into `setup()`

**Files:**
- Modify: `common/telemetry.py` (the `if endpoint:` branch of `setup()`)
- Test: `tests/test_telemetry.py`

**Interfaces:**
- Consumes: `_FilteringSpanExporter` and the `atexit`/`BatchSpanProcessor` imports from Task 1.
- Produces: no new public symbols — `setup()` keeps its `(service_name: str) -> None` signature; behavior is additive and gated on `endpoint`.

- [ ] **Step 1: Write the failing tests**

Add to the imports of `tests/test_telemetry.py` (if not already present from Task 1):

```python
from unittest.mock import MagicMock
```

Then append these tests to `tests/test_telemetry.py`:

```python
def test_setup_wraps_exporter_and_registers_flush(monkeypatch):
    # Force the endpoint branch to run again in-process.
    monkeypatch.setattr(telemetry, "_CONFIGURED", False)
    monkeypatch.setenv("OTEL_EXPORTER_OTLP_ENDPOINT", "http://localhost:4318")

    # Stub the OTLP exporter at its import source so no network client is built.
    import opentelemetry.exporter.otlp.proto.http.trace_exporter as otlp_mod
    monkeypatch.setattr(otlp_mod, "OTLPSpanExporter", lambda *a, **k: object())

    # Spy on BatchSpanProcessor to capture the exporter it is constructed with.
    captured = {}

    class _SpyBSP:
        def __init__(self, exporter):
            captured["exporter"] = exporter

    monkeypatch.setattr(telemetry, "BatchSpanProcessor", _SpyBSP)

    # Keep the global provider untouched (avoids OTel "Overriding" warning noise).
    monkeypatch.setattr(telemetry.trace, "set_tracer_provider", lambda provider: None)

    reg = MagicMock()
    monkeypatch.setattr(telemetry.atexit, "register", reg)

    telemetry.setup("svc")

    assert isinstance(captured["exporter"], telemetry._FilteringSpanExporter)
    assert reg.call_count == 1
    assert getattr(reg.call_args[0][0], "__name__", "") == "shutdown"


def test_setup_without_endpoint_registers_no_flush(monkeypatch):
    monkeypatch.setattr(telemetry, "_CONFIGURED", False)
    monkeypatch.delenv("OTEL_EXPORTER_OTLP_ENDPOINT", raising=False)
    monkeypatch.setattr(telemetry.trace, "set_tracer_provider", lambda provider: None)

    reg = MagicMock()
    monkeypatch.setattr(telemetry.atexit, "register", reg)

    telemetry.setup("svc")

    assert reg.call_count == 0  # no flush handler when telemetry is off
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python -m pytest tests/test_telemetry.py -k "setup_wraps or setup_without_endpoint" -v`
Expected: `test_setup_wraps_exporter_and_registers_flush` FAILS — `captured["exporter"]` is a bare `OTLPSpanExporter` stub (an `object()`), not a `_FilteringSpanExporter`, and `reg.call_count` is `0` (no atexit yet). `test_setup_without_endpoint_registers_no_flush` may already pass (it asserts the unchanged no-op behavior).

- [ ] **Step 3: Write the implementation**

In `common/telemetry.py`, change the `if endpoint:` block of `setup()` from:

```python
    if endpoint:
        from opentelemetry.exporter.otlp.proto.http.trace_exporter import OTLPSpanExporter
        provider.add_span_processor(BatchSpanProcessor(OTLPSpanExporter()))
    trace.set_tracer_provider(provider)
```

to:

```python
    if endpoint:
        from opentelemetry.exporter.otlp.proto.http.trace_exporter import OTLPSpanExporter
        exporter = _FilteringSpanExporter(OTLPSpanExporter())
        provider.add_span_processor(BatchSpanProcessor(exporter))
        # Short-lived processes (the orchestrator) exit before BatchSpanProcessor's
        # timer fires; flush buffered spans on clean exit.
        atexit.register(provider.shutdown)
    trace.set_tracer_provider(provider)
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `python -m pytest tests/test_telemetry.py -k "setup_wraps or setup_without_endpoint" -v`
Expected: PASS (2 tests)

Then run the whole telemetry file and the full suite to confirm no regression and pristine output:

Run: `python -m pytest tests/test_telemetry.py -v`
Expected: PASS (all telemetry tests, including the existing `test_inject_then_extract_roundtrips_a_span`, `test_setup_is_idempotent`, `test_server_span_continues_remote_trace`)

Run: `python -m pytest -q`
Expected: full suite green — **52 passed** (46 baseline + 4 from Task 1 + 2 from Task 2), no new warnings beyond the pre-existing 102.

- [ ] **Step 5: Commit**

```bash
git add common/telemetry.py tests/test_telemetry.py
git commit -m "feat(telemetry): wrap exporter and flush on exit when OTLP is configured"
```

---

## Final verification

- [ ] `python -m pytest -q` — full suite green (52 passed), output pristine.
- [ ] Confirm scope: `git diff --name-only main...HEAD` shows only `common/telemetry.py`, `tests/test_telemetry.py`, and the spec/plan docs — no span-creation, agent, orchestrator, or Java files.
- [ ] Confirm the no-op path is untouched: with `OTEL_EXPORTER_OTLP_ENDPOINT` unset, `setup()` registers no atexit handler and wraps nothing (covered by `test_setup_without_endpoint_registers_no_flush`).
- [ ] (Optional, live) With Langfuse up + the OTLP env set, run an analysis and confirm the 2 stray `…JsonRpcDispatcher.handle_requests` traces no longer appear and the orchestrator's root span is present without a manual `shutdown()`.
