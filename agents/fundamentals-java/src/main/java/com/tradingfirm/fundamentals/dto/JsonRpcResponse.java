package com.tradingfirm.fundamentals.dto;

import com.fasterxml.jackson.annotation.JsonInclude;

@JsonInclude(JsonInclude.Include.NON_NULL)
public record JsonRpcResponse(Result result, Error error, String id, String jsonrpc) {

    public record Result(A2AMessage message) {}
    public record Error(int code, String message) {}

    public static JsonRpcResponse ok(A2AMessage message, String id) {
        return new JsonRpcResponse(new Result(message), null, id, "2.0");
    }

    public static JsonRpcResponse error(int code, String message, String id) {
        return new JsonRpcResponse(null, new Error(code, message), id, "2.0");
    }
}
