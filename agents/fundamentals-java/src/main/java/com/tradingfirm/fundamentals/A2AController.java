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
