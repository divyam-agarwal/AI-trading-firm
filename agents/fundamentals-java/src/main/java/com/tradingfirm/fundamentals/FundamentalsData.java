package com.tradingfirm.fundamentals;

import java.util.Map;

/** Deterministic mock fundamentals. Mirror of agents/fundamentals/data.py. */
public final class FundamentalsData {

    public record Facts(String ticker, double peRatio, double revenueGrowth,
                        double debtToEquity, double fcfYield) {}

    private record Base(double peRatio, double revenueGrowth, double debtToEquity, double fcfYield) {}

    private static final Map<String, Base> FIXTURES = Map.of(
            "AAPL", new Base(31.2, 0.08, 1.5, 0.03),
            "TSLA", new Base(62.0, 0.19, 0.3, 0.02)
    );
    private static final Base DEFAULT = new Base(20.0, 0.05, 1.0, 0.04);

    private FundamentalsData() {}

    public static Facts load(String ticker) {
        String t = ticker.toUpperCase();
        Base b = FIXTURES.getOrDefault(t, DEFAULT);
        return new Facts(t, b.peRatio(), b.revenueGrowth(), b.debtToEquity(), b.fcfYield());
    }
}
