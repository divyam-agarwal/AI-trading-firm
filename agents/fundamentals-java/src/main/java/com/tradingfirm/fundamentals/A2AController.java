package com.tradingfirm.fundamentals;

import com.tradingfirm.fundamentals.dto.A2AMessage;
import com.tradingfirm.fundamentals.dto.AgentCard;
import com.tradingfirm.fundamentals.dto.JsonRpcRequest;
import com.tradingfirm.fundamentals.dto.JsonRpcResponse;
import io.opentelemetry.api.trace.Span;
import io.opentelemetry.api.trace.StatusCode;
import io.opentelemetry.context.Scope;
import org.springframework.web.bind.annotation.GetMapping;
import org.springframework.web.bind.annotation.PostMapping;
import org.springframework.web.bind.annotation.RequestBody;
import org.springframework.web.bind.annotation.RestController;

import java.util.List;
import java.util.Map;
import java.util.UUID;

@RestController
public class A2AController {

    private static final String AGENT_NAME = AgentCard.fundamentals().name();

    private final FundamentalsService service;
    private final Telemetry telemetry;

    public A2AController(FundamentalsService service, Telemetry telemetry) {
        this.service = service;
        this.telemetry = telemetry;
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
        Map<String, String> metadata =
                request.params() != null ? request.params().metadata() : null;

        // Continue the orchestrator's trace; the handler runs inside the server span
        // so the LLM span nests under it. Tracing is best-effort.
        Span span = telemetry.serverSpan(AGENT_NAME, metadata);
        span.setAttribute("agent.name", AGENT_NAME);
        String reply;
        try (Scope scope = span.makeCurrent()) {
            reply = service.analyze(text);
        } catch (RuntimeException e) {
            span.recordException(e);
            span.setStatus(StatusCode.ERROR);
            throw e;
        } finally {
            span.end();
        }

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
