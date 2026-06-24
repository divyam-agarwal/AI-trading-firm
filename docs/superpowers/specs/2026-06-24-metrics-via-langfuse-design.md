# Design — Metrics via Langfuse

Status: approved (2026-06-24). Implements the **metrics** half of design §10.3 by
*deriving* metrics from the traces already emitted in Tracing Scope C, rather than
emitting a second OTel metrics signal.

## 1. Goal

Surface the four metrics named in the master design (§10.3):

1. **Per-agent request count**
2. **Success / failure** (error rate)
3. **A2A call duration**
4. **LLM token totals** (and, for free, cost)

…by querying **Langfuse's Metrics API** over the spans the system already exports.
Langfuse is the compute engine — it aggregates server-side (ClickHouse). **Our code
performs no metric calculation**: no summing tokens, no percentiles, no counters.

## 2. Why not emit OTel metrics (MeterProvider/counters/histograms)?

Considered and rejected for this milestone. The four §10.3 metrics are all derivable
from the trace data Scope C already sends to Langfuse:

| Metric | Already present in our spans |
| --- | --- |
| Token totals / cost | `gen_ai.usage.*` on every LLM span (Scope C); Langfuse derives cost from model id + tokens |
| A2A / call duration | Langfuse auto-computes observation latency from each span's start/end timestamps |
| Request count | one observation per span; each agent's server span has a distinct name |
| Success / failure | we already `set_status(ERROR)` on exceptions → Langfuse observation `level` |

A parallel OTel metrics pipeline would be **redundant** with this, and — because
Langfuse ingests traces only, not OTLP metrics — would additionally require a metrics
backend (OTel Collector + Prometheus) the repo does not have. At portfolio volume the
production advantages of a true metrics signal (pre-aggregated time series that survive
trace sampling) do not apply. Emitting OTel metrics remains a possible *future*
milestone if the goal becomes "demonstrate the OTel metrics signal" specifically; it is
explicitly out of scope here.

## 3. Non-goals

- No `MeterProvider`, OTel meters, counters, or histograms.
- No metrics backend (no Prometheus, no OTel Collector) added to `docker/`.
- **No instrumentation changes** to `common/`, `orchestrator/`, the Python agents, or
  the Java agent. The span names and attributes from Scope A/B/C are sufficient.
- No new runtime dependency on the Langfuse SDK (we stay OTLP-native; the report script
  uses plain `httpx` against the public REST API).

## 4. Architecture & data flow

```
(already done, Scope C)        (this milestone)
agents + orchestrator  --OTLP-->  Langfuse  <--HTTP GET /api/public/v2/metrics--  metrics_report.py
                                  (ClickHouse aggregates)                          (prints a table)
                                       ^
                                       |  same query bodies described by
                                  docker/langfuse/dashboard.json (UI widgets)
```

Single source of truth: the ~4 Metrics-API query bodies are defined **once** in a small
module and consumed by both the CLI script and (as documentation) the dashboard spec.

## 5. Components

### 5.1 Query definitions — `common/metrics_queries.py`

A pure-data module: a list of named metric queries, each a dict matching the Metrics API
`query` shape. No I/O, no Langfuse import, no other imports — so it lives in `common/`
(the shared, importable package) without adding any runtime coupling and without touching
the SDK-isolation or no-op-telemetry invariants. Consumed by the script and the tests;
trivially unit-testable. Example shape:

```python
QUERIES = [
    {
        "key": "requests_by_agent",
        "title": "Requests by agent",
        "query": {
            "view": "observations",
            "metrics": [{"measure": "count", "aggregation": "count"}],
            "dimensions": [{"field": "name"}],
            "filters": [],
        },
    },
    # success/failure (dimension level), a2a latency (measure latency),
    # token totals (measure totalTokens + totalCost, dimension providedModelName)
]
```

`fromTimestamp`/`toTimestamp` are **not** baked into the query bodies — they are filled
in by the caller from CLI flags (default: last 24h), so the same query body serves both
the script and the dashboard widget.

### 5.2 CLI report — `scripts/metrics_report.py`

Thin Metrics-API client:

1. Read config from env (mirrors Scope C): `LANGFUSE_HOST` (default
   `http://localhost:3000`), `LANGFUSE_PUBLIC_KEY`, `LANGFUSE_SECRET_KEY`.
2. If keys are missing, print a friendly "metrics need Langfuse keys; see runbook"
   message and exit 0 (graceful absence, like the rest of the telemetry stack).
3. For each query in `QUERIES`, GET `{host}/api/public/v2/metrics?query=<url-encoded
   JSON>` with HTTP Basic auth (`public:secret`), over a time window from `--hours`
   (default 24) or explicit `--from`/`--to` flags.
4. Format each result set as a small text table and print it.

The script does **no aggregation** — it formats whatever rows Langfuse returns. Response
field names follow the Metrics API convention `{aggregation}_{measure}` (e.g.
`count_count`, `sum_totalTokens`, `p95_latency`).

