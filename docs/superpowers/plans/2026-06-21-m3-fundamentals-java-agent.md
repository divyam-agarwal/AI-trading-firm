# M3 — Java/Spring Boot Fundamentals Agent Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace the Python Fundamentals agent on `:9001` with a Java/Spring Boot A2A service serving the byte-identical contract, so `orchestrator/` and `common/` need zero changes.

**Architecture:** A standalone Maven module at `agents/fundamentals-java/` runs a Spring Boot app on port 9001. A hand-rolled `@RestController` serves two endpoints that reproduce the captured a2a-sdk wire shape: `GET /.well-known/agent-card.json` (the camelCase Agent Card) and `POST /` (JSON-RPC 2.0 `SendMessage`). A `FundamentalsService` mirrors the Python agent's fixtures + prompt and calls Claude via the official Anthropic Java SDK. The Python agent stays in place; a launch script selects which one runs on 9001.

**Tech Stack:** Java 21, Maven 3.9, Spring Boot 3 (`spring-boot-starter-web`), Jackson, official Anthropic Java SDK (`com.anthropic:anthropic-java`), JUnit 5 + Spring MockMvc; existing Python `a2a-sdk` client for the interop proof.

## Global Constraints

These apply to every task. Copied verbatim from the spec (`docs/superpowers/specs/2026-06-20-m3-fundamentals-java-agent-design.md`).

- **Zero changes to `orchestrator/` or `common/`.** The Java service must match the captured wire bytes; do not touch the Python client/server wrappers.
- **Wire contract (source of truth — captured live, deviates from A2A docs):**
  - `GET /.well-known/agent-card.json` → camelCase keys: `supportedInterfaces[].url` = `http://127.0.0.1:9001/`, `protocolBinding` = `"JSONRPC"`, `protocolVersion` = `"1.0"`; `capabilities.streaming` = `false`; skill id `analyze_fundamentals`.
  - `POST /` request: `{"method":"SendMessage","params":{"message":{"messageId":...,"role":"ROLE_USER","parts":[{"text":"AAPL"}]},"configuration":{}},"id":<id>,"jsonrpc":"2.0"}` — method is `SendMessage` (NOT `message/send`); role enum string `ROLE_USER`.
  - `POST /` response: `{"result":{"message":{"messageId":<uuid>,"role":"ROLE_AGENT","parts":[{"text":<summary>}]}},"id":<echoed id>,"jsonrpc":"2.0"}` — single Message, not a Task/Artifact.
  - Unknown method → `{"error":{"code":-32601,"message":"Method not found"},"id":<echoed id>,"jsonrpc":"2.0"}`.
  - Tolerate and ignore unknown request fields (`metadata`, `configuration`). Scope A: no tracing.
- **Port 9001.** Only one process owns it; the launch script must not also start the Python fundamentals agent.
- **LLM call:** model string exactly `claude-sonnet-4-6` (no date suffix). Request is minimal — model + maxTokens + system + user message only. NO `temperature`/`top_p`/`top_k`/`budget_tokens`/`thinking`/prefill (these 400 on current models). API key from `ANTHROPIC_API_KEY` env.
- **Prompt parity with Python** (`agents/fundamentals/logic.py` + `data.py`): same fixtures, same prompt text, same system prompt (reproduced verbatim in Task 3/4).
- **Public-repo rule:** no Claude/AI authorship attribution in tracked docs or commit messages; "Claude (Anthropic Java SDK)" as a stack item is fine. Strip any `Co-Authored-By` trailer before pushing.
- **Default `python -m pytest -q` stays at 18 passed, no API key needed.** The new Python interop test must auto-skip when the jar isn't built (and run key-free via the stub flag when it is).
- **Branch:** all work on `m3-fundamentals-java-agent` (already checked out).

## File Structure

```
agents/fundamentals-java/
├── pom.xml                                   # Spring Boot + Anthropic Java SDK + test deps
├── .gitignore                                # target/
└── src/
    ├── main/
    │   ├── java/com/tradingfirm/fundamentals/
    │   │   ├── FundamentalsApplication.java          # @SpringBootApplication; server.port=9001
    │   │   ├── A2AController.java                    # GET card + POST / (SendMessage)
    │   │   ├── FundamentalsService.java              # fixtures → prompt → Claude (or stub) → summary
    │   │   ├── FundamentalsData.java                  # AAPL/TSLA/default fixtures (mirror of data.py)
    │   │   ├── AnthropicClientConfig.java            # Anthropic client bean from ANTHROPIC_API_KEY
    │   │   └── dto/
    │   │       ├── AgentCard.java                    # card + nested AgentInterface, Capabilities, Skill
    │   │       ├── JsonRpcRequest.java               # method, params, id, jsonrpc
    │   │       ├── JsonRpcResponse.java              # result|error, id, jsonrpc
    │   │       └── A2AMessage.java                    # messageId, role, parts[]  (+ Part{text})
    │   └── resources/
    │       └── application.properties                # server.port=9001
    └── test/java/com/tradingfirm/fundamentals/
        ├── FundamentalsApplicationTests.java         # context loads
        ├── A2AControllerTest.java                    # MockMvc: card JSON + SendMessage envelope
        ├── FundamentalsDataTest.java                 # fixture lookup
        └── FundamentalsServiceTest.java              # prompt build w/ Anthropic client mocked

scripts/run_all_java.sh                               # Java :9001 + Python :9002/:9003 + orchestrator
tests/test_java_interop.py                            # Python: build+launch jar, call_agent round-trip (skippable)
README.md                                             # (modified) note the Java agent + swap run
```

---

### Task 1: Maven module scaffold + Spring Boot app on :9001

**Files:**
- Create: `agents/fundamentals-java/pom.xml`
- Create: `agents/fundamentals-java/.gitignore`
- Create: `agents/fundamentals-java/src/main/resources/application.properties`
- Create: `agents/fundamentals-java/src/main/java/com/tradingfirm/fundamentals/FundamentalsApplication.java`
- Test: `agents/fundamentals-java/src/test/java/com/tradingfirm/fundamentals/FundamentalsApplicationTests.java`

