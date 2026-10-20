import argparse
import json
from datetime import date, datetime
from pathlib import Path
from zoneinfo import ZoneInfo

from .collector import collect, verify_artifacts
from .window import Window


def main():
    parser = argparse.ArgumentParser(description="Read-only Polymarket BTC 15-minute history collector; no wallet or trades")
    commands = parser.add_subparsers(dest="command", required=True)
    collection = commands.add_parser("collect", help="Download actual public source responses and export a completeness audit")
    collection.add_argument("--data-dir", type=Path, default=Path("data"))
    collection.add_argument("--days", type=int, default=30)
    collection.add_argument("--timezone", default="Etc/GMT+8")
    collection.add_argument("--end-date", type=date.fromisoformat, help="Exclusive local date; defaults to today's start")
    collection.add_argument("--max-markets", type=int, help="Diagnostic limit only: never marks the full requested window complete")
    collection.add_argument("--skip-trades", action="store_true", help="Skip the alternative public trade-print source")
    verification = commands.add_parser("verify", help="Check saved CSV and cached source-response hashes")
    verification.add_argument("directory", type=Path)
    analysis = commands.add_parser("analyze", help="Analyze real data and freeze one training-selected execution scenario before holdout evaluation")
    analysis.add_argument("directory", type=Path)
    args = parser.parse_args()
    if args.command == "analyze":
        from .research import run_research
        report = run_research(args.directory)
        print(json.dumps(report, indent=2, allow_nan=False))
        return 0
    if args.command == "verify":
        failures = verify_artifacts(args.directory)
        print(json.dumps({"integrity_ok": not failures, "failures": failures}, indent=2))
        return 1 if failures else 0
    if args.max_markets is not None and args.max_markets < 1:
        parser.error("--max-markets must be positive")
    end = args.end_date or datetime.now(ZoneInfo(args.timezone)).date()
    window = Window(end, args.days, args.timezone)
    audit = collect(window, args.data_dir.resolve(), args.max_markets, not args.skip_trades, progress=lambda text: print(text, flush=True))
    # A blocked/incomplete collection must fail visibly to automation, even if its audit was written successfully.
    return 0 if audit["analysis_ready"] and audit["execution_backtest_ready"] else 2


if __name__ == "__main__":
    raise SystemExit(main())
