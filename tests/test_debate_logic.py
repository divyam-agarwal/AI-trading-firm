from unittest.mock import patch

from agents.debate import logic


def test_parse_recommendation_finds_each_label():
    assert logic.parse_recommendation("blah\nRECOMMENDATION: BUY") == "BUY"
    assert logic.parse_recommendation("RECOMMENDATION: sell now") == "SELL"
    assert logic.parse_recommendation("we suggest HOLD") == "HOLD"


def test_parse_recommendation_defaults_to_hold():
    assert logic.parse_recommendation("no clear call here") == "HOLD"


def test_synthesize_uses_debate_model_and_appends_disclaimer():
    with patch("agents.debate.logic.complete", return_value="memo\nRECOMMENDATION: BUY") as m:
        out = logic.synthesize("fundamentals text", "sentiment text")
    assert "RECOMMENDATION: BUY" in out
    assert "not financial advice" in out.lower()
    assert m.call_args.kwargs["model"] == "claude-opus-4-8"
    prompt = m.call_args.args[0]
    assert "fundamentals text" in prompt and "sentiment text" in prompt