**Interfaces:**
- Consumes: nothing.
- Produces: a buildable Spring Boot app. Package `com.tradingfirm.fundamentals`. Main class `FundamentalsApplication`. Server binds `server.port=9001`.

- [ ] **Step 1: Write `pom.xml`**

```xml
<?xml version="1.0" encoding="UTF-8"?>
<project xmlns="http://maven.apache.org/POM/4.0.0"
         xmlns:xsi="http://www.w3.org/2001/XMLSchema-instance"
         xsi:schemaLocation="http://maven.apache.org/POM/4.0.0 http://maven.apache.org/xsd/maven-4.0.0.xsd">
    <modelVersion>4.0.0</modelVersion>

    <parent>
        <groupId>org.springframework.boot</groupId>
        <artifactId>spring-boot-starter-parent</artifactId>
        <version>3.3.5</version>
        <relativePath/>
    </parent>

    <groupId>com.tradingfirm</groupId>
    <artifactId>fundamentals-java</artifactId>
    <version>0.1.0</version>
    <name>Fundamentals Analyst (Java)</name>
    <description>A2A Fundamentals agent. Demo only, not financial advice.</description>

    <properties>
        <java.version>21</java.version>
    </properties>

    <dependencies>
        <dependency>
            <groupId>org.springframework.boot</groupId>
            <artifactId>spring-boot-starter-web</artifactId>
        </dependency>
        <!-- Official Anthropic Java SDK. Verify the latest version on Maven Central
             (search "com.anthropic anthropic-java"); bump if the build can't resolve it. -->
        <dependency>
            <groupId>com.anthropic</groupId>
            <artifactId>anthropic-java</artifactId>
            <version>2.9.0</version>
        </dependency>
        <dependency>
            <groupId>org.springframework.boot</groupId>
            <artifactId>spring-boot-starter-test</artifactId>
            <scope>test</scope>
        </dependency>
    </dependencies>

    <build>
        <plugins>
            <plugin>
                <groupId>org.springframework.boot</groupId>
                <artifactId>spring-boot-maven-plugin</artifactId>
            </plugin>
        </plugins>
    </build>
</project>
```

- [ ] **Step 2: Write `.gitignore` and `application.properties`**

`agents/fundamentals-java/.gitignore`:
```
target/
```

`agents/fundamentals-java/src/main/resources/application.properties`:
```
server.port=9001
spring.application.name=fundamentals-agent
```

- [ ] **Step 3: Write the application class**

`FundamentalsApplication.java`:
```java
package com.tradingfirm.fundamentals;

import org.springframework.boot.SpringApplication;
import org.springframework.boot.autoconfigure.SpringBootApplication;

@SpringBootApplication
public class FundamentalsApplication {
    public static void main(String[] args) {
        SpringApplication.run(FundamentalsApplication.class, args);
    }
}
```

- [ ] **Step 4: Write the failing context-load test**

`FundamentalsApplicationTests.java`:
```java
package com.tradingfirm.fundamentals;

import org.junit.jupiter.api.Test;
import org.springframework.boot.test.context.SpringBootTest;

@SpringBootTest
class FundamentalsApplicationTests {
    @Test
    void contextLoads() {
    }
}
```

> Note: `@SpringBootTest` will instantiate `AnthropicClientConfig` once it exists (Task 4). Until then the context has no Anthropic bean, which is fine — this test only checks the context starts. After Task 4, the bean reads `ANTHROPIC_API_KEY`; if the SDK's `fromEnv()` throws when the key is absent, Task 4 Step 5 makes the bean lazy so this test stays key-free.

- [ ] **Step 5: Build and run the test**

Run: `mvn -q -f agents/fundamentals-java/pom.xml test`
Expected: BUILD SUCCESS, `contextLoads` passes. (First run downloads dependencies; if `com.anthropic:anthropic-java:2.9.0` fails to resolve, bump to the latest version shown on Maven Central and re-run.)

- [ ] **Step 6: Commit**

```bash
git add agents/fundamentals-java/pom.xml agents/fundamentals-java/.gitignore \
        agents/fundamentals-java/src/main/resources/application.properties \
        agents/fundamentals-java/src/main/java/com/tradingfirm/fundamentals/FundamentalsApplication.java \
        agents/fundamentals-java/src/test/java/com/tradingfirm/fundamentals/FundamentalsApplicationTests.java
git commit -m "feat(java): scaffold Spring Boot fundamentals agent on :9001"
```

---

### Task 2: Agent Card endpoint

**Files:**
- Create: `agents/fundamentals-java/src/main/java/com/tradingfirm/fundamentals/dto/AgentCard.java`
- Create: `agents/fundamentals-java/src/main/java/com/tradingfirm/fundamentals/A2AController.java`
- Test: `agents/fundamentals-java/src/test/java/com/tradingfirm/fundamentals/A2AControllerTest.java`

**Interfaces:**
- Consumes: nothing from prior tasks.
- Produces: `A2AController` (Spring `@RestController`) with `GET /.well-known/agent-card.json` returning the card. `AgentCard` is a static factory `AgentCard.fundamentals()` returning the fixed card. Later tasks add the `POST /` handler to this same controller.

- [ ] **Step 1: Write the failing MockMvc test for the card**

