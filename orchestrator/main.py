"""CLI: python -m orchestrator.main <TICKER>"""
import asyncio
import sys

from common.telemetry import setup
from orchestrator.graph import run


def main() -> None:
    if len(sys.argv) != 2:
        print("usage: python -m orchestrator.main <TICKER>")
        raise SystemExit(2)
    setup("orchestrator")
    state = asyncio.run(run(sys.argv[1]))
    print("\n=== MEMO ===\n")
    print(state.get("memo", "(no memo)"))
    print(f"\n=== RECOMMENDATION: {state.get('recommendation', 'HOLD')} ===")


if __name__ == "__main__":
    main()
