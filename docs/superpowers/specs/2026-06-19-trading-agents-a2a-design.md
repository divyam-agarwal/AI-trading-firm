# TradingAgents-A2A — Design

**Date:** 2026-06-19
**Status:** Approved (design) — pending spec review before implementation
**Author:** Divyam (with Claude)

## 1. Purpose & Goals

A **portfolio/learning showcase** demonstrating two capabilities that are usually shown separately:

1. **Organized, predefined multi-agent coordination** — agents collaborate in a fixed, well-defined flow (not free-form chatter).
2. **Cross-technology interoperability** — agents built on *different technology stacks* coordinate over a standard wire protocol, with the orchestrator agnostic to each agent's internals.

The domain is a **financial analysis crew** inspired by [TauricResearch/TradingAgents](https://github.com/TauricResearch/TradingAgents). TradingAgents nails predefined coordination (a LangGraph pipeline with a bull/bear debate) but is a **single monolithic in-process graph** — it does *not* demonstrate cross-tech interop. This project keeps the compelling, CFA-relevant domain and re-architects the agents as **independent A2A services**, which is the differentiating contribution.

### Success criteria
- A user runs one command with a ticker and gets a synthesized BUY/HOLD/SELL memo produced by multiple coordinating agents.
- Agents run as independent processes communicating over **A2A** (JSON-RPC/HTTP), discovered via **Agent Cards**.
- The orchestration flow is **predefined and visualizable** (a LangGraph `StateGraph`).
- **Proof of interop:** one Python agent can be replaced by a **Java/Spring Boot** agent at the same A2A contract, with **zero changes** to the orchestrator.

### Non-goals (YAGNI)
- Real trading, brokerage integration, or real money. This is a coordination demo, **not financial advice**.
- Dynamic/agent-led orchestration (an LLM deciding who to call at runtime) — explicitly out of scope; it contradicts the "predefined" goal.
- Faithful clone of all ~7 TradingAgents roles. We use a lean roster.
- Auth/multi-tenant/production hardening of the A2A endpoints.

## 2. Background: A2A primer (for reference)

- **Agent Card** — JSON at `/.well-known/agent-card.json` describing an agent (name, URL, skills, capabilities). Enables discovery.
- **Server (Remote Agent)** — exposes skills over A2A. **Client** — calls a remote agent. An agent can be both.
- **Task** — a unit of work with a lifecycle: `submitted → working → completed/failed/input-required`.
- **Message** — a turn (role `user`/`agent`) composed of **Parts** (text / file / structured data).
- **Artifact** — the output a task produces.
- **Wire protocol** — JSON-RPC 2.0 over HTTP; `message/send` (sync) and `message/stream` (SSE). Any language that serves HTTP can participate — this is what guarantees cross-tech interop.
- **Key mental model:** A2A is the transport/discovery layer *between* agents; it is **not** the orchestrator. Something must still decide who runs when — here that is LangGraph.

## 3. Chosen Approach

**LangGraph orchestrator + A2A agents as graph nodes.**

A LangGraph `StateGraph` defines the predefined flow; each node performs an A2A client call to a remote agent. This blends "organized coordination" (the graph) with "different technologies" (A2A calls to independent services), and leverages existing LangGraph familiarity (`langchain-langgraph-demo`). The graph is visualizable, which is itself a demo asset.

**Approaches considered and rejected:**
- *Plain-Python asyncio orchestrator* — simplest and most transparent, but less reusable/visual and a weaker résumé signal.
- *Agent-led dynamic orchestration* — most "agentic" but contradicts the predefined-flow goal and is harder to make reliable in a demo.

## 4. Architecture

```
                         ┌─────────────────────────────┐
                         │   Orchestrator (LangGraph)  │
   user: "Analyze AAPL"  │   StateGraph + A2A client   │
   ───────────────────►  │   plan → fan-out → join     │
                         │        → synthesize         │
                         └──────┬───────────┬──────────┘
                                │ A2A        │ A2A         (JSON-RPC/HTTP)
                 ┌──────────────▼──┐   ┌─────▼─────────────┐
                 │ Fundamentals     │   │ News & Sentiment  │   ← run in PARALLEL
                 │ Analyst (:9001)  │   │ Analyst (:9002)   │
                 │ Py → Java(Ph.2)  │   │ Python            │
                 └──────────────┬──┘   └─────┬─────────────┘
                                │             │
                                └──────┬──────┘
                                       │ A2A (both reports)
                              ┌────────▼──────────┐
                              │ Research/Debate    │   ← bull vs bear, then memo
                              │ Analyst (:9003) Py │
                              └────────┬──────────┘
                                       │ final memo (Artifact)
                                       ▼
                                  Orchestrator → user
```

Each agent is an **independent process** with its own Agent Card. The orchestrator knows only their URLs, never their internals.

## 5. Components

### 5.1 Orchestrator (LangGraph `StateGraph`, A2A client only)
- Nodes: `plan` → `gather` (fan-out to the two analysts in parallel) → `debate` (call Research agent) → `finish`.
- Holds the shared `State`; each node issues an A2A `message/send`.
- Entry point: CLI for v1 (`python -m orchestrator.main AAPL`); optional FastAPI later.
- Helper `a2a_client.py`: resolve Agent Card, send message, extract result Part/Artifact.

### 5.2 Fundamentals Analyst (`:9001`)
- **Skill:** `analyze_fundamentals(ticker) → report`. Fetches financials (mock JSON v1; optionally yfinance) and produces a valuation summary.
- Phase 1: Python (`a2a-sdk`). **Phase 2: replaced by a Spring Boot service** at the same URL/contract — orchestrator unchanged.

### 5.3 News & Sentiment Analyst (`:9002`)
- **Skill:** `analyze_sentiment(ticker) → report`. Pulls recent headlines, scores sentiment via LLM. Runs **in parallel** with Fundamentals.

### 5.4 Research/Debate Analyst (`:9003`)
- **Skill:** `synthesize(fundamentals_report, sentiment_report) → memo`. Runs an internal bull-vs-bear LLM exchange, then emits a `BUY/HOLD/SELL` recommendation + rationale memo as an A2A **Artifact**.

## 6. Data Flow & Shared State

Orchestrator holds a typed `State`:

```python
class State(TypedDict):
    ticker: str
    fundamentals: str | None      # filled by :9001
    sentiment: str | None         # filled by :9002
    memo: str | None              # filled by :9003
    recommendation: str | None    # BUY/HOLD/SELL parsed from memo
```

- `gather` writes `fundamentals` + `sentiment` concurrently (parallel fan-out).
- `debate` reads both and writes `memo` + `recommendation`.
- Reports pass as A2A text/data **Parts**; the final memo returns as an **Artifact**.

## 7. Tech Stack

| Concern | Choice | Why |
|---|---|---|
| A2A | `a2a-sdk` (official) + `uvicorn`/Starlette | Standard protocol; Agent Card + JSON-RPC for free |
| Orchestration | LangGraph | Predefined `StateGraph`; already familiar; visualizable |
| LLM | Claude via `anthropic` SDK — `claude-sonnet-4-6` for analysts, `claude-opus-4-8` for debate | Latest models; per-agent model choice mirrors "complex vs quick" split |
| HTTP client | `httpx` (async) | Used by a2a-sdk |
| Data (Fundamentals) | Mock JSON v1; swappable for a free API (e.g. yfinance) | Deterministic demo; real API optional |
| Java agent (Phase 2) | Spring Boot + small A2A controller | Plays to Java/Spring background |

## 8. Project Layout

```
trading-agents-a2a/
├── orchestrator/        # LangGraph graph + A2A client + CLI entry
│   ├── graph.py
│   ├── a2a_client.py    # resolve card, send_message, extract result
│   └── main.py          # `python -m orchestrator.main AAPL`
├── agents/
│   ├── fundamentals/    # a2a server (Phase 1 Python)
│   ├── sentiment/
│   └── debate/
├── common/              # shared schemas, prompts, model config
├── tests/
├── scripts/run_all.sh   # launch all agents + run a query
└── pyproject.toml
```

Each agent folder has the same shape: `executor.py` (the `AgentExecutor`), `card.py` (Agent Card), `server.py` (uvicorn entry on its port).

## 9. Error Handling

- **Agent unreachable / card fetch fails:** orchestrator surfaces a clear error naming the agent + URL; fail fast (no silent partial memos).
- **One analyst fails during fan-out:** mark that report `unavailable`, let debate proceed with a noted gap (graceful degradation); configurable to fail-hard.
- **A2A task `failed` / timeout:** per-call `httpx` timeout; one bounded retry, then propagate.
- **Malformed LLM output (no clear BUY/HOLD/SELL):** debate agent re-prompts once, then defaults to `HOLD` with a flagged note.

## 10. Testing Strategy

- **Unit:** each `AgentExecutor`'s core logic with the LLM call mocked → deterministic.
- **A2A contract test:** spin up each agent, fetch its Agent Card, send one `message/send`, assert a well-formed Task/Artifact returns.
- **Orchestrator integration:** run the full graph against **stub A2A agents** (fixed responses) — verifies fan-out/join/sequencing with no LLM cost or flakiness.
- **Phase-2 swap test:** the same contract test must pass against the Java agent unchanged — the proof of interop.

## 11. Phasing / Milestones

- **M1:** One Python A2A agent (Fundamentals) + a minimal orchestrator that calls it. End-to-end "hello A2A."
- **M2:** All three Python agents + full LangGraph flow (parallel fan-out + debate). **Phase 1 complete — a standalone working project.**
- **M3:** Swap Fundamentals for the Spring Boot agent, orchestrator untouched. **The interop money-shot.**
- **M4 (optional):** FastAPI/web entry + LangGraph diagram export for the demo.

## 12. Risks & Notes

- **a2a-sdk API churn:** the SDK is young; pin a version and verify the exact `AgentExecutor`/client API at implementation time.
- **Python 3.14:** confirm a2a-sdk + langgraph + anthropic wheels support 3.14; fall back to a 3.12 venv if needed.
- **LLM cost/flakiness in tests:** mitigated by mocking LLM in unit tests and stubbing agents in integration tests.
- **Disclaimer:** outputs and README must state this is a technical demo of agent coordination, **not financial advice**.
