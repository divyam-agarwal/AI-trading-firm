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
