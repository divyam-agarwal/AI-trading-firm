package com.tradingfirm.fundamentals.dto;

/** Inbound JSON-RPC request. Unknown fields (e.g. metadata) are ignored by Spring's Jackson
 *  (fail-on-unknown-properties is false by default in Spring Boot). */
public record JsonRpcRequest(String method, Params params, String id, String jsonrpc) {
    public record Params(A2AMessage message, Object configuration) {}
}
