# Design — Telemetry polish

Status: approved (2026-06-30). Two small, independent fixes to `common/telemetry.py`
surfaced during the Tracing Scope C live verification and the Metrics live run.

> **Decision (2026-06-30, during implementation): feature (a) "flush on exit" was
> DROPPED — only feature (b) shipped.** Verifying the installed OTel SDK showed
> `TracerProvider(shutdown_on_exit=True)` (the default) *already* does
> `atexit.register(self.shutdown)`, so an explicit `atexit.register` is redundant on a
> clean exit. And it does not address the actual Scope C span loss, which came from
> `run_all_java.sh` **SIGTERM-killing** the orchestrator — `atexit` (OTel's or ours) does
> not run on a signal kill. Properly fixing the kill case (a force-flush in `main.py` after
> `run()`, or a graceful shutdown in the run scripts) is deferred as separate work. The
> sections below are kept as the original design record; only §4.1 + the exporter-wrapping
> half of §4.2 were implemented.

## 1. Goal

1. **Flush on exit** — short-lived processes (the orchestrator) must not silently drop
   their spans when they exit, without the caller having to call `provider.shutdown()`
   by hand.
2. **Suppress a2a-sdk self-instrumentation at the source** — the a2a-sdk instruments
   *itself* with OpenTelemetry, emitting `a2a.server.*` / `a2a.client.*` spans that form
   2 stray Langfuse traces per run (named `…JsonRpcDispatcher.handle_requests`). Drop
   them before export so they never reach the backend.

Both are opt-in: they only take effect when `OTEL_EXPORTER_OTLP_ENDPOINT` is set. When it
is unset, telemetry stays a complete no-op (the project-wide invariant), so tests and
quick local runs are unaffected.

## 2. Background / why these two

- **Flush:** `TracerProvider` uses a `BatchSpanProcessor`, which buffers spans and exports
  them on a timer or at `shutdown()`. The orchestrator process prints its memo and exits
  almost immediately, so its root span + A2A client spans are still buffered and lost. The
  Scope C live run worked around this by calling `trace.get_tracer_provider().shutdown()`
  manually and sleeping. An `atexit` handler makes a clean exit flush automatically.
- **a2a-sdk noise:** verified — the SDK creates its tracer with
  `trace.get_tracer(INSTRUMENTING_MODULE_NAME)` where `INSTRUMENTING_MODULE_NAME =
  "a2a-python-sdk"` (`a2a/utils/telemetry.py`). So **every** SDK-internal span carries the
  instrumentation scope name `"a2a-python-sdk"`. Our own spans use module names as scopes
  (`common.telemetry`, `common.llm`, `orchestrator.graph`, `orchestrator.a2a_client`), so
  an exact-match drop on `"a2a-python-sdk"` removes the noise with zero risk to our spans.
  This is the emission-side complement to the report-side filter already shipped in
  `common/metrics_report.py` (`_clean`).

## 3. Non-goals

- No change to span creation, attributes, or names anywhere (`llm.py`, `a2a_server.py`,
  `a2a_client.py`, `graph.py`, the agents — untouched).
- No Java changes. The Java agent does not use a2a-sdk (no self-noise) and is a long-lived
  server (no premature-exit span loss).
- No new dependencies. No metrics/logging work (those are separate deferred items).
- No change to the public `telemetry` API (`setup`/`tracer`/`inject`/`extract`/
  `server_span` keep their signatures).

## 4. Design

All changes live in `common/telemetry.py`, inside the existing `if endpoint:` branch of
`setup()` (so the no-op path is literally unchanged).

### 4.1 `_FilteringSpanExporter`

A thin wrapper around any `SpanExporter` that drops spans by instrumentation-scope name
before delegating:

```python
SUPPRESSED_SCOPES = frozenset({"a2a-python-sdk"})

class _FilteringSpanExporter(SpanExporter):
    """Wrap a SpanExporter, dropping spans whose instrumentation scope is in
    SUPPRESSED_SCOPES (the a2a-sdk self-instruments and emits stray traces).
    Our own spans use module-name scopes, so they are never matched."""

    def __init__(self, inner: SpanExporter) -> None:
        self._inner = inner

    def export(self, spans):
        kept = [s for s in spans if s.instrumentation_scope.name not in SUPPRESSED_SCOPES]
        if not kept:
            return SpanExportResult.SUCCESS
        return self._inner.export(kept)

    def shutdown(self):
        return self._inner.shutdown()

    def force_flush(self, timeout_millis: int = 30_000):
        return self._inner.force_flush(timeout_millis)
```

Notes:
- `ReadableSpan.instrumentation_scope` is the OTel SDK attribute carrying the scope; `.name`
  is the string passed to `get_tracer(...)`. (Defensive: if `instrumentation_scope` were
  ever `None`, treat the span as kept — never crash the export path.)
- When everything in a batch is filtered out, return `SUCCESS` without calling the inner
  exporter (avoids an empty export round-trip).
- `SUPPRESSED_SCOPES` is a module-level `frozenset` so the set of suppressed scopes is
  visible and extensible in one place.

### 4.2 Wiring in `setup()`

Current:

```python
if endpoint:
    from ...http.trace_exporter import OTLPSpanExporter
    provider.add_span_processor(BatchSpanProcessor(OTLPSpanExporter()))
trace.set_tracer_provider(provider)
```

Becomes:

```python
if endpoint:
    from ...http.trace_exporter import OTLPSpanExporter
    exporter = _FilteringSpanExporter(OTLPSpanExporter())
    provider.add_span_processor(BatchSpanProcessor(exporter))
    atexit.register(provider.shutdown)
trace.set_tracer_provider(provider)
```

- The filter wraps the OTLP exporter so the drop happens at export time, *after*
  `BatchSpanProcessor` has batched — the minimal idiomatic spot.
- `atexit.register(provider.shutdown)` is inside the `if endpoint:` branch, so no handler is
  registered (and no flush attempted) when telemetry is off. `provider.shutdown()` flushes
  the `BatchSpanProcessor` and is idempotent; registering it once per configured process is
  correct (`setup()` is already guarded by the module-level `_CONFIGURED` flag, so it runs
  once).

### 4.3 Why an exporter wrapper (vs alternatives)

- **Sampler:** rejected — `Sampler.should_sample(...)` does not receive the instrumentation
  scope, so it cannot decide based on `"a2a-python-sdk"`.
- **Custom SpanProcessor:** workable but must re-implement `on_start`/`on_end`/`shutdown`/
  `force_flush` delegation to the batch processor. More surface than the exporter wrapper.
- **Exporter wrapper (chosen):** only `export`/`shutdown`/`force_flush` to delegate; runs
  after batching; reads `instrumentation_scope.name` directly off `ReadableSpan`.

## 5. Error handling

- Filtering is pure and total; a missing/`None` `instrumentation_scope` is treated as
  "keep" so the export path never raises on a malformed span.
- `atexit` handlers that raise would surface a traceback at interpreter exit;
  `provider.shutdown()` on the OTel SDK is best-effort and does not raise in normal use, so
  no extra guard is added (keeping it minimal). If this ever proves noisy, wrapping the
  registered callable is a one-line follow-up.

## 6. Testing (`tests/test_telemetry.py`, key-free, no network)

1. **`_FilteringSpanExporter` drops the a2a scope, keeps ours.** Build an inner stub
   exporter (records what it received). Feed two fake spans — one with
   `instrumentation_scope.name == "a2a-python-sdk"`, one with `"common.llm"`. Assert the
   inner exporter received only the `"common.llm"` span and `export` returned `SUCCESS`.
2. **All-filtered batch short-circuits.** Feed only an `"a2a-python-sdk"` span; assert the
   inner exporter's `export` was **not** called and the result is `SUCCESS`.
3. **Delegation.** Assert `shutdown()` and `force_flush()` call through to the inner
   exporter.
4. **Wiring — endpoint set.** With `OTEL_EXPORTER_OTLP_ENDPOINT` set and
   `telemetry._CONFIGURED` reset to `False`, patch (in the `telemetry` module namespace) the
   `OTLPSpanExporter` import site to a stub, `BatchSpanProcessor` to a spy that captures its
   single constructor arg, and `atexit.register` to a mock. Call `setup("svc")` and assert:
   (a) `atexit.register` was called once with a callable whose `__name__ == "shutdown"`
   (the provider's flush), and (b) the arg captured by the `BatchSpanProcessor` spy is a
   `_FilteringSpanExporter` (i.e. the OTLP exporter was wrapped). **Do not** read the result
   back off `trace.get_tracer_provider()` — OTel's `set_tracer_provider` is set-once
   globally (conftest relies on this), so the global provider may not be the one `setup()`
   just built. Verifying via the patched constructors is provider-independent.
5. **Wiring — endpoint unset.** With the env var removed and `_CONFIGURED` reset and
   `atexit.register` patched, call `setup("svc")`; assert `atexit.register` was **not**
   called (no flush handler when telemetry is off). The existing `test_setup_is_idempotent`
   / inject-extract tests must still pass.

All tests that exercise the `endpoint` branch reset `telemetry._CONFIGURED` first (the
module guard makes `setup()` one-shot) and patch the OTLP exporter / `BatchSpanProcessor` in
the `telemetry` namespace so nothing touches the network and no real global provider swap is
asserted against.

## 7. Files touched

| File | Change |
| --- | --- |
| `common/telemetry.py` | add `import atexit`; add `_FilteringSpanExporter` + `SUPPRESSED_SCOPES`; wrap the exporter and register the atexit flush inside the existing `if endpoint:` branch |
| `tests/test_telemetry.py` | add the 5 tests in §6 |

No other files change.

## 8. Out of scope / future

- Removing the manual `shutdown()` + sleep workaround from any live-run scripts/runbooks is
  optional cleanup, not required by this change (the atexit handler makes the manual call
  redundant but harmless).
- If `atexit` flush proves insufficient for hard kills (SIGKILL), a signal handler is a
  separate, larger concern — not pursued.
