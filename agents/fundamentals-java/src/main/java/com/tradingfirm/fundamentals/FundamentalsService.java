package com.tradingfirm.fundamentals;

import com.anthropic.client.AnthropicClient;
import com.anthropic.models.messages.Message;
import com.anthropic.models.messages.MessageCreateParams;
import io.opentelemetry.api.trace.Span;
import io.opentelemetry.api.trace.StatusCode;
import io.opentelemetry.api.trace.Tracer;
import io.opentelemetry.context.Scope;
import org.springframework.context.annotation.Lazy;
import org.springframework.stereotype.Service;

@Service
public class FundamentalsService {

    public static final String SYSTEM =
            "You are a fundamentals analyst. Be concise. This is a technical demo, not financial advice.";

    static final String MODEL = "claude-sonnet-4-6";

    private final AnthropicClient client;
    private final Tracer tracer;

    public FundamentalsService(@Lazy AnthropicClient client, Tracer tracer) {
        this.client = client;
        this.tracer = tracer;
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
        MessageCreateParams params = MessageCreateParams.builder()
                .model(MODEL)
                .maxTokens(1024L)
                .system(SYSTEM)
                .addUserMessage(prompt)
                .build();
        Span span = tracer.spanBuilder("chat " + MODEL).startSpan();
        span.setAttribute("gen_ai.request.model", MODEL);
        try (Scope scope = span.makeCurrent()) {
            Message message = client.messages().create(params);
            return extractText(message);
        } catch (RuntimeException e) {
            span.recordException(e);
            span.setStatus(StatusCode.ERROR);
            throw e;
        } finally {
            span.end();
        }
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

    /**
     * Concatenate the text of all text blocks in the response.
     * ContentBlock.text() returns Optional<TextBlock>; TextBlock.text() returns String directly.
     */
    private static String extractText(Message message) {
        StringBuilder sb = new StringBuilder();
        message.content().forEach(block ->
                block.text().ifPresent(t -> sb.append(t.text())));
        return sb.toString();
    }
}
