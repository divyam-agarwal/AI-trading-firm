# AI Trading Firm

A showcase of **heterogeneous AI agents coordinating over a standard protocol**. Specialized analyst agents (each an independent service) collaborate in a predefined workflow, orchestrated by a state machine, to produce an investment memo.

> ⚠️ This is a **technical demonstration of multi-agent coordination**, not financial advice.

## The idea

Inspired by [TauricResearch/TradingAgents](https://github.com/TauricResearch/TradingAgents), but re-architected so that each agent is an **independent service that talks to the others over the [A2A protocol](https://a2a-protocol.org/)** — proving agents built on different technology stacks can coordinate, with the orchestrator agnostic to each agent's internals.

- **Orchestrator** — a LangGraph state machine; fans out to analysts in parallel, then synthesizes.
- **Fundamentals Analyst** — valuation signals (Python; later swappable for a Java/Spring service at the same A2A contract).
- **News & Sentiment Analyst** — news sentiment scoring.
- **Research & Debate Analyst** — bull-vs-bear synthesis into a BUY / HOLD / SELL memo.
- **Observability** — end-to-end distributed tracing (OpenTelemetry) and LLM observability (Langfuse), where a single trace spans every agent.

## Status

🚧 Early development — design and implementation plan are committed; build in progress.

- Design: [`docs/superpowers/specs/`](docs/superpowers/specs/)
- Implementation plan: [`docs/superpowers/plans/`](docs/superpowers/plans/)

## Tech

Python · A2A · LangGraph · Claude (Anthropic SDK) · OpenTelemetry · Langfuse

## Python version

Targets Python 3.12+. Venv built with Python 3.13.7 (`/usr/local/bin/python3.13`); python3.12 is not present on this machine.
