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
