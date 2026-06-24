from common.metrics_queries import QUERIES


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
