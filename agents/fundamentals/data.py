"""Deterministic mock fundamentals. Swappable for yfinance later."""
_FIXTURES = {
    "AAPL": {"pe_ratio": 31.2, "revenue_growth": 0.08, "debt_to_equity": 1.5, "fcf_yield": 0.03},
    "TSLA": {"pe_ratio": 62.0, "revenue_growth": 0.19, "debt_to_equity": 0.3, "fcf_yield": 0.02},
}
_DEFAULT = {"pe_ratio": 20.0, "revenue_growth": 0.05, "debt_to_equity": 1.0, "fcf_yield": 0.04}


def load(ticker: str) -> dict:
    base = _FIXTURES.get(ticker.upper(), _DEFAULT)
    return {"ticker": ticker.upper(), **base}
