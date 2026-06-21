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
