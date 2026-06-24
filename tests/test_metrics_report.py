import json
from pathlib import Path
from unittest.mock import MagicMock

from common import metrics_report as mr
from common.metrics_queries import QUERIES

DASHBOARD = Path(__file__).resolve().parent.parent / "docker" / "langfuse" / "dashboard.json"


def test_metrics_url_normalizes_trailing_slash():
    assert mr.metrics_url("http://localhost:3000/") == "http://localhost:3000/api/public/v2/metrics"
    assert mr.metrics_url("http://localhost:3000") == "http://localhost:3000/api/public/v2/metrics"


def test_build_query_param_injects_window_without_mutating():
    body = {"view": "observations", "metrics": [], "dimensions": [], "filters": []}
    out = mr.build_query_param(body, frm="2026-06-24T00:00:00Z", to="2026-06-24T12:00:00Z")
    parsed = json.loads(out)
    assert parsed["fromTimestamp"] == "2026-06-24T00:00:00Z"
    assert parsed["toTimestamp"] == "2026-06-24T12:00:00Z"
    assert parsed["view"] == "observations"
    assert "fromTimestamp" not in body  # original untouched


def test_format_table_renders_rows():
    cols = [("name", "Span"), ("count_count", "Requests")]
    rows = [{"name": "Fundamentals Analyst", "count_count": "1"}, {"name": "a2a SendMessage", "count_count": "3"}]
    out = mr.format_table("Requests by span name", cols, rows)
    assert "Requests by span name" in out
    assert "Span" in out and "Requests" in out
    assert "Fundamentals Analyst" in out and "a2a SendMessage" in out
    assert "3" in out


def test_format_table_handles_empty_rows():
    out = mr.format_table("Latency", [("name", "Span")], [])
    assert "Latency" in out
    assert "no data" in out.lower()


def test_queries_are_well_formed():
    assert len(QUERIES) == 4
    keys = {q["key"] for q in QUERIES}
    assert keys == {"requests_by_agent", "success_failure", "latency_by_span", "tokens_by_model"}
    for q in QUERIES:
        assert isinstance(q["title"], str) and q["title"]
        body = q["query"]
        assert body["view"] == "observations"
        assert body["metrics"] and all("measure" in m and "aggregation" in m for m in body["metrics"])
        assert isinstance(body["dimensions"], list)
        assert body["filters"] == []
        # timestamps are injected by the caller, never baked in
        assert "fromTimestamp" not in body and "toTimestamp" not in body
        assert q["columns"] and all(len(c) == 2 for c in q["columns"])


def test_load_config_missing_keys_returns_none(monkeypatch):
    monkeypatch.delenv("LANGFUSE_PUBLIC_KEY", raising=False)
    monkeypatch.delenv("LANGFUSE_SECRET_KEY", raising=False)
    assert mr.load_config() is None


def test_load_config_present(monkeypatch):
    monkeypatch.setenv("LANGFUSE_HOST", "http://lf:3000")
    monkeypatch.setenv("LANGFUSE_PUBLIC_KEY", "pk")
    monkeypatch.setenv("LANGFUSE_SECRET_KEY", "sk")
    cfg = mr.load_config()
    assert cfg == mr.Config(host="http://lf:3000", public_key="pk", secret_key="sk")


def test_fetch_builds_request_and_returns_data():
    cfg = mr.Config(host="http://lf:3000", public_key="pk", secret_key="sk")
    resp = MagicMock()
    resp.json.return_value = {"data": [{"name": "Fundamentals Analyst", "count_count": "1"}]}
    resp.raise_for_status.return_value = None
    client = MagicMock()
    client.get.return_value = resp

    body = {"view": "observations", "metrics": [], "dimensions": [], "filters": []}
    data = mr.fetch(cfg, body, frm="2026-06-24T00:00:00Z", to="2026-06-24T12:00:00Z", client=client)

    assert data == [{"name": "Fundamentals Analyst", "count_count": "1"}]
    args, kwargs = client.get.call_args
    assert args[0] == "http://lf:3000/api/public/v2/metrics"
    assert kwargs["auth"] == ("pk", "sk")
    assert json.loads(kwargs["params"]["query"])["fromTimestamp"] == "2026-06-24T00:00:00Z"


def test_run_prints_all_tables(capsys):
    cfg = mr.Config(host="http://lf:3000", public_key="pk", secret_key="sk")
    resp = MagicMock()
    resp.json.return_value = {"data": [{"name": "Fundamentals Analyst", "count_count": "1",
                                        "level": "DEFAULT", "providedModelName": "claude-sonnet-4-6",
                                        "p95_latency": "2.0", "avg_latency": "2.0",
                                        "sum_totalTokens": "1240", "sum_totalCost": "0.01"}]}
    resp.raise_for_status.return_value = None
    client = MagicMock()
    client.get.return_value = resp

    code = mr.run(cfg, frm="2026-06-24T00:00:00Z", to="2026-06-24T12:00:00Z", client=client)

    out = capsys.readouterr().out
    assert code == 0
    assert "Requests by span name" in out
    assert "Success / failure by level" in out
    assert "Latency by span" in out
    assert "LLM tokens & cost by model" in out
    assert client.get.call_count == len(QUERIES)  # QUERIES imported at top in Task 1


def test_run_continues_on_query_error(capsys):
    cfg = mr.Config(host="http://lf:3000", public_key="pk", secret_key="sk")
    client = MagicMock()
    client.get.side_effect = RuntimeError("boom")
    code = mr.run(cfg, frm="a", to="b", client=client)
    out = capsys.readouterr().out
    assert code == 1
    assert "!!" in out  # error marker printed, no traceback


def test_main_graceful_absence(monkeypatch, capsys):
    monkeypatch.delenv("LANGFUSE_PUBLIC_KEY", raising=False)
    monkeypatch.delenv("LANGFUSE_SECRET_KEY", raising=False)
    code = mr.main(["--hours", "1"])
    out = capsys.readouterr().out
    assert code == 0
    assert "LANGFUSE_PUBLIC_KEY" in out or "keys" in out.lower()


def test_main_runs_with_config(monkeypatch, capsys):
    monkeypatch.setenv("LANGFUSE_PUBLIC_KEY", "pk")
    monkeypatch.setenv("LANGFUSE_SECRET_KEY", "sk")
    called = {}

    def fake_run(config, *, frm, to, client):
        called["frm"] = frm
        called["to"] = to
        print("ran")
        return 0

    monkeypatch.setattr(mr, "run", fake_run)
    code = mr.main(["--from", "2026-06-01T00:00:00Z", "--to", "2026-06-02T00:00:00Z"])
    assert code == 0
    assert called["frm"] == "2026-06-01T00:00:00Z"
    assert called["to"] == "2026-06-02T00:00:00Z"
    assert "ran" in capsys.readouterr().out


def test_dashboard_widgets_match_queries():
    spec = json.loads(DASHBOARD.read_text())
    widgets = {w["key"]: w for w in spec["widgets"]}
    assert set(widgets) == {q["key"] for q in QUERIES}
    for q in QUERIES:
        w = widgets[q["key"]]
        for field in ("view", "metrics", "dimensions", "filters"):
            assert w[field] == q["query"][field], f"{q['key']}.{field} drifted from QUERIES"
        assert w["chartType"]
