package com.tradingfirm.fundamentals.dto;

import java.util.Map;

/** Inbound JSON-RPC request. Unknown fields are ignored by Spring's Jackson
 *  (fail-on-unknown-properties is false by default in Spring Boot).
 *  The orchestrator injects the W3C traceparent at params.metadata. */
public record JsonRpcRequest(String method, Params params, String id, String jsonrpc) {
    public record Params(A2AMessage message, Object configuration, Map<String, String> metadata) {}
}
