# Metrics via Langfuse Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Surface design §10.3's four metrics (per-agent request count, success/failure, A2A call duration, LLM token totals) by querying Langfuse's Metrics API over the traces already emitted in Scope C — no metric computation in our code.

**Architecture:** A pure-data module defines the metric queries once. An importable `common/` module holds the report logic (config, HTTP, formatting); a thin `scripts/` entrypoint runs it. A committed `dashboard.json` mirrors the same queries as UI widget specs, kept honest by a consistency test. Langfuse does all aggregation server-side; our code only asks and formats.

**Tech Stack:** Python 3.13 (venv), `httpx` (already a dep), `pytest`/`pytest-asyncio` (dev), Langfuse 3.195.0 self-hosted.

> **Post-implementation correction (live verification 2026-06-24):** the code/test blocks below use `/api/public/v2/metrics`, but that endpoint is **Langfuse-v4-only** and 404s on the pinned 3.x. The shipped code uses the **v1** path `/api/public/metrics` (identical query shape and `{aggregation}_{measure}` response). The blocks below are left as the original plan record; see `common/metrics_report.py` for the corrected path.

## Global Constraints

- **No new runtime dependencies.** `httpx` is already in `pyproject.toml`; use it. No Langfuse SDK.
- **No metric computation in our code** — no `MeterProvider`, OTel meters, counters, or histograms. Langfuse aggregates; we format.
- **No instrumentation changes** — do not edit `common/telemetry.py`, `common/llm.py`, `common/a2a_server.py`, `orchestrator/a2a_client.py`, `orchestrator/graph.py`, the Python agents, or any Java file.
- **Key-free tests** — everything mocked; no real network, no Langfuse keys in the suite. Mirrors the project's "everything mocked except in-process A2A round-trips" rule.
- **Graceful absence** — when Langfuse keys are unset the report prints guidance and exits 0 (telemetry is opt-in everywhere in this repo).
- **Public-repo rule** — no "Claude"/AI attribution in commit messages or tracked docs.
- **Models / span names are fixed inputs** (do not rename anything): analyst server spans are `"Fundamentals Analyst"`, `"News & Sentiment Analyst"`, `"Research & Debate Analyst"`; LLM spans `"chat claude-sonnet-4-6"` / `"chat claude-opus-4-8"`; client span `"a2a SendMessage"`; root `"analyze <ticker>"`.
- **Run from repo root** with the venv active (`. .venv/bin/activate`); `common` is import-available via `pip install -e ".[dev]"`.

## File Structure

| File | Responsibility |
| --- | --- |
| `common/metrics_queries.py` | NEW. Pure data: `QUERIES` — the 4 named Metrics-API query specs + their display columns. Zero imports. |
| `common/metrics_report.py` | NEW. Report logic (importable, testable): config loading, URL/param building, HTTP fetch, table formatting, `main()`. |
| `scripts/metrics_report.py` | NEW. Thin CLI entrypoint: `sys.exit(main(sys.argv[1:]))`. |
| `docker/langfuse/dashboard.json` | NEW. Committed dashboard + widget specs mirroring `QUERIES`. |
| `docker/langfuse/README.md` | MODIFY. Add a "Metrics" runbook section. |
| `tests/test_metrics_report.py` | NEW. Unit tests: query well-formedness, formatting, URL/auth, graceful absence, dashboard↔QUERIES consistency. |

**Refinement vs spec §5.2:** the spec put the report logic in `scripts/metrics_report.py`. Because `scripts/` is not an importable package (not in `[tool.setuptools.packages.find]`), the logic lives in `common/metrics_report.py` (importable + testable) and the `scripts/` file is a thin wrapper. Same design, testable realization.

---

### Task 1: Metric query definitions

**Files:**
- Create: `common/metrics_queries.py`
- Test: `tests/test_metrics_report.py`

**Interfaces:**
- Produces: `QUERIES: list[dict]`. Each item has keys: `"key": str`, `"title": str`, `"query": dict` (a Metrics-API query body with `view`/`metrics`/`dimensions`/`filters`, **without** timestamps), `"columns": list[tuple[str, str]]` (response-field, header). Response aggregate fields follow Langfuse's `{aggregation}_{measure}` convention.

- [ ] **Step 1: Write the failing test**

