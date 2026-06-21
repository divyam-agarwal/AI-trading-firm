# M3 — Java/Spring Boot Fundamentals Agent (Interop)

**Date:** 2026-06-20
**Status:** Approved (design) — pending spec review before implementation
**Author:** Divyam
**Milestone:** M3 (the cross-tech interop money-shot), Scope A — functional interop only

## 1. Purpose & Goal

Replace the Python Fundamentals analyst on `:9001` with a **Java/Spring Boot** A2A service
that serves the **byte-identical A2A contract**, proving heterogeneous agents coordinate over
a standard wire protocol. The orchestrator (`orchestrator/`) and the shared wrappers
(`common/`) must require **zero changes**.

### Success criterion

`./scripts/run_all_java.sh AAPL` launches the Java agent on `:9001` (plus the existing Python
sentiment/debate agents) and produces a synthesized BUY/HOLD/SELL memo — with **no edits** to
`orchestrator/a2a_client.py`, `orchestrator/graph.py`, or `common/`.

### Scope (decided during brainstorming)

- **Scope A — functional interop only.** Tracing/Langfuse is explicitly **out of scope** for M3
  (see §8). The Java agent tolerates and ignores any trace-context metadata on requests; it
  creates no spans and exports nothing.
- **A2A in Java:** a **hand-rolled Spring `@RestController`** reproducing the captured wire
  shape — *not* an A2A Java SDK (see §3 for why).
- **LLM in Java:** the **official Anthropic Java SDK** (`com.anthropic:anthropic-java`),
  producing a real Claude valuation summary equivalent to the Python agent.
- **Coexistence, not deletion:** the Python `agents/fundamentals/` stays; the Java agent is
  added alongside and selected by a launch script.

## 2. The Verified Wire Contract

These shapes were captured **live** from the running Python agent + the real `a2a-sdk` client
(a2a-sdk==1.1.0). They are the source of truth — they deviate from the published A2A spec, so
the Java service must match *these bytes*, not the spec docs.

### 2.1 Agent Card — `GET /.well-known/agent-card.json`

Returns `200` with this JSON (camelCase keys; protobuf-derived):

```json
{
  "name": "Fundamentals Analyst",
  "description": "Evaluates company financials and valuation. Demo only, not financial advice.",
  "supportedInterfaces": [
    {
      "url": "http://127.0.0.1:9001/",
      "protocolBinding": "JSONRPC",
      "protocolVersion": "1.0"
    }
  ],
  "version": "0.1.0",
  "capabilities": { "streaming": false },
  "defaultInputModes": ["text/plain"],
  "defaultOutputModes": ["text/plain"],
  "skills": [
    {
      "id": "analyze_fundamentals",
      "name": "Analyze Fundamentals",
      "description": "Evaluates company financials and valuation. Demo only, not financial advice.",
      "tags": ["finance"]
    }
  ]
}
```

The Python `A2ACardResolver` parses this and the client uses `supportedInterfaces[0].url` as the
POST target. Replicating this JSON exactly is sufficient for discovery.

### 2.2 Request — `POST /`

JSON-RPC 2.0, **gRPC-transcoded** (note `"SendMessage"`, not `"message/send"`; enum
`"ROLE_USER"`):

```json
{
  "method": "SendMessage",
  "params": {
    "message": {
      "messageId": "<uuid>",
      "role": "ROLE_USER",
      "parts": [{ "text": "AAPL" }]
    },
    "configuration": {}
  },
  "id": "<request-id>",
  "jsonrpc": "2.0"
}
```

Optional: a `metadata` map (string→string) may be present on the request when the orchestrator
injects W3C trace context. In Scope A this is **tolerated and ignored**.

### 2.3 Response

```json
{
  "result": {
    "message": {
      "messageId": "<new-uuid>",
      "role": "ROLE_AGENT",
      "parts": [{ "text": "<valuation summary>" }]
    }
  },
  "id": "<echoed request-id>",
  "jsonrpc": "2.0"
}
```

The client extracts `result.message.parts[].text` and concatenates. The response is a single
**Message**, not a Task/Artifact — match that.

### 2.4 Robustness rules

- Echo the request `id` back unchanged; always include `"jsonrpc": "2.0"`.
- A request with a `method` other than `SendMessage` returns a JSON-RPC error object
  (`{"error": {"code": -32601, "message": "Method not found"}, "id": <echo>, "jsonrpc": "2.0"}`).
- Jackson is configured to **ignore unknown properties** so `configuration`, `metadata`, and any
  future fields deserialize without error.

## 3. Why a hand-rolled controller (not an A2A Java SDK)

The Python client emits the gRPC-transcoded shape above (`SendMessage`, `ROLE_USER`, camelCase
card). An A2A Java SDK may default to the spec's `message/send` JSON-RPC form, which would **not
match** what the Python client sends/expects — silently defeating the zero-change goal — and adds
another young SDK's churn. A small controller that reproduces the captured bytes is guaranteed to
match and keeps full control of the wire. The original project spec already calls for a "small A2A
controller," consistent with this choice.

## 4. Module Layout

New Maven project at `agents/fundamentals-java/` (JDK 21, Maven 3.9.9 — both installed locally):