`A2AControllerTest.java`:
```java
package com.tradingfirm.fundamentals;

import org.junit.jupiter.api.Test;
import org.springframework.beans.factory.annotation.Autowired;
import org.springframework.boot.test.autoconfigure.web.servlet.WebMvcTest;
import org.springframework.test.web.servlet.MockMvc;

import static org.springframework.test.web.servlet.request.MockMvcRequestBuilders.get;
import static org.springframework.test.web.servlet.result.MockMvcResultMatchers.*;

@WebMvcTest(A2AController.class)
class A2AControllerTest {

    @Autowired
    MockMvc mvc;

    @Test
    void servesAgentCardAtWellKnownPath() throws Exception {
        mvc.perform(get("/.well-known/agent-card.json"))
           .andExpect(status().isOk())
           .andExpect(jsonPath("$.name").value("Fundamentals Analyst"))
           .andExpect(jsonPath("$.version").value("0.1.0"))
           .andExpect(jsonPath("$.capabilities.streaming").value(false))
           .andExpect(jsonPath("$.defaultInputModes[0]").value("text/plain"))
           .andExpect(jsonPath("$.defaultOutputModes[0]").value("text/plain"))
           .andExpect(jsonPath("$.supportedInterfaces[0].url").value("http://127.0.0.1:9001/"))
           .andExpect(jsonPath("$.supportedInterfaces[0].protocolBinding").value("JSONRPC"))
           .andExpect(jsonPath("$.supportedInterfaces[0].protocolVersion").value("1.0"))
           .andExpect(jsonPath("$.skills[0].id").value("analyze_fundamentals"))
           .andExpect(jsonPath("$.skills[0].name").value("Analyze Fundamentals"))
           .andExpect(jsonPath("$.skills[0].tags[0]").value("finance"));
    }
}
```

> `@WebMvcTest(A2AController.class)` loads only the web layer (no Anthropic bean), so this test is fast and key-free. Once Task 5 injects `FundamentalsService` into the controller, add `@MockBean FundamentalsService service;` to this test class (Task 5 Step 1 covers that) so the slice context can construct the controller.

- [ ] **Step 2: Run the test to verify it fails**

Run: `mvn -q -f agents/fundamentals-java/pom.xml test -Dtest=A2AControllerTest`
Expected: FAIL — `A2AController` / `AgentCard` do not exist (compilation error).

- [ ] **Step 3: Write the `AgentCard` DTO**

`dto/AgentCard.java`:
```java
package com.tradingfirm.fundamentals.dto;

import java.util.List;

/** A2A Agent Card. Field names serialize to the exact camelCase keys the Python client expects. */
public record AgentCard(
        String name,
        String description,
        List<AgentInterface> supportedInterfaces,
        String version,
        Capabilities capabilities,
        List<String> defaultInputModes,
        List<String> defaultOutputModes,
        List<Skill> skills
) {
    public record AgentInterface(String url, String protocolBinding, String protocolVersion) {}
    public record Capabilities(boolean streaming) {}
    public record Skill(String id, String name, String description, List<String> tags) {}

    private static final String DESCRIPTION =
            "Evaluates company financials and valuation. Demo only, not financial advice.";

    public static AgentCard fundamentals() {
        return new AgentCard(
                "Fundamentals Analyst",
                DESCRIPTION,
                List.of(new AgentInterface("http://127.0.0.1:9001/", "JSONRPC", "1.0")),
                "0.1.0",
                new Capabilities(false),
                List.of("text/plain"),
                List.of("text/plain"),
                List.of(new Skill("analyze_fundamentals", "Analyze Fundamentals", DESCRIPTION, List.of("finance")))
        );
    }
}
```

- [ ] **Step 4: Write the controller with the card endpoint**

`A2AController.java`:
```java
package com.tradingfirm.fundamentals;

import com.tradingfirm.fundamentals.dto.AgentCard;
import org.springframework.web.bind.annotation.GetMapping;
import org.springframework.web.bind.annotation.RestController;

@RestController
public class A2AController {

    @GetMapping("/.well-known/agent-card.json")
    public AgentCard agentCard() {
        return AgentCard.fundamentals();
    }
}
```

- [ ] **Step 5: Run the test to verify it passes**

Run: `mvn -q -f agents/fundamentals-java/pom.xml test -Dtest=A2AControllerTest`
Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git add agents/fundamentals-java/src/main/java/com/tradingfirm/fundamentals/dto/AgentCard.java \
        agents/fundamentals-java/src/main/java/com/tradingfirm/fundamentals/A2AController.java \
        agents/fundamentals-java/src/test/java/com/tradingfirm/fundamentals/A2AControllerTest.java
git commit -m "feat(java): serve A2A agent card at /.well-known/agent-card.json"
```

---

### Task 3: Fundamentals fixtures

**Files:**
- Create: `agents/fundamentals-java/src/main/java/com/tradingfirm/fundamentals/FundamentalsData.java`
- Test: `agents/fundamentals-java/src/test/java/com/tradingfirm/fundamentals/FundamentalsDataTest.java`

**Interfaces:**
- Consumes: nothing.
- Produces: `FundamentalsData.load(String ticker)` returning a `Facts` record: `Facts(String ticker, double peRatio, double revenueGrowth, double debtToEquity, double fcfYield)`. Ticker is upper-cased; unknown tickers return the default fixture. `Facts.toPromptMap()` returns a `String` formatted to match the Python `dict` repr used in the prompt (see Task 4 for exact format).

- [ ] **Step 1: Write the failing test**

`FundamentalsDataTest.java`:
```java
package com.tradingfirm.fundamentals;

import org.junit.jupiter.api.Test;

import static org.junit.jupiter.api.Assertions.*;

class FundamentalsDataTest {

    @Test
    void knownTickerReturnsFixture() {
        FundamentalsData.Facts f = FundamentalsData.load("AAPL");
        assertEquals("AAPL", f.ticker());
        assertEquals(31.2, f.peRatio());
        assertEquals(0.08, f.revenueGrowth());
        assertEquals(1.5, f.debtToEquity());
        assertEquals(0.03, f.fcfYield());
    }

    @Test
    void tickerIsUpperCased() {
        assertEquals("TSLA", FundamentalsData.load("tsla").ticker());
        assertEquals(62.0, FundamentalsData.load("tsla").peRatio());
    }

    @Test
    void unknownTickerReturnsDefault() {
        FundamentalsData.Facts f = FundamentalsData.load("ZZZZ");
        assertEquals("ZZZZ", f.ticker());
        assertEquals(20.0, f.peRatio());
        assertEquals(0.05, f.revenueGrowth());
        assertEquals(1.0, f.debtToEquity());
        assertEquals(0.04, f.fcfYield());
    }
}
```

- [ ] **Step 2: Run to verify it fails**

Run: `mvn -q -f agents/fundamentals-java/pom.xml test -Dtest=FundamentalsDataTest`
Expected: FAIL — `FundamentalsData` does not exist.

- [ ] **Step 3: Write `FundamentalsData`**

Mirror of `agents/fundamentals/data.py`:
```java
package com.tradingfirm.fundamentals;

