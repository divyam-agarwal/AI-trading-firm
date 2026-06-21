package com.tradingfirm.fundamentals;

import org.junit.jupiter.api.Test;

import static org.junit.jupiter.api.Assertions.*;

class FundamentalsDataTest {

    @Test
    void knownTickerReturnsFixture() {
        FundamentalsData.Facts f = FundamentalsData.load("AAPL");
        assertEquals("AAPL", f.ticker());
        assertEquals(31.2, f.peRatio());
        assertEquals(0.08, f.revenueGrowth());
        assertEquals(1.5, f.debtToEquity());
        assertEquals(0.03, f.fcfYield());
    }

    @Test
    void tickerIsUpperCased() {
        assertEquals("TSLA", FundamentalsData.load("tsla").ticker());
        assertEquals(62.0, FundamentalsData.load("tsla").peRatio());
    }

    @Test
    void unknownTickerReturnsDefault() {
        FundamentalsData.Facts f = FundamentalsData.load("ZZZZ");
        assertEquals("ZZZZ", f.ticker());
        assertEquals(20.0, f.peRatio());
        assertEquals(0.05, f.revenueGrowth());
        assertEquals(1.0, f.debtToEquity());
        assertEquals(0.04, f.fcfYield());
    }
}
