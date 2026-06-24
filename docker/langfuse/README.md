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
  http://localhost:3000/api/public/metrics
```

> Endpoint is the **v1** Metrics API (`/api/public/metrics`) — correct for self-hosted
> Langfuse 3.x. The `/api/public/v2/metrics` path is Langfuse-v4-only and returns 404 on
> 3.x; the query shape and `{aggregation}_{measure}` response naming are identical.

### UI dashboard

Langfuse 3.x has no dashboard import API, so `docker/langfuse/dashboard.json` is the
version-controlled spec. To build it: **Dashboards → New dashboard**, then add one widget
per entry in `dashboard.json`, copying its `view` / `metrics` / `dimensions` / `filters`
and `chartType`. The widget queries are byte-identical to `common/metrics_queries.py`
(a test enforces this).

> Per-agent latency reads from the analyst **server** spans (distinct names). The client
> `a2a SendMessage` spans share one name, so they show aggregate round-trip latency, not a
> per-agent breakdown — see the design doc §6.1.

> The CLI report hides two kinds of no-signal rows for readability: the a2a-sdk's own
> self-instrumentation spans (dotted names like `a2a.server.*` / `a2a.client.*`; our real
> `a2a SendMessage` span is kept) and rows whose grouping dimension is empty (e.g. the
> non-LLM `providedModelName: null` row in tokens-by-model). The raw `curl` query and the
> UI dashboard show everything, unfiltered. Suppressing the a2a-sdk spans at the *source*
> (so they never reach Langfuse) remains a separate telemetry-polish step.
