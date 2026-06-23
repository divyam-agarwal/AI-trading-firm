package com.tradingfirm.fundamentals;

import io.opentelemetry.api.OpenTelemetry;
import org.junit.jupiter.api.Test;

import static org.junit.jupiter.api.Assertions.*;

class FundamentalsServiceTest {

    // Pass null client: these tests exercise only pure prompt-building + fixture lookup,
    // which never touch the client.
    private final FundamentalsService service =
            new FundamentalsService(null, OpenTelemetry.noop().getTracer("test"));

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