Add to `tests/test_metrics_report.py`:

```python
from common.metrics_queries import QUERIES


def test_queries_are_well_formed():
    assert len(QUERIES) == 4
    keys = {q["key"] for q in QUERIES}
    assert keys == {"requests_by_agent", "success_failure", "latency_by_span", "tokens_by_model"}
    for q in QUERIES:
        assert isinstance(q["title"], str) and q["title"]
        body = q["query"]
        assert body["view"] == "observations"
        assert body["metrics"] and all("measure" in m and "aggregation" in m for m in body["metrics"])
        assert isinstance(body["dimensions"], list)
        assert body["filters"] == []
        # timestamps are injected by the caller, never baked in
        assert "fromTimestamp" not in body and "toTimestamp" not in body
        assert q["columns"] and all(len(c) == 2 for c in q["columns"])
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/test_metrics_report.py::test_queries_are_well_formed -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'common.metrics_queries'`

- [ ] **Step 3: Write the implementation**

Create `common/metrics_queries.py`:

```python
"""Metric query specs for the Langfuse Metrics API (GET /api/public/v2/metrics).

Pure data — no imports, no I/O. Each query targets the ``observations`` view and
omits the time window (the caller injects ``fromTimestamp``/``toTimestamp``), so the
same body serves both the CLI report and the committed dashboard widgets.

Response aggregate fields follow Langfuse's ``{aggregation}_{measure}`` naming, e.g.
``count_count``, ``p95_latency``, ``sum_totalTokens``.
"""

QUERIES = [
    {
        "key": "requests_by_agent",
        "title": "Requests by span name",
        "query": {
            "view": "observations",
            "metrics": [{"measure": "count", "aggregation": "count"}],
            "dimensions": [{"field": "name"}],
            "filters": [],
        },
        "columns": [("name", "Span"), ("count_count", "Requests")],
    },
    {
        "key": "success_failure",
        "title": "Success / failure by level",
        "query": {
            "view": "observations",
            "metrics": [{"measure": "count", "aggregation": "count"}],
            "dimensions": [{"field": "level"}],
            "filters": [],
        },
        "columns": [("level", "Level"), ("count_count", "Count")],
    },
    {
        "key": "latency_by_span",
        "title": "Latency by span (p95 / avg)",
        "query": {
            "view": "observations",
            "metrics": [
                {"measure": "latency", "aggregation": "p95"},
                {"measure": "latency", "aggregation": "avg"},
            ],
            "dimensions": [{"field": "name"}],
            "filters": [],
        },
        "columns": [("name", "Span"), ("p95_latency", "p95"), ("avg_latency", "avg")],
    },
    {
        "key": "tokens_by_model",
        "title": "LLM tokens & cost by model",
        "query": {
            "view": "observations",
            "metrics": [
                {"measure": "totalTokens", "aggregation": "sum"},
                {"measure": "totalCost", "aggregation": "sum"},
            ],
            "dimensions": [{"field": "providedModelName"}],
            "filters": [],
        },
        "columns": [
            ("providedModelName", "Model"),
            ("sum_totalTokens", "Tokens"),
            ("sum_totalCost", "Cost"),
        ],
    },
]
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python -m pytest tests/test_metrics_report.py::test_queries_are_well_formed -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add common/metrics_queries.py tests/test_metrics_report.py
git commit -m "feat(metrics): define Langfuse Metrics-API query specs"
```

---

### Task 2: Pure helpers — URL, query param, table formatting

**Files:**
- Create: `common/metrics_report.py`
- Test: `tests/test_metrics_report.py`

**Interfaces:**
- Consumes: nothing from other tasks (pure functions).
- Produces:
  - `metrics_url(host: str) -> str` — strips a trailing `/` and returns `f"{host}/api/public/v2/metrics"`.
  - `build_query_param(body: dict, *, frm: str, to: str) -> str` — returns a JSON string equal to `body` plus `fromTimestamp=frm` and `toTimestamp=to` (does not mutate `body`).
  - `format_table(title: str, columns: list[tuple[str, str]], rows: list[dict]) -> str` — renders a fixed-width text table; missing fields render as empty; empty `rows` renders the header plus a `(no data ...)` line.

- [ ] **Step 1: Write the failing tests**

Add to `tests/test_metrics_report.py`:

```python
import json

from common import metrics_report as mr


def test_metrics_url_normalizes_trailing_slash():
    assert mr.metrics_url("http://localhost:3000/") == "http://localhost:3000/api/public/v2/metrics"
    assert mr.metrics_url("http://localhost:3000") == "http://localhost:3000/api/public/v2/metrics"


def test_build_query_param_injects_window_without_mutating():
    body = {"view": "observations", "metrics": [], "dimensions": [], "filters": []}
    out = mr.build_query_param(body, frm="2026-06-24T00:00:00Z", to="2026-06-24T12:00:00Z")
    parsed = json.loads(out)
    assert parsed["fromTimestamp"] == "2026-06-24T00:00:00Z"
    assert parsed["toTimestamp"] == "2026-06-24T12:00:00Z"
    assert parsed["view"] == "observations"
    assert "fromTimestamp" not in body  # original untouched


def test_format_table_renders_rows():
    cols = [("name", "Span"), ("count_count", "Requests")]
    rows = [{"name": "Fundamentals Analyst", "count_count": "1"}, {"name": "a2a SendMessage", "count_count": "3"}]
    out = mr.format_table("Requests by span name", cols, rows)
    assert "Requests by span name" in out
    assert "Span" in out and "Requests" in out
    assert "Fundamentals Analyst" in out and "a2a SendMessage" in out
    assert "3" in out


def test_format_table_handles_empty_rows():
    out = mr.format_table("Latency", [("name", "Span")], [])
    assert "Latency" in out
    assert "no data" in out.lower()
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python -m pytest tests/test_metrics_report.py -k "metrics_url or build_query_param or format_table" -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'common.metrics_report'`

- [ ] **Step 3: Write the implementation**

Create `common/metrics_report.py` with the imports and pure helpers (later tasks append to this file):

```python
"""Query the Langfuse Metrics API and print design §10.3's metrics as tables.

Langfuse computes every aggregate server-side; this module only builds queries,
fetches results, and formats them. Opt-in: prints guidance and exits 0 when the
Langfuse keys are unset.
"""
import json
import os
from dataclasses import dataclass

import httpx

from common.metrics_queries import QUERIES


def metrics_url(host: str) -> str:
    return host.rstrip("/") + "/api/public/v2/metrics"


def build_query_param(body: dict, *, frm: str, to: str) -> str:
    return json.dumps({**body, "fromTimestamp": frm, "toTimestamp": to})


def format_table(title: str, columns: list[tuple[str, str]], rows: list[dict]) -> str:
    headers = [h for _, h in columns]
    fields = [f for f, _ in columns]
    cells = [[("" if r.get(f) is None else str(r.get(f))) for f in fields] for r in rows]
    widths = [len(h) for h in headers]
    for row in cells:
        for i, val in enumerate(row):
            widths[i] = max(widths[i], len(val))
    line = "  ".join(h.ljust(widths[i]) for i, h in enumerate(headers))
    out = [title, line, "  ".join("-" * w for w in widths)]
    if not rows:
        out.append("(no data in window — widen --hours or run an analysis first)")
    else:
        for row in cells:
            out.append("  ".join(val.ljust(widths[i]) for i, val in enumerate(row)))
    return "\n".join(out)
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `python -m pytest tests/test_metrics_report.py -k "metrics_url or build_query_param or format_table" -v`
Expected: PASS (4 tests)

- [ ] **Step 5: Commit**

```bash
git add common/metrics_report.py tests/test_metrics_report.py
git commit -m "feat(metrics): pure helpers for URL, query param, table formatting"
```

---

### Task 3: Config, fetch, and run orchestration (mocked HTTP)

**Files:**
- Modify: `common/metrics_report.py` (append)
- Test: `tests/test_metrics_report.py`

**Interfaces:**
- Consumes: `metrics_url`, `build_query_param`, `format_table`, `QUERIES` (Task 1/2).
- Produces:
  - `@dataclass Config` with fields `host: str`, `public_key: str`, `secret_key: str`.
  - `load_config() -> Config | None` — reads `LANGFUSE_HOST` (default `http://localhost:3000`), `LANGFUSE_PUBLIC_KEY`, `LANGFUSE_SECRET_KEY`; returns `None` if either key is missing/blank.
  - `fetch(config: Config, body: dict, *, frm: str, to: str, client: httpx.Client) -> list[dict]` — GETs the metrics endpoint with Basic auth and `params={"query": build_query_param(...)}`, raises for HTTP status, returns `resp.json()["data"]`.
  - `run(config: Config, *, frm: str, to: str, client: httpx.Client) -> int` — for each `QUERIES` entry prints `format_table(...)`; on a per-query exception prints `"!! <title>: <err>"` and continues; returns `0` if any query succeeded else `1`.