import java.util.Map;

/** Deterministic mock fundamentals. Mirror of agents/fundamentals/data.py. */
public final class FundamentalsData {

    public record Facts(String ticker, double peRatio, double revenueGrowth,
                        double debtToEquity, double fcfYield) {}

    private record Base(double peRatio, double revenueGrowth, double debtToEquity, double fcfYield) {}

    private static final Map<String, Base> FIXTURES = Map.of(
            "AAPL", new Base(31.2, 0.08, 1.5, 0.03),
            "TSLA", new Base(62.0, 0.19, 0.3, 0.02)
    );
    private static final Base DEFAULT = new Base(20.0, 0.05, 1.0, 0.04);

    private FundamentalsData() {}

    public static Facts load(String ticker) {
        String t = ticker.toUpperCase();
        Base b = FIXTURES.getOrDefault(t, DEFAULT);
        return new Facts(t, b.peRatio(), b.revenueGrowth(), b.debtToEquity(), b.fcfYield());
    }
}
```

- [ ] **Step 4: Run to verify it passes**

Run: `mvn -q -f agents/fundamentals-java/pom.xml test -Dtest=FundamentalsDataTest`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add agents/fundamentals-java/src/main/java/com/tradingfirm/fundamentals/FundamentalsData.java \
        agents/fundamentals-java/src/test/java/com/tradingfirm/fundamentals/FundamentalsDataTest.java
git commit -m "feat(java): mock fundamentals fixtures (mirror of data.py)"
```

---

### Task 4: FundamentalsService — prompt building + Claude call

**Files:**
- Create: `agents/fundamentals-java/src/main/java/com/tradingfirm/fundamentals/AnthropicClientConfig.java`
- Create: `agents/fundamentals-java/src/main/java/com/tradingfirm/fundamentals/FundamentalsService.java`
- Test: `agents/fundamentals-java/src/test/java/com/tradingfirm/fundamentals/FundamentalsServiceTest.java`

**Interfaces:**
- Consumes: `FundamentalsData.load(...)` (Task 3).
- Produces: `FundamentalsService.analyze(String ticker) -> String` (the valuation summary). The service exposes `String buildPrompt(FundamentalsData.Facts facts)` and a `static final String SYSTEM` constant so the test can assert prompt construction without calling Claude. Constructor takes the Anthropic client (injected) so the test can pass a mock. Honors `FUNDAMENTALS_LLM_STUB` env var: when set to `1`/`true`, `analyze` returns a deterministic canned string and never calls Claude.

- [ ] **Step 1: Write the failing service test (Claude client mocked)**

`FundamentalsServiceTest.java`:
```java
package com.tradingfirm.fundamentals;

import org.junit.jupiter.api.Test;

import static org.junit.jupiter.api.Assertions.*;

class FundamentalsServiceTest {

    // Pass null client: these tests exercise only pure prompt-building + fixture lookup,
    // which never touch the client.
    private final FundamentalsService service = new FundamentalsService(null);

    @Test
    void systemPromptMatchesPythonAgent() {
        assertEquals(
            "You are a fundamentals analyst. Be concise. This is a technical demo, not financial advice.",
            FundamentalsService.SYSTEM);
    }

    @Test
    void promptIncludesTickerAndFactsAndAsk() {
        FundamentalsData.Facts facts = FundamentalsData.load("AAPL");
        String prompt = service.buildPrompt(facts);
        assertTrue(prompt.contains("AAPL"), prompt);
        assertTrue(prompt.contains("31.2"), prompt);          // pe_ratio present
        assertTrue(prompt.contains("attractive, neutral, or expensive"), prompt);
        assertTrue(prompt.contains("3-4 sentences"), prompt);
    }
}
```

- [ ] **Step 2: Run to verify it fails**

Run: `mvn -q -f agents/fundamentals-java/pom.xml test -Dtest=FundamentalsServiceTest`
Expected: FAIL — `FundamentalsService` does not exist.

- [ ] **Step 3: Write the Anthropic client bean**

`AnthropicClientConfig.java`:
```java
package com.tradingfirm.fundamentals;

import com.anthropic.client.AnthropicClient;
import com.anthropic.client.okhttp.AnthropicOkHttpClient;
import org.springframework.context.annotation.Bean;
import org.springframework.context.annotation.Configuration;
import org.springframework.context.annotation.Lazy;

@Configuration
public class AnthropicClientConfig {

    /**
     * Lazy so the app context (and @SpringBootTest) starts without ANTHROPIC_API_KEY.
     * fromEnv() reads ANTHROPIC_API_KEY. Verify the exact factory/class names against the
     * installed SDK if this does not compile (com.anthropic.client.okhttp.AnthropicOkHttpClient).
     */
    @Bean
    @Lazy
    public AnthropicClient anthropicClient() {
        return AnthropicOkHttpClient.fromEnv();
    }
}
```

- [ ] **Step 4: Write `FundamentalsService`**

Prompt text mirrors `agents/fundamentals/logic.py` exactly. The fixtures string mimics the Python `dict` repr `{'ticker': 'AAPL', 'pe_ratio': 31.2, 'revenue_growth': 0.08, 'debt_to_equity': 1.5, 'fcf_yield': 0.03}` closely enough to carry the same numbers (exact Python repr is not required — the LLM reads it as context).

