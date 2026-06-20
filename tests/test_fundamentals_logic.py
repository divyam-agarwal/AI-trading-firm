from unittest.mock import patch

from agents.fundamentals import data, logic


def test_load_returns_known_ticker_dict():
    d = data.load("AAPL")
    assert d["ticker"] == "AAPL"
    assert "pe_ratio" in d


def test_load_unknown_ticker_has_defaults():
    d = data.load("ZZZZ")
    assert d["ticker"] == "ZZZZ"
    assert "pe_ratio" in d  # synthesized default, never KeyError


def test_analyze_passes_ticker_data_to_llm_and_returns_text():
    with patch("agents.fundamentals.logic.complete", return_value="valuation summary") as m:
        out = logic.analyze("AAPL")
    assert out == "valuation summary"
    prompt = m.call_args.args[0]
    assert "AAPL" in prompt