- [ ] **Step 1: Write the failing tests**

Add to `tests/test_metrics_report.py`:

```python
from unittest.mock import MagicMock


def test_load_config_missing_keys_returns_none(monkeypatch):
    monkeypatch.delenv("LANGFUSE_PUBLIC_KEY", raising=False)
    monkeypatch.delenv("LANGFUSE_SECRET_KEY", raising=False)
    assert mr.load_config() is None


def test_load_config_present(monkeypatch):
    monkeypatch.setenv("LANGFUSE_HOST", "http://lf:3000")
    monkeypatch.setenv("LANGFUSE_PUBLIC_KEY", "pk")
    monkeypatch.setenv("LANGFUSE_SECRET_KEY", "sk")
    cfg = mr.load_config()
    assert cfg == mr.Config(host="http://lf:3000", public_key="pk", secret_key="sk")


def test_fetch_builds_request_and_returns_data():
    cfg = mr.Config(host="http://lf:3000", public_key="pk", secret_key="sk")
    resp = MagicMock()
    resp.json.return_value = {"data": [{"name": "Fundamentals Analyst", "count_count": "1"}]}
    resp.raise_for_status.return_value = None
    client = MagicMock()
    client.get.return_value = resp

    body = {"view": "observations", "metrics": [], "dimensions": [], "filters": []}
    data = mr.fetch(cfg, body, frm="2026-06-24T00:00:00Z", to="2026-06-24T12:00:00Z", client=client)

    assert data == [{"name": "Fundamentals Analyst", "count_count": "1"}]
    args, kwargs = client.get.call_args
    assert args[0] == "http://lf:3000/api/public/v2/metrics"
    assert kwargs["auth"] == ("pk", "sk")
    assert json.loads(kwargs["params"]["query"])["fromTimestamp"] == "2026-06-24T00:00:00Z"


def test_run_prints_all_tables(capsys):
    cfg = mr.Config(host="http://lf:3000", public_key="pk", secret_key="sk")
    resp = MagicMock()
    resp.json.return_value = {"data": [{"name": "Fundamentals Analyst", "count_count": "1",
                                        "level": "DEFAULT", "providedModelName": "claude-sonnet-4-6",
                                        "p95_latency": "2.0", "avg_latency": "2.0",
                                        "sum_totalTokens": "1240", "sum_totalCost": "0.01"}]}
    resp.raise_for_status.return_value = None
    client = MagicMock()
    client.get.return_value = resp

    code = mr.run(cfg, frm="2026-06-24T00:00:00Z", to="2026-06-24T12:00:00Z", client=client)

    out = capsys.readouterr().out
    assert code == 0
    assert "Requests by span name" in out
    assert "Success / failure by level" in out
    assert "Latency by span" in out
    assert "LLM tokens & cost by model" in out
    assert client.get.call_count == len(QUERIES)  # QUERIES imported at top in Task 1


def test_run_continues_on_query_error(capsys):
    cfg = mr.Config(host="http://lf:3000", public_key="pk", secret_key="sk")
    client = MagicMock()
    client.get.side_effect = RuntimeError("boom")
    code = mr.run(cfg, frm="a", to="b", client=client)
    out = capsys.readouterr().out
    assert code == 1
    assert "!!" in out  # error marker printed, no traceback
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python -m pytest tests/test_metrics_report.py -k "load_config or fetch or run_prints or run_continues" -v`
Expected: FAIL with `AttributeError: module 'common.metrics_report' has no attribute 'Config'`

- [ ] **Step 3: Write the implementation**

Append to `common/metrics_report.py`:

