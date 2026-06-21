package com.tradingfirm.fundamentals.dto;

import com.fasterxml.jackson.annotation.JsonInclude;
import java.util.List;

@JsonInclude(JsonInclude.Include.NON_NULL)
public record A2AMessage(String messageId, String role, List<Part> parts) {
    public record Part(String text) {}
}
