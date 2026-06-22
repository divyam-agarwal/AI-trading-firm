# AI Trading Firm

A showcase of **heterogeneous AI agents coordinating over a standard protocol**. Specialized analyst agents (each an independent service) collaborate in a predefined workflow, orchestrated by a state machine, to produce an investment memo.

> ⚠️ This is a **technical demonstration of multi-agent coordination**, not financial advice.

## The idea

Inspired by [TauricResearch/TradingAgents](https://github.com/TauricResearch/TradingAgents), but re-architected so that each agent is an **independent service that talks to the others over the [A2A protocol](https://a2a-protocol.org/)** — proving agents built on different technology stacks can coordinate, with the orchestrator agnostic to each agent's internals.

- **Orchestrator** — a LangGraph state machine; fans out to analysts in parallel, then synthesizes.
- **Fundamentals Analyst** — valuation signals (Python; later swappable for a Java/Spring service at the same A2A contract).
- **News & Sentiment Analyst** — news sentiment scoring.
- **Research & Debate Analyst** — bull-vs-bear synthesis into a BUY / HOLD / SELL memo.
- **Observability** — distributed tracing (OpenTelemetry) and LLM observability (Langfuse). The Python orchestrator and both Python agents share one trace: the orchestrator opens a root span, injects W3C trace context into each A2A call, and the agent servers extract it and parent their server and LLM spans into the same trace. The Java/Spring agent joining the trace, plus a Langfuse viewer with token/cost, land in later milestones.

## Status

🚧 Early development — design and implementation plan are committed; build in progress.

- Design: [`docs/superpowers/specs/`](docs/superpowers/specs/)
- Implementation plan: [`docs/superpowers/plans/`](docs/superpowers/plans/)

## Tech

Python · A2A · LangGraph · Claude (Anthropic SDK) · OpenTelemetry · Langfuse

## Python version

Targets Python 3.12+. Venv built with Python 3.13.7 (`/usr/local/bin/python3.13`); python3.12 is not present on this machine.

## Run (Phase 1)

```bash
pip install -e ".[dev]"
export ANTHROPIC_API_KEY=sk-ant-...
./scripts/run_all.sh AAPL
```

Optional observability: set `OTEL_EXPORTER_OTLP_ENDPOINT` and `LANGFUSE_*` to send traces to a collector / Langfuse.

### Cross-tech interop (M3): Java/Spring Boot Fundamentals agent

The Fundamentals analyst (`:9001`) also ships as a **Java/Spring Boot** A2A service
(`agents/fundamentals-java/`) serving the identical A2A contract. The LangGraph
orchestrator calls it with **zero changes** — proof that heterogeneous agents coordinate
over the standard A2A wire protocol.

```bash
# Build once (JDK 21 + Maven):
mvn -q -f agents/fundamentals-java/pom.xml package

# Run the full pipeline with the Java agent on :9001 (Python sentiment/debate on :9002/:9003):
set -a; source .env; set +a
./scripts/run_all_java.sh AAPL
```

Java agent stack: Spring Boot + a small A2A controller, Claude via the Anthropic Java SDK.
The all-Python pipeline (`./scripts/run_all.sh`) is unchanged. Demo only, not financial advice.
