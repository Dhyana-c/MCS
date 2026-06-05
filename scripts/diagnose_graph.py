#!/usr/bin/env python
"""Run graph quality diagnostic on an existing database and output baseline metrics."""

import argparse
import json
import sys
from pathlib import Path

from mcs.diagnostics.graph_quality import diagnose_from_db


def main():
    parser = argparse.ArgumentParser(description="Run graph quality diagnostic")
    parser.add_argument("db_path", type=str, help="Path to SQLite database")
    parser.add_argument("--json", type=str, help="Output JSON report to file")
    parser.add_argument("--quiet", action="store_true", help="Only print summary, no JSON")

    args = parser.parse_args()

    if not Path(args.db_path).exists():
        print(f"Error: Database not found: {args.db_path}", file=sys.stderr)
        sys.exit(1)

    print(f"Loading graph from: {args.db_path}")
    report = diagnose_from_db(args.db_path)

    # Print summary to terminal
    report.print_summary()

    # Optionally save JSON
    if args.json:
        with open(args.json, "w", encoding="utf-8") as f:
            f.write(report.to_json())
        print(f"\nJSON report saved to: {args.json}")


if __name__ == "__main__":
    main()