```java
package com.tradingfirm.fundamentals;

import com.anthropic.client.AnthropicClient;
import com.anthropic.models.messages.MessageCreateParams;
import com.anthropic.models.messages.Message;
import org.springframework.stereotype.Service;

@Service
public class FundamentalsService {

    public static final String SYSTEM =
            "You are a fundamentals analyst. Be concise. This is a technical demo, not financial advice.";

    private final AnthropicClient client;

    public FundamentalsService(AnthropicClient client) {
        this.client = client;
    }

    public String analyze(String ticker) {
        FundamentalsData.Facts facts = FundamentalsData.load(ticker);
        if (stubEnabled()) {
            return "[stub] Fundamentals summary for " + facts.ticker()
                    + ": valuation neutral. Demo only, not financial advice.";
        }
        String prompt = buildPrompt(facts);
        // Minimal request: model + maxTokens + system + user message ONLY.
        // No temperature/top_p/top_k/budget_tokens/thinking (these 400 on current models).
        // Verify builder method names against the installed SDK if this does not compile.
        MessageCreateParams params = MessageCreateParams.builder()
                .model("claude-sonnet-4-6")
                .maxTokens(1024L)
                .system(SYSTEM)
                .addUserMessage(prompt)
                .build();
        Message message = client.messages().create(params);
        return extractText(message);
    }

    String buildPrompt(FundamentalsData.Facts f) {
        String facts = String.format(
                "{'ticker': '%s', 'pe_ratio': %s, 'revenue_growth': %s, 'debt_to_equity': %s, 'fcf_yield': %s}",
                f.ticker(), f.peRatio(), f.revenueGrowth(), f.debtToEquity(), f.fcfYield());
        return "Given these fundamentals for " + f.ticker() + ": " + facts + ". "
                + "Summarize the valuation picture in 3-4 sentences and state whether fundamentals "
                + "look attractive, neutral, or expensive.";
    }

    private static boolean stubEnabled() {
        String v = System.getenv("FUNDAMENTALS_LLM_STUB");
        return "1".equals(v) || "true".equalsIgnoreCase(v);
    }

    /** Concatenate the text of all text blocks in the response. Verify accessors against the SDK. */
    private static String extractText(Message message) {
        StringBuilder sb = new StringBuilder();
        message.content().forEach(block -> block.text().ifPresent(t -> sb.append(t.text())));
        return sb.toString();
    }
}
```

> Anthropic Java SDK note: `MessageCreateParams.builder()`, `.model(String)`, `.maxTokens(long)`, `.system(String)`, `.addUserMessage(String)`, `client.messages().create(params)`, and `message.content()` → blocks with `.text()` returning an `Optional<TextBlock>` whose `.text()` is the string are the documented shapes. If any symbol name differs in the resolved SDK version, fix it from the compiler error (do not guess alternate APIs) — model string and the "minimal params only" rule are fixed; only the Java symbol spellings may need adjustment.

- [ ] **Step 5: Run the service test to verify it passes**

Run: `mvn -q -f agents/fundamentals-java/pom.xml test -Dtest=FundamentalsServiceTest`
Expected: PASS. (Pure prompt/system assertions; no client call.)

- [ ] **Step 6: Run the full module test suite (context still loads)**

Run: `mvn -q -f agents/fundamentals-java/pom.xml test`
Expected: BUILD SUCCESS — `contextLoads`, `A2AControllerTest`, `FundamentalsDataTest`, `FundamentalsServiceTest` all pass (the `@Lazy` Anthropic bean keeps `@SpringBootTest` key-free).

- [ ] **Step 7: Commit**

```bash
git add agents/fundamentals-java/src/main/java/com/tradingfirm/fundamentals/AnthropicClientConfig.java \
        agents/fundamentals-java/src/main/java/com/tradingfirm/fundamentals/FundamentalsService.java \
        agents/fundamentals-java/src/test/java/com/tradingfirm/fundamentals/FundamentalsServiceTest.java
git commit -m "feat(java): fundamentals valuation via Anthropic Java SDK (claude-sonnet-4-6)"
```

---

### Task 5: SendMessage JSON-RPC endpoint

**Files:**
- Create: `agents/fundamentals-java/src/main/java/com/tradingfirm/fundamentals/dto/A2AMessage.java`
- Create: `agents/fundamentals-java/src/main/java/com/tradingfirm/fundamentals/dto/JsonRpcRequest.java`
- Create: `agents/fundamentals-java/src/main/java/com/tradingfirm/fundamentals/dto/JsonRpcResponse.java`
- Modify: `agents/fundamentals-java/src/main/java/com/tradingfirm/fundamentals/A2AController.java`
- Modify: `agents/fundamentals-java/src/test/java/com/tradingfirm/fundamentals/A2AControllerTest.java`

**Interfaces:**
- Consumes: `FundamentalsService.analyze(String)` (Task 4); `AgentCard` (Task 2).
- Produces: `POST /` on `A2AController` handling JSON-RPC `SendMessage`. Reads `params.message.parts[*].text` (concatenated) as the ticker, calls `service.analyze(...)`, returns the response envelope; unknown method returns the JSON-RPC error object. Request id is echoed; `jsonrpc` is always `"2.0"`.

- [ ] **Step 1: Add `@MockBean` service to the existing controller test and write the SendMessage tests**

Edit `A2AControllerTest.java`: add the mock bean (so the web slice can build the controller now that it depends on the service) and two new tests. Full updated file:

