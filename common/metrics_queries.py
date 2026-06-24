"""Metric query specs for the Langfuse Metrics API (GET /api/public/v2/metrics).

Pure data — no imports, no I/O. Each query targets the ``observations`` view and
omits the time window (the caller injects ``fromTimestamp``/``toTimestamp``), so the
same body serves both the CLI report and the committed dashboard widgets.

Response aggregate fields follow Langfuse's ``{aggregation}_{measure}`` naming, e.g.
``count_count``, ``p95_latency``, ``sum_totalTokens``.
"""

QUERIES = [
    {
        "key": "requests_by_agent",
        "title": "Requests by span name",
        "query": {
            "view": "observations",
            "metrics": [{"measure": "count", "aggregation": "count"}],
            "dimensions": [{"field": "name"}],
            "filters": [],
        },
        "columns": [("name", "Span"), ("count_count", "Requests")],
    },
    {
        "key": "success_failure",
        "title": "Success / failure by level",
        "query": {
            "view": "observations",
            "metrics": [{"measure": "count", "aggregation": "count"}],
            "dimensions": [{"field": "level"}],
            "filters": [],
        },
        "columns": [("level", "Level"), ("count_count", "Count")],
    },
    {
        "key": "latency_by_span",
        "title": "Latency by span (p95 / avg)",
        "query": {
            "view": "observations",
            "metrics": [
                {"measure": "latency", "aggregation": "p95"},
                {"measure": "latency", "aggregation": "avg"},
            ],
            "dimensions": [{"field": "name"}],
            "filters": [],
        },
        "columns": [("name", "Span"), ("p95_latency", "p95"), ("avg_latency", "avg")],
    },
    {
        "key": "tokens_by_model",
        "title": "LLM tokens & cost by model",
        "query": {
            "view": "observations",
            "metrics": [
                {"measure": "totalTokens", "aggregation": "sum"},
                {"measure": "totalCost", "aggregation": "sum"},
            ],
            "dimensions": [{"field": "providedModelName"}],
            "filters": [],
        },
        "columns": [
            ("providedModelName", "Model"),
            ("sum_totalTokens", "Tokens"),
            ("sum_totalCost", "Cost"),
        ],
    },
]
