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