```java
package com.tradingfirm.fundamentals;

import org.junit.jupiter.api.Test;
import org.springframework.beans.factory.annotation.Autowired;
import org.springframework.boot.test.autoconfigure.web.servlet.WebMvcTest;
import org.springframework.boot.test.mock.mockito.MockBean;
import org.springframework.http.MediaType;
import org.springframework.test.web.servlet.MockMvc;

import static org.mockito.ArgumentMatchers.eq;
import static org.mockito.Mockito.when;
import static org.springframework.test.web.servlet.request.MockMvcRequestBuilders.get;
import static org.springframework.test.web.servlet.request.MockMvcRequestBuilders.post;
import static org.springframework.test.web.servlet.result.MockMvcResultMatchers.*;

@WebMvcTest(A2AController.class)
class A2AControllerTest {

    @Autowired
    MockMvc mvc;

    @MockBean
    FundamentalsService service;

    @Test
    void servesAgentCardAtWellKnownPath() throws Exception {
        mvc.perform(get("/.well-known/agent-card.json"))
           .andExpect(status().isOk())
           .andExpect(jsonPath("$.name").value("Fundamentals Analyst"))
           .andExpect(jsonPath("$.version").value("0.1.0"))
           .andExpect(jsonPath("$.capabilities.streaming").value(false))
           .andExpect(jsonPath("$.defaultInputModes[0]").value("text/plain"))
           .andExpect(jsonPath("$.defaultOutputModes[0]").value("text/plain"))
           .andExpect(jsonPath("$.supportedInterfaces[0].url").value("http://127.0.0.1:9001/"))
           .andExpect(jsonPath("$.supportedInterfaces[0].protocolBinding").value("JSONRPC"))
           .andExpect(jsonPath("$.supportedInterfaces[0].protocolVersion").value("1.0"))
           .andExpect(jsonPath("$.skills[0].id").value("analyze_fundamentals"))
           .andExpect(jsonPath("$.skills[0].name").value("Analyze Fundamentals"))
           .andExpect(jsonPath("$.skills[0].tags[0]").value("finance"));
    }

    @Test
    void sendMessageReturnsAgentReplyEnvelope() throws Exception {
        when(service.analyze(eq("AAPL"))).thenReturn("Apple looks neutral.");

        String body = """
            {"method":"SendMessage","params":{"message":{"messageId":"m1","role":"ROLE_USER",
            "parts":[{"text":"AAPL"}]},"configuration":{}},"id":"req-1","jsonrpc":"2.0"}""";

        mvc.perform(post("/").contentType(MediaType.APPLICATION_JSON).content(body))
           .andExpect(status().isOk())
           .andExpect(jsonPath("$.jsonrpc").value("2.0"))
           .andExpect(jsonPath("$.id").value("req-1"))
           .andExpect(jsonPath("$.result.message.role").value("ROLE_AGENT"))
           .andExpect(jsonPath("$.result.message.messageId").isNotEmpty())
           .andExpect(jsonPath("$.result.message.parts[0].text").value("Apple looks neutral."))
           .andExpect(jsonPath("$.error").doesNotExist());
    }

    @Test
    void unknownMethodReturnsJsonRpcError() throws Exception {
        String body = """
            {"method":"DeleteEverything","params":{},"id":"req-2","jsonrpc":"2.0"}""";

        mvc.perform(post("/").contentType(MediaType.APPLICATION_JSON).content(body))
           .andExpect(status().isOk())
           .andExpect(jsonPath("$.jsonrpc").value("2.0"))
           .andExpect(jsonPath("$.id").value("req-2"))
           .andExpect(jsonPath("$.error.code").value(-32601))
           .andExpect(jsonPath("$.error.message").value("Method not found"))
           .andExpect(jsonPath("$.result").doesNotExist());
    }
}
```

- [ ] **Step 2: Run to verify it fails**

Run: `mvn -q -f agents/fundamentals-java/pom.xml test -Dtest=A2AControllerTest`
Expected: FAIL — the DTOs and `POST /` handler do not exist (compilation error).

- [ ] **Step 3: Write the message + request DTOs**

`dto/A2AMessage.java`:
```java
package com.tradingfirm.fundamentals.dto;

import com.fasterxml.jackson.annotation.JsonInclude;
import java.util.List;

@JsonInclude(JsonInclude.Include.NON_NULL)
public record A2AMessage(String messageId, String role, List<Part> parts) {
    public record Part(String text) {}
}
```

`dto/JsonRpcRequest.java`:
```java
package com.tradingfirm.fundamentals.dto;

/** Inbound JSON-RPC request. Unknown fields (e.g. metadata) are ignored by Spring's Jackson
 *  (fail-on-unknown-properties is false by default in Spring Boot). */
public record JsonRpcRequest(String method, Params params, String id, String jsonrpc) {
    public record Params(A2AMessage message, Object configuration) {}
}
```

- [ ] **Step 4: Write the response DTO**

`dto/JsonRpcResponse.java`:
```java
package com.tradingfirm.fundamentals.dto;

import com.fasterxml.jackson.annotation.JsonInclude;

@JsonInclude(JsonInclude.Include.NON_NULL)
public record JsonRpcResponse(Result result, Error error, String id, String jsonrpc) {

    public record Result(A2AMessage message) {}
    public record Error(int code, String message) {}

    public static JsonRpcResponse ok(A2AMessage message, String id) {
        return new JsonRpcResponse(new Result(message), null, id, "2.0");
    }

    public static JsonRpcResponse error(int code, String message, String id) {
        return new JsonRpcResponse(null, new Error(code, message), id, "2.0");
    }
}
```

- [ ] **Step 5: Add the `POST /` handler to the controller**

Full updated `A2AController.java`:
```java
package com.tradingfirm.fundamentals;

import com.tradingfirm.fundamentals.dto.A2AMessage;
import com.tradingfirm.fundamentals.dto.AgentCard;
import com.tradingfirm.fundamentals.dto.JsonRpcRequest;
import com.tradingfirm.fundamentals.dto.JsonRpcResponse;
import org.springframework.web.bind.annotation.GetMapping;
import org.springframework.web.bind.annotation.PostMapping;
import org.springframework.web.bind.annotation.RequestBody;
import org.springframework.web.bind.annotation.RestController;

import java.util.List;
import java.util.UUID;

@RestController
public class A2AController {

    private final FundamentalsService service;

    public A2AController(FundamentalsService service) {
        this.service = service;
    }

    @GetMapping("/.well-known/agent-card.json")
    public AgentCard agentCard() {
        return AgentCard.fundamentals();
    }

    @PostMapping("/")
    public JsonRpcResponse rpc(@RequestBody JsonRpcRequest request) {
        if (!"SendMessage".equals(request.method())) {
            return JsonRpcResponse.error(-32601, "Method not found", request.id());
        }
        String text = userText(request);
        String reply = service.analyze(text);
        A2AMessage out = new A2AMessage(
                UUID.randomUUID().toString(),
                "ROLE_AGENT",
                List.of(new A2AMessage.Part(reply)));
        return JsonRpcResponse.ok(out, request.id());
    }

    /** Concatenate the text of all parts in the inbound message. */
    private static String userText(JsonRpcRequest request) {
        StringBuilder sb = new StringBuilder();
        if (request.params() != null && request.params().message() != null
                && request.params().message().parts() != null) {
            for (A2AMessage.Part p : request.params().message().parts()) {
                if (p.text() != null) {
                    sb.append(p.text());
                }
            }
        }
        return sb.toString();
    }
}
```

