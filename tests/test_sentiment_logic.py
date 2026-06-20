from unittest.mock import patch

from agents.sentiment import logic


def test_analyze_returns_llm_text_and_mentions_ticker():
    with patch("agents.sentiment.logic.complete", return_value="sentiment: positive") as m:
        out = logic.analyze("TSLA")
    assert out == "sentiment: positive"
    assert "TSLA" in m.call_args.args[0]