```python
@dataclass
class Config:
    host: str
    public_key: str
    secret_key: str


def load_config() -> "Config | None":
    host = os.getenv("LANGFUSE_HOST", "http://localhost:3000")
    public_key = os.getenv("LANGFUSE_PUBLIC_KEY", "")
    secret_key = os.getenv("LANGFUSE_SECRET_KEY", "")
    if not public_key or not secret_key:
        return None
    return Config(host=host, public_key=public_key, secret_key=secret_key)


def fetch(config: Config, body: dict, *, frm: str, to: str, client: httpx.Client) -> list[dict]:
    resp = client.get(
        metrics_url(config.host),
        params={"query": build_query_param(body, frm=frm, to=to)},
        auth=(config.public_key, config.secret_key),
    )
    resp.raise_for_status()
    return resp.json().get("data", [])


def run(config: Config, *, frm: str, to: str, client: httpx.Client) -> int:
    succeeded = 0
    for q in QUERIES:
        try:
            rows = fetch(config, q["query"], frm=frm, to=to, client=client)
        except Exception as exc:  # one bad query must not abort the whole report
            print(f"!! {q['title']}: {exc}\n")
            continue
        print(format_table(q["title"], q["columns"], rows))
        print()
        succeeded += 1
    return 0 if succeeded else 1
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `python -m pytest tests/test_metrics_report.py -v`
Expected: PASS (all tests so far)

- [ ] **Step 5: Commit**

```bash
git add common/metrics_report.py tests/test_metrics_report.py
git commit -m "feat(metrics): config loading, HTTP fetch, and report orchestration"
```

---

### Task 4: CLI entrypoint (`main` + thin script)

**Files:**
- Modify: `common/metrics_report.py` (append `main`)
- Create: `scripts/metrics_report.py`
- Test: `tests/test_metrics_report.py`

**Interfaces:**
- Consumes: `load_config`, `run` (Task 3).
- Produces:
  - `main(argv: list[str] | None = None) -> int` — parses `--hours` (int, default 24), `--from`, `--to` (ISO 8601; override the window); computes `frm`/`to` (UTC, `...Z`); if `load_config()` is `None`, prints a guidance line and returns `0`; else opens an `httpx.Client` and returns `run(...)`.
- `scripts/metrics_report.py` runs `sys.exit(main(sys.argv[1:]))`.

- [ ] **Step 1: Write the failing tests**

Add to `tests/test_metrics_report.py`:

```python
def test_main_graceful_absence(monkeypatch, capsys):
    monkeypatch.delenv("LANGFUSE_PUBLIC_KEY", raising=False)
    monkeypatch.delenv("LANGFUSE_SECRET_KEY", raising=False)
    code = mr.main(["--hours", "1"])
    out = capsys.readouterr().out
    assert code == 0
    assert "LANGFUSE_PUBLIC_KEY" in out or "keys" in out.lower()


def test_main_runs_with_config(monkeypatch, capsys):
    monkeypatch.setenv("LANGFUSE_PUBLIC_KEY", "pk")
    monkeypatch.setenv("LANGFUSE_SECRET_KEY", "sk")
    called = {}

    def fake_run(config, *, frm, to, client):
        called["frm"] = frm
        called["to"] = to
        print("ran")
        return 0

    monkeypatch.setattr(mr, "run", fake_run)
    code = mr.main(["--from", "2026-06-01T00:00:00Z", "--to", "2026-06-02T00:00:00Z"])
    assert code == 0
    assert called["frm"] == "2026-06-01T00:00:00Z"
    assert called["to"] == "2026-06-02T00:00:00Z"
    assert "ran" in capsys.readouterr().out
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python -m pytest tests/test_metrics_report.py -k "main_graceful or main_runs" -v`
Expected: FAIL with `AttributeError: module 'common.metrics_report' has no attribute 'main'`

- [ ] **Step 3: Write the implementation**

Append to `common/metrics_report.py`:

```python
import argparse
from datetime import datetime, timedelta, timezone