- [ ] **Step 6: Run the controller tests to verify they pass**

Run: `mvn -q -f agents/fundamentals-java/pom.xml test -Dtest=A2AControllerTest`
Expected: PASS (all three tests).

- [ ] **Step 7: Run the full module suite**

Run: `mvn -q -f agents/fundamentals-java/pom.xml test`
Expected: BUILD SUCCESS, all tests pass.

- [ ] **Step 8: Commit**

```bash
git add agents/fundamentals-java/src/main/java/com/tradingfirm/fundamentals/dto/A2AMessage.java \
        agents/fundamentals-java/src/main/java/com/tradingfirm/fundamentals/dto/JsonRpcRequest.java \
        agents/fundamentals-java/src/main/java/com/tradingfirm/fundamentals/dto/JsonRpcResponse.java \
        agents/fundamentals-java/src/main/java/com/tradingfirm/fundamentals/A2AController.java \
        agents/fundamentals-java/src/test/java/com/tradingfirm/fundamentals/A2AControllerTest.java
git commit -m "feat(java): JSON-RPC SendMessage endpoint matching the captured A2A wire shape"
```

---

### Task 6: Python interop proof (the headline test)

**Files:**
- Create: `tests/test_java_interop.py`

**Interfaces:**
- Consumes: the built Spring Boot jar (`agents/fundamentals-java/target/fundamentals-java-0.1.0.jar`); the existing `orchestrator.a2a_client.call_agent` (unchanged).
- Produces: a pytest that proves the Python A2A client works **unchanged** against the Java agent. Auto-skips when Java/Maven is unavailable. Runs key-free via `FUNDAMENTALS_LLM_STUB=1`.

- [ ] **Step 1: Write the interop test**

`tests/test_java_interop.py`:
```python
"""Proof of interop: the Python a2a-sdk client talks to the Java agent unchanged.

Skipped unless Java + Maven are present. Runs key-free via FUNDAMENTALS_LLM_STUB=1,
so it does not call Claude and needs no ANTHROPIC_API_KEY.
"""
import asyncio
import os
import shutil
import socket
import subprocess
import time
from pathlib import Path

import httpx
import pytest

from orchestrator.a2a_client import call_agent

ROOT = Path(__file__).resolve().parent.parent
JAVA_DIR = ROOT / "agents" / "fundamentals-java"
JAR = JAVA_DIR / "target" / "fundamentals-java-0.1.0.jar"
PORT = 9001
BASE_URL = f"http://127.0.0.1:{PORT}"

pytestmark = pytest.mark.skipif(
    shutil.which("java") is None or shutil.which("mvn") is None,
    reason="Java/Maven not installed; skipping cross-language interop test",
)


def _build_jar() -> None:
    subprocess.run(
        ["mvn", "-q", "-f", str(JAVA_DIR / "pom.xml"), "package", "-DskipTests"],
        check=True,
    )


def _wait_for_port(port: int, timeout: float = 40.0) -> None:
    deadline = time.time() + timeout
    while time.time() < deadline:
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
            s.settimeout(0.5)
            if s.connect_ex(("127.0.0.1", port)) == 0:
                return
        time.sleep(0.25)
    raise TimeoutError(f"Java agent did not start on port {port}")


@pytest.fixture(scope="module")
def java_agent():
    if not JAR.exists():
        _build_jar()
    env = {**os.environ, "FUNDAMENTALS_LLM_STUB": "1"}
    proc = subprocess.Popen(["java", "-jar", str(JAR)], env=env)
    try:
        _wait_for_port(PORT)
        yield BASE_URL
    finally:
        proc.terminate()
        try:
            proc.wait(timeout=10)
        except subprocess.TimeoutExpired:
            proc.kill()


def test_agent_card_resolves(java_agent):
    card = httpx.get(f"{java_agent}/.well-known/agent-card.json", timeout=10).json()
    assert card["name"] == "Fundamentals Analyst"
    assert card["supportedInterfaces"][0]["url"] == f"{BASE_URL}/"


def test_python_client_round_trips_against_java(java_agent):
    reply = asyncio.run(call_agent(java_agent, "AAPL"))
    assert reply, "expected a non-empty reply from the Java agent"
    assert "AAPL" in reply  # the stub echoes the ticker
```

- [ ] **Step 2: Confirm the default suite still skips it and stays green**

Run: `python -m pytest -q` (from the repo root, venv active, no API key needed)
Expected: 18 passed, and `tests/test_java_interop.py` shows as **skipped** if the jar isn't built yet — OR, if Java/Maven are present and it builds, the 2 interop tests pass (so `20 passed` or `18 passed, 2 skipped`). The pre-existing 18 must all still pass either way.

> If the interop tests run, the first invocation builds the jar (can take ~30s on a cold Maven cache). That's expected. If you want to keep the default suite fast, run `python -m pytest -q --ignore=tests/test_java_interop.py` for quick cycles and the full suite before committing.

- [ ] **Step 3: Run the interop test explicitly to confirm the cross-language path works**

Run: `python -m pytest -q tests/test_java_interop.py`
Expected: 2 passed (jar built, Java agent launched with the stub, Python `call_agent` round-trips). No `ANTHROPIC_API_KEY` required.

- [ ] **Step 4: Commit**

```bash
git add tests/test_java_interop.py
git commit -m "test: prove the Python orchestrator client works unchanged against the Java agent"
```

---

### Task 7: Launch script + README

**Files:**
- Create: `scripts/run_all_java.sh`
- Modify: `README.md`

**Interfaces:**
- Consumes: the built jar; the existing `agents.sentiment.server` / `agents.debate.server` Python modules and `orchestrator.main`.
- Produces: `scripts/run_all_java.sh <TICKER>` — the full end-to-end swap run (Java on 9001 + Python on 9002/9003 + orchestrator). The original `scripts/run_all.sh` is untouched.

- [ ] **Step 1: Write the launch script**

