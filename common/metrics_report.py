"""Query the Langfuse Metrics API and print design §10.3's metrics as tables.

Langfuse computes every aggregate server-side; this module only builds queries,
fetches results, and formats them. Opt-in: prints guidance and exits 0 when the
Langfuse keys are unset.
"""
import json
import os
from dataclasses import dataclass

import httpx

from common.metrics_queries import QUERIES


def metrics_url(host: str) -> str:
    return host.rstrip("/") + "/api/public/v2/metrics"


def build_query_param(body: dict, *, frm: str, to: str) -> str:
    return json.dumps({**body, "fromTimestamp": frm, "toTimestamp": to})


def format_table(title: str, columns: list[tuple[str, str]], rows: list[dict]) -> str:
    headers = [h for _, h in columns]
    fields = [f for f, _ in columns]
    cells = [[("" if r.get(f) is None else str(r.get(f))) for f in fields] for r in rows]
    widths = [len(h) for h in headers]
    for row in cells:
        for i, val in enumerate(row):
            widths[i] = max(widths[i], len(val))
    line = "  ".join(h.ljust(widths[i]) for i, h in enumerate(headers))
    out = [title, line, "  ".join("-" * w for w in widths)]
    if not rows:
        out.append("(no data in window — widen --hours or run an analysis first)")
    else:
        for row in cells:
            out.append("  ".join(val.ljust(widths[i]) for i, val in enumerate(row)))
    return "\n".join(out)