def _iso(dt: datetime) -> str:
    return dt.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def main(argv: "list[str] | None" = None) -> int:
    parser = argparse.ArgumentParser(description="Print Langfuse-derived metrics (design §10.3).")
    parser.add_argument("--hours", type=int, default=24, help="window size, hours back from now (default 24)")
    parser.add_argument("--from", dest="frm", help="ISO 8601 window start (overrides --hours)")
    parser.add_argument("--to", dest="to", help="ISO 8601 window end (defaults to now)")
    args = parser.parse_args(argv)

    now = datetime.now(timezone.utc)
    to = args.to or _iso(now)
    frm = args.frm or _iso(now - timedelta(hours=args.hours))

    config = load_config()
    if config is None:
        print(
            "Metrics need Langfuse keys. Set LANGFUSE_PUBLIC_KEY and LANGFUSE_SECRET_KEY "
            "(and optionally LANGFUSE_HOST). See docker/langfuse/README.md → Metrics."
        )
        return 0

    with httpx.Client(timeout=30) as client:
        return run(config, frm=frm, to=to, client=client)
```

Put the `import argparse` and `from datetime import ...` lines at the **top** of the file with the other imports (shown here inline for locality; move them up when editing).

Create `scripts/metrics_report.py`:

```python
#!/usr/bin/env python
"""CLI: print Langfuse-derived metrics. See docker/langfuse/README.md → Metrics."""
import sys

from common.metrics_report import main

if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `python -m pytest tests/test_metrics_report.py -v`
Expected: PASS (all)

Also verify the script wires up (graceful-absence path, no keys needed):

Run: `python scripts/metrics_report.py --hours 1`
Expected: prints the "Metrics need Langfuse keys…" line and exits 0.

- [ ] **Step 5: Commit**

```bash
git add common/metrics_report.py scripts/metrics_report.py tests/test_metrics_report.py
git commit -m "feat(metrics): CLI entrypoint with time-window flags"
```

---

### Task 5: Dashboard spec + consistency test

**Files:**
- Create: `docker/langfuse/dashboard.json`
- Test: `tests/test_metrics_report.py`

**Interfaces:**
- Consumes: `QUERIES` (Task 1).
- Produces: `docker/langfuse/dashboard.json` — `{"name", "description", "widgets": [...]}`. Each widget has `key`, `title`, `chartType`, and `view`/`metrics`/`dimensions`/`filters` byte-equal to the matching `QUERIES` entry's `query`. A test enforces this so the dashboard never drifts from the script.

- [ ] **Step 1: Write the failing test**

Add to `tests/test_metrics_report.py`:

```python
from pathlib import Path

DASHBOARD = Path(__file__).resolve().parent.parent / "docker" / "langfuse" / "dashboard.json"


def test_dashboard_widgets_match_queries():
    spec = json.loads(DASHBOARD.read_text())
    widgets = {w["key"]: w for w in spec["widgets"]}
    assert set(widgets) == {q["key"] for q in QUERIES}
    for q in QUERIES:
        w = widgets[q["key"]]
        for field in ("view", "metrics", "dimensions", "filters"):
            assert w[field] == q["query"][field], f"{q['key']}.{field} drifted from QUERIES"
        assert w["chartType"]
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/test_metrics_report.py::test_dashboard_widgets_match_queries -v`
Expected: FAIL with `FileNotFoundError` (dashboard.json missing)

- [ ] **Step 3: Write the implementation**

Create `docker/langfuse/dashboard.json`:

```json
{
  "name": "Trading Firm — Agent Metrics",
  "description": "Design §10.3 metrics derived from A2A/LLM traces. Langfuse 3.x has no dashboard import API; recreate these widgets in the UI (Dashboards → New) using the view/metrics/dimensions/filters below. See README → Metrics.",
  "widgets": [
    {
      "key": "requests_by_agent",
      "title": "Requests by span name",
      "chartType": "BAR_TIME_SERIES",
      "view": "observations",
      "metrics": [{"measure": "count", "aggregation": "count"}],
      "dimensions": [{"field": "name"}],
      "filters": []
    },
    {
      "key": "success_failure",
      "title": "Success / failure by level",
      "chartType": "BAR_TIME_SERIES",
      "view": "observations",
      "metrics": [{"measure": "count", "aggregation": "count"}],
      "dimensions": [{"field": "level"}],
      "filters": []
    },
    {
      "key": "latency_by_span",
      "title": "Latency by span (p95 / avg)",
      "chartType": "LINE_TIME_SERIES",
      "view": "observations",
      "metrics": [
        {"measure": "latency", "aggregation": "p95"},
        {"measure": "latency", "aggregation": "avg"}
      ],
      "dimensions": [{"field": "name"}],
      "filters": []
    },
    {
      "key": "tokens_by_model",
      "title": "LLM tokens & cost by model",
      "chartType": "BAR_TIME_SERIES",
      "view": "observations",
      "metrics": [
        {"measure": "totalTokens", "aggregation": "sum"},
        {"measure": "totalCost", "aggregation": "sum"}
      ],
      "dimensions": [{"field": "providedModelName"}],
      "filters": []
    }
  ]
}
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python -m pytest tests/test_metrics_report.py::test_dashboard_widgets_match_queries -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add docker/langfuse/dashboard.json tests/test_metrics_report.py
git commit -m "feat(metrics): committed Langfuse dashboard spec mirroring the queries"
```