### 5.3 Dashboard spec — `docker/langfuse/dashboard.json`

A committed JSON document describing the dashboard and its widgets. Each widget carries
the same `view`/`dimensions`/`metrics`/`filters` as a query in §5.1 (mirroring Langfuse's
`DashboardWidget` model) plus a `chartType`. **Langfuse 3.x has no public dashboard
import API** — dashboards are DB-backed and built via the UI. So `dashboard.json` is the
version-controlled *specification*; the runbook documents recreating it in the UI from
these widget configs. This keeps the dashboard reproducible and reviewable in git without
pretending an import path exists.

### 5.4 Runbook — section in `docker/langfuse/README.md`

Adds a "Metrics" section:
1. Bring the Langfuse stack up and run an analysis so traces exist (links existing Scope C
   steps).
2. Export `LANGFUSE_HOST` / `LANGFUSE_PUBLIC_KEY` / `LANGFUSE_SECRET_KEY`.
3. `python scripts/metrics_report.py` → the metrics table.
4. Raw `curl` query bodies for each metric (reproduce without the script — mirrors how
   Scope C documented verifying traces via the public API).
5. Steps to build the matching UI dashboard from `dashboard.json`'s widget specs.

## 6. The metric → query mapping

All queries use `view: observations`.

| Metric | measure / aggregation | dimension(s) | Notes |
| --- | --- | --- | --- |
| Per-agent request count | `count` / `count` | `name` | rows keyed by span name; analyst server spans are distinct ("Fundamentals Analyst", "News & Sentiment Analyst", "Research & Debate Analyst") |
| Success / failure | `count` / `count` | `level` (and optionally `name`) | `level` = `DEFAULT` (ok) vs `ERROR`; populated by existing `set_status(ERROR)` |
| A2A call duration | `latency` / `p95` (+ `avg`) | `name` | per-agent via analyst server-span names; aggregate round-trip via the `a2a SendMessage` client span |
| LLM token totals | `totalTokens` / `sum` (+ `totalCost` / `sum`) | `providedModelName` | from Scope C `gen_ai.usage.*`; Langfuse derives cost |

### 6.1 Accepted limitation — per-agent *client-side* A2A latency

Every orchestrator client span is named `a2a SendMessage`, so the Metrics API (which
groups by `name`, not by arbitrary metadata) cannot break client round-trip latency down
per agent. We therefore report **per-agent latency from the server spans** (distinct
names) and use the `a2a SendMessage` span only for the aggregate client round-trip. This
avoids any change to `orchestrator/a2a_client.py`. If a per-agent client breakdown is
wanted later, the minimal change is to fold the agent name into the client span name
(e.g. `a2a SendMessage fundamentals`) — noted, not done.

## 7. Error handling & graceful absence

- Missing Langfuse keys → friendly message, exit 0 (no traceback). Consistent with the
  "telemetry is opt-in / no-op when unconfigured" invariant.
- HTTP / network errors against Langfuse → caught per query; print which metric failed
  and continue with the rest, so one bad query doesn't abort the whole report. Exit
  non-zero only if every query failed.
- Empty result set (no traces in window) → print the table header with a "no data in
  window — widen --hours or run an analysis first" hint.

## 8. Testing

Python suite only (the milestone is consumer-side tooling; **no Java changes**):

- **Query construction:** assert each entry in `QUERIES` is well-formed (has `view`,
  `metrics`, `dimensions`) and that the caller correctly injects the time window and
  url-encodes the `query` param.
- **Response formatting:** feed a canned Metrics-API JSON response (mocked `httpx`) and
  assert the printed table contains the expected rows/values. No real network, no keys.
- **Graceful absence:** with keys unset, assert the script exits 0 with the guidance
  message and makes no HTTP call.

All key-free, mirroring the project's "everything mocked except in-process A2A
round-trips" philosophy.

## 9. Files touched

| File | Change |
| --- | --- |
| `common/metrics_queries.py` | new — query definitions (pure data, zero imports) |
| `scripts/metrics_report.py` | new — CLI Metrics-API client + table printer |
| `docker/langfuse/dashboard.json` | new — committed dashboard/widget spec |
| `docker/langfuse/README.md` | edit — add "Metrics" runbook section |
| `tests/test_metrics_report.py` | new — query + formatting + graceful-absence tests |

The only `common/` addition is the pure-data `metrics_queries.py` (zero imports). No
changes to existing `common/` modules, the agents, the orchestrator graph/client, or any
Java file.

## 10. Out of scope / future

- Emitting a true OTel metrics signal (MeterProvider) + a Prometheus/OTel-Collector
  backend — a separate milestone if "demonstrate the metrics signal" becomes a goal.
- structlog JSON logging carrying `trace_id` (design §10.3, separate deferred step).
- Folding agent name into the client span name for per-agent client-latency grouping.
