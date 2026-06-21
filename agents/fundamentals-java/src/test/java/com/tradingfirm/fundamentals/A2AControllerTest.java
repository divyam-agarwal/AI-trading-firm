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