---

### Task 6: Metrics runbook

**Files:**
- Modify: `docker/langfuse/README.md`

**Interfaces:** none (documentation).

- [ ] **Step 1: Read the current README to find the insertion point**

Run: `sed -n '1,60p' docker/langfuse/README.md`
Expected: see the existing Scope C runbook sections; pick the end of the file (or after the verification section) for the new "## Metrics" heading.

- [ ] **Step 2: Append the Metrics section**

Add to the end of `docker/langfuse/README.md`:

```markdown
## Metrics (design §10.3)

The four §10.3 metrics — per-agent request count, success/failure, A2A call duration,
and LLM token totals — are **derived from the traces already in Langfuse**, not emitted
as a separate signal. Langfuse computes every aggregate server-side; we just query it.

### CLI report

1. Bring the stack up and run an analysis so traces exist (see the verification section
   above).
2. Export the project keys (the same pair used for the OTLP `Authorization` header):

   ```bash
   export LANGFUSE_HOST=http://localhost:3000
   export LANGFUSE_PUBLIC_KEY=pk-lf-...
   export LANGFUSE_SECRET_KEY=sk-lf-...
   ```
3. Run the report (defaults to the last 24h; `--hours N`, or `--from/--to` ISO 8601):

   ```bash
   python scripts/metrics_report.py --hours 24
   ```

   With keys unset it prints a one-line hint and exits 0 (telemetry is opt-in).

### Reproduce a metric with curl (no script)

```bash
curl -s -u "$LANGFUSE_PUBLIC_KEY:$LANGFUSE_SECRET_KEY" -G \
  --data-urlencode 'query={"view":"observations","metrics":[{"measure":"count","aggregation":"count"}],"dimensions":[{"field":"name"}],"filters":[],"fromTimestamp":"2026-06-24T00:00:00Z","toTimestamp":"2026-06-25T00:00:00Z"}' \
  http://localhost:3000/api/public/v2/metrics
```

### UI dashboard

Langfuse 3.x has no dashboard import API, so `docker/langfuse/dashboard.json` is the
version-controlled spec. To build it: **Dashboards → New dashboard**, then add one widget
per entry in `dashboard.json`, copying its `view` / `metrics` / `dimensions` / `filters`
and `chartType`. The widget queries are byte-identical to `common/metrics_queries.py`
(a test enforces this).

> Per-agent latency reads from the analyst **server** spans (distinct names). The client
> `a2a SendMessage` spans share one name, so they show aggregate round-trip latency, not a
> per-agent breakdown — see the design doc §6.1.
```

- [ ] **Step 3: Verify the suite still passes and the docs render**

Run: `python -m pytest tests/test_metrics_report.py -v`
Expected: PASS (all metrics tests)

Run: `python -m pytest -q`
Expected: the full suite passes (previously 28 passed; now higher with the new tests).

- [ ] **Step 4: Commit**

```bash
git add docker/langfuse/README.md
git commit -m "docs(metrics): runbook for the CLI report, curl queries, and UI dashboard"
```

---

## Final verification

- [ ] Run the whole Python suite: `python -m pytest -q` — all pass, key-free.
- [ ] Run `python scripts/metrics_report.py` with no keys — prints guidance, exits 0.
- [ ] Confirm no edits leaked into `common/telemetry.py`, `common/llm.py`, `common/a2a_server.py`, `orchestrator/`, the agents, or any Java file: `git diff --name-only main...HEAD` shows only the six files from the File Structure table.
- [ ] (Optional, live) With the Langfuse stack up + keys exported + an analysis run, `python scripts/metrics_report.py` prints the four populated tables.
```
