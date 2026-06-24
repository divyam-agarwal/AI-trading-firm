#!/usr/bin/env python
"""CLI: print Langfuse-derived metrics. See docker/langfuse/README.md → Metrics."""
import sys

from common.metrics_report import main

if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