```
agents/fundamentals-java/
├── pom.xml                       # Spring Boot + Anthropic Java SDK + test deps
└── src/
    ├── main/java/com/tradingfirm/fundamentals/
    │   ├── FundamentalsApplication.java   # @SpringBootApplication, server.port=9001
    │   ├── A2AController.java             # GET card + POST / (JSON-RPC SendMessage)
    │   ├── FundamentalsService.java       # fixtures → prompt → Claude call → summary
    │   ├── FundamentalsData.java          # AAPL/TSLA/default fixtures (mirror of data.py)
    │   ├── AnthropicClientConfig.java     # builds the Anthropic client bean from env key
    │   └── dto/                           # AgentCard, JsonRpcRequest/Response, Message, Part…
    └── test/java/com/tradingfirm/fundamentals/
        ├── A2AControllerTest.java         # MockMvc: card JSON + SendMessage envelope
        └── FundamentalsServiceTest.java   # logic with Anthropic client mocked
```

The Python `agents/fundamentals/` is untouched and remains the all-Python launch path.

## 5. LLM Call (parity with the Python agent)

`FundamentalsService`:
- Loads fixtures for the ticker from `FundamentalsData` — mirror of `agents/fundamentals/data.py`:
  `AAPL {pe 31.2, rev_growth 0.08, d/e 1.5, fcf_yield 0.03}`, `TSLA {62.0, 0.19, 0.3, 0.02}`,
  default `{20.0, 0.05, 1.0, 0.04}`; ticker upper-cased.
- Builds the same prompt as `logic.py`: *"Given these fundamentals for {ticker}: {facts}. Summarize
  the valuation picture in 3-4 sentences and state whether fundamentals look attractive, neutral,
  or expensive."*
- System prompt: *"You are a fundamentals analyst. Be concise. This is a technical demo, not
  financial advice."*
- Model: `claude-sonnet-4-6` (the analyst model; exact string, no date suffix, no
  `temperature`/`budget_tokens`). Calls the **official Anthropic Java SDK**; API key from
  `ANTHROPIC_API_KEY`. The exact SDK model-string/parameter usage will be confirmed against the
  `claude-api` skill before implementation.

## 6. Build & Run

- Build: `mvn -q -f agents/fundamentals-java/pom.xml package` → executable Spring Boot jar.
- New `scripts/run_all_java.sh`: launches the Java jar on `:9001`, Python sentiment on `:9002`,
  Python debate on `:9003`, then runs `python -m orchestrator.main <TICKER>`. Mirrors the
  structure of `scripts/run_all.sh` (which is left untouched as the all-Python path), including
  the `set -a; source .env` key-export workflow and a readiness wait before invoking the
  orchestrator.

## 7. Testing Strategy

Preserves Phase 1's invariant: the default `python -m pytest -q` stays at **18 passed, no API key
needed**.

- **JUnit (key-free, LLM mocked):**
  - `A2AControllerTest` (MockMvc): asserts `GET /.well-known/agent-card.json` returns the exact
    card JSON of §2.1, and that a `SendMessage` POST yields the §2.3 envelope (id echoed,
    `ROLE_AGENT`, text part present), with the service layer mocked. This is the highest-value,
    key-free guard on wire compatibility.
  - `FundamentalsServiceTest`: Anthropic client mocked; asserts fixture lookup (AAPL/TSLA/default,
    case-insensitive) and prompt/system-prompt construction.
- **Python interop proof (the headline test):** one pytest, marked integration and **auto-skipped**
  when the jar isn't built or `ANTHROPIC_API_KEY` is absent, that launches the built jar on `:9001`
  and runs the existing A2A contract assertions — and the full orchestrator — against it,
  confirming the Python `a2a_client`/orchestrator works unchanged. Because it is skipped by
  default, the standard suite remains 18-pass and key-free.

## 8. Out of Scope (deferred)

- **Tracing / Langfuse.** The Java agent ignores trace-context metadata; it creates no spans and
  exports nothing. Server-side trace extraction (Phase-1 deferred item #2) and the end-to-end
  "one trace across Python + Java in Langfuse" remain a separate, later milestone — to be done
  once, across both languages, rather than half-built here. (Rationale: tracing is currently only
  scaffolded even in Python — orchestrator opens no real root span, server-side `extract()` is
  unwired, Langfuse has no wiring code — so it is a cross-cutting effort independent of the swap.)
- Real financial data (yfinance), auth, streaming/SSE, additional skills.

## 9. Docs & Public-Repo Rules

- Update `README.md`: note the Java agent and how to run the swap (`run_all_java.sh`).
- Update the original design spec's M3 status and the gitignored `HANDOFF.md`.
- **Public-repo rule:** no Claude/AI authorship attribution in tracked docs or commit messages;
  naming "Claude (Anthropic Java SDK)" as a tech-stack item is fine. Strip any `Co-Authored-By`
  trailer before pushing.

## 10. Risks & Notes

- **Wire drift:** any mismatch (method name, enum casing, camelCase keys, single-Message vs Task)
  breaks the zero-change goal. Mitigated by the captured contract (§2) and the MockMvc + Python
  interop tests.
- **Anthropic Java SDK specifics:** model-string format and required params differ from Python;
  confirm against the `claude-api` skill at implementation time.
- **Port conflict:** only one process may own `:9001`; `run_all_java.sh` must not also start the
  Python fundamentals agent.
- **Disclaimer:** outputs and docs state this is a technical demo of agent coordination, not
  financial advice.
