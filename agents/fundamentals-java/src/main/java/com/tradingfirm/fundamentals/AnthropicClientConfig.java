package com.tradingfirm.fundamentals;

import com.anthropic.client.AnthropicClient;
import com.anthropic.client.okhttp.AnthropicOkHttpClient;
import org.springframework.context.annotation.Bean;
import org.springframework.context.annotation.Configuration;
import org.springframework.context.annotation.Lazy;

@Configuration
public class AnthropicClientConfig {

    /**
     * Lazy so the app context (and @SpringBootTest) starts without ANTHROPIC_API_KEY.
     * fromEnv() reads ANTHROPIC_API_KEY.
     */
    @Bean
    @Lazy
    public AnthropicClient anthropicClient() {
        return AnthropicOkHttpClient.fromEnv();
    }
}