`scripts/run_all_java.sh`:
```bash
#!/usr/bin/env bash
# Full end-to-end run with the JAVA fundamentals agent on :9001.
# The Python sentiment (:9002) and debate (:9003) agents are unchanged.
# Needs ANTHROPIC_API_KEY exported (set -a; source .env; set +a) and a built jar.
set -euo pipefail
cd "$(dirname "$0")/.."

JAR="agents/fundamentals-java/target/fundamentals-java-0.1.0.jar"
if [ ! -f "$JAR" ]; then
  echo "Building the Java fundamentals agent..."
  mvn -q -f agents/fundamentals-java/pom.xml package -DskipTests
fi

. .venv/bin/activate

java -jar "$JAR" & F=$!
python -m agents.sentiment.server & S=$!
python -m agents.debate.server & D=$!
trap 'kill $F $S $D 2>/dev/null || true' EXIT
sleep 5
python -m orchestrator.main "${1:-AAPL}"
```

- [ ] **Step 2: Make it executable**

Run: `chmod +x scripts/run_all_java.sh`
Expected: no output; the file is now executable (matches `scripts/run_all.sh`).

- [ ] **Step 3: Update the README**

Add a short section to `README.md` documenting the swap. Find the existing "How to run" content and add, after it, a subsection (adjust the surrounding wording to match the README's existing voice):

```markdown
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
```

- [ ] **Step 4: Verify the end-to-end swap run (live, needs API key)**

Run:
```bash
set -a; source .env; set +a
./scripts/run_all_java.sh AAPL
```
Expected: builds the jar if needed, starts all three agents, prints a `=== MEMO ===` block and a `=== RECOMMENDATION: BUY|HOLD|SELL ===` line — produced via the **Java** fundamentals agent, with no edits to `orchestrator/` or `common/`. (This is the headline demo; it makes real Claude calls.)

- [ ] **Step 5: Commit**

```bash
git add scripts/run_all_java.sh README.md
git commit -m "feat: run-all script and README for the Java fundamentals agent swap"
```

---

### Task 8: Update spec status and handoff

**Files:**
- Modify: `docs/superpowers/specs/2026-06-19-trading-agents-a2a-design.md`
- Modify: `HANDOFF.md` (gitignored — commit will only pick up the spec)

**Interfaces:**
- Consumes: nothing.
- Produces: docs reflecting M3 (Scope A) complete.

- [ ] **Step 1: Update the design spec's M3 status**

In `docs/superpowers/specs/2026-06-19-trading-agents-a2a-design.md` §12, update the M3 line to note the functional-interop portion is done and tracing remains deferred. Change:
```
- **M3:** Swap Fundamentals for the Spring Boot agent, orchestrator untouched, **and the Java agent appears in the same Langfuse trace.** The interop money-shot.
```
to:
```
- **M3 (Scope A — done):** Fundamentals swapped for a Spring Boot A2A agent at the identical contract; orchestrator untouched. The interop money-shot. Same-Langfuse-trace for the Java agent is deferred to the tracing milestone (server-side trace extraction + Langfuse, done once across both languages).
```

- [ ] **Step 2: Update `HANDOFF.md`**

In `HANDOFF.md`, move M3 out of "Deferred / next steps" into the "Current state" summary (mark it Scope-A complete), and note `scripts/run_all_java.sh` + `agents/fundamentals-java/` + `tests/test_java_interop.py`. Leave items 2–6 (tracing, error handling, structlog, Langfuse, M4) as the remaining deferred list. (HANDOFF.md is gitignored, so this edit is local-only and won't be committed.)

- [ ] **Step 3: Commit the spec update**

```bash
git add docs/superpowers/specs/2026-06-19-trading-agents-a2a-design.md
git commit -m "docs: mark M3 (Scope A) interop complete; tracing deferred"
```

---

## Final verification (whole branch)

- [ ] `mvn -q -f agents/fundamentals-java/pom.xml test` → BUILD SUCCESS, all JUnit tests pass.
- [ ] `python -m pytest -q` → the original 18 still pass (interop tests pass or skip depending on Java/jar availability); no API key needed.
- [ ] `python -m pytest -q tests/test_java_interop.py` → 2 passed (key-free, via the stub).
- [ ] Live: `set -a; source .env; set +a; ./scripts/run_all_java.sh AAPL` → memo + recommendation produced through the Java agent, zero changes to `orchestrator/` or `common/` (confirm with `git status` that only `agents/fundamentals-java/`, `scripts/`, `tests/`, `README.md`, and the spec changed).
- [ ] `git log --oneline` shows no `Co-Authored-By` / AI-attribution trailers.

## Self-Review (performed during planning)

- **Spec coverage:** §2 wire contract → Tasks 2 & 5 (card + SendMessage, with the exact captured shapes and the unknown-method error). §3 hand-rolled rationale → Task 5 DTOs/controller. §4 layout → Tasks 1–5. §5 LLM parity → Task 4 (model `claude-sonnet-4-6`, mirrored prompt/system/fixtures; minimal params). §6 build & run → Tasks 1 & 7. §7 testing → JUnit (Tasks 1–5) + skippable Python interop (Task 6). §8 out-of-scope tracing → not implemented; metadata tolerated via Jackson defaults (Task 5 DTO note). §9 docs/public-repo rule → Task 7 & 8 + Global Constraints. §10 risks (wire drift, SDK specifics, port) → covered by MockMvc + interop tests, the compile-fix note, and the single-9001-owner launch script.
- **Placeholder scan:** the only deferred value is the Anthropic Java SDK version (`2.9.0`) and the exact SDK symbol names, both explicitly resolved via the documented build/compile-fix loop — not silent TODOs.
- **Type consistency:** `FundamentalsData.Facts` (Task 3) is consumed by `FundamentalsService.buildPrompt` (Task 4); `FundamentalsService.analyze(String)` (Task 4) is consumed by `A2AController.rpc` (Task 5); `AgentCard.fundamentals()` (Task 2) used in Task 5's controller; DTO names (`JsonRpcRequest`/`JsonRpcResponse`/`A2AMessage`) consistent between Task 5 code and tests; `FUNDAMENTALS_LLM_STUB` flag defined in Task 4 and used in Task 6.
