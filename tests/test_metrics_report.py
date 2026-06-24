import json

from common import metrics_report as mr
from common.metrics_queries import QUERIES


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
