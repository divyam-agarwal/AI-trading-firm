package com.tradingfirm.fundamentals;

import org.junit.jupiter.api.Test;

import java.util.Map;

import static org.junit.jupiter.api.Assertions.*;

class TracingConfigTest {

    @Test
    void parsesCommaSeparatedHeadersSplittingOnFirstEquals() {
        // base64 basic-auth values contain '=' padding; must split on the first '=' only.
        Map<String, String> headers =
                TracingConfig.parseHeaders("Authorization=Basic cGs6c2s=,X-Scope=demo");
        assertEquals("Basic cGs6c2s=", headers.get("Authorization"));
        assertEquals("demo", headers.get("X-Scope"));
        assertEquals(2, headers.size());
    }

    @Test
    void blankOrNullYieldsNoHeaders() {
        assertTrue(TracingConfig.parseHeaders(null).isEmpty());
        assertTrue(TracingConfig.parseHeaders("").isEmpty());
        assertTrue(TracingConfig.parseHeaders("   ").isEmpty());
    }
}
