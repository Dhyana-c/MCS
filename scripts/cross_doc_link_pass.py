#!/usr/bin/env python
"""Run cross-document linking pass on a graph database.

This script applies cross-document linking strategies to improve
graph connectivity, persists the new edges, and reports before/after metrics.
"""

import argparse
import json
import sys
from pathlib import Path

# Add parent to path for imports
sys.path.insert(0, str(Path(__file__).parent.parent))

from mcs.diagnostics.graph_quality import diagnose_graph
from mcs.plugins.phase1.cross_doc_linker import (
    cross_doc_link_pass_from_db,
    find_cross_doc_candidates_by_name,
    find_cross_doc_candidates_by_alias,
    load_graph_from_db,
)


def main():
    parser = argparse.ArgumentParser(
        description="Run cross-document linking pass on a graph"
    )
    parser.add_argument("db_path", type=str, help="Path to SQLite database")
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Only analyze candidates, don't apply or save changes",
    )
    parser.add_argument(
        "--output",
        type=str,
        help="Output database path (default: modify input in place)",
    )
    parser.add_argument(
        "--strategies",
        type=str,
        nargs="+",
        default=["name_match", "alias_match"],
        choices=["name_match", "alias_match"],
        help="Strategies to use",
    )
    parser.add_argument(
        "--confidence",
        type=float,
        default=0.8,
        help="Minimum confidence threshold",
    )
    parser.add_argument(
        "--json",
        type=str,
        help="Output results as JSON to file",
    )

    args = parser.parse_args()

    if not Path(args.db_path).exists():
        print(f"Error: Database not found: {args.db_path}", file=sys.stderr)
        sys.exit(1)

    print(f"Loading graph from: {args.db_path}")
    graph = load_graph_from_db(args.db_path)

    # Baseline metrics
    print("\n=== Baseline Metrics ===")
    baseline = diagnose_graph(graph)
    baseline.print_summary()

    # Find candidates (for reporting / dry-run preview)
    print("\n=== Finding Cross-Document Link Candidates ===")
    all_candidates = []
    if "name_match" in args.strategies:
        name_candidates = find_cross_doc_candidates_by_name(graph)
        print(f"Name match candidates: {len(name_candidates)}")
        all_candidates.extend(name_candidates)
    if "alias_match" in args.strategies:
        alias_candidates = find_cross_doc_candidates_by_alias(graph)
        print(f"Alias match candidates: {len(alias_candidates)}")
        all_candidates.extend(alias_candidates)

    result = {
        "baseline": baseline.to_dict(),
        "candidates_found": len(all_candidates),
        "strategies": args.strategies,
        "confidence_threshold": args.confidence,
        "dry_run": args.dry_run,
    }

    if args.dry_run:
        print("\n(dry-run: no links applied, no changes written)")
    elif all_candidates:
        # Apply + persist via the db-level pass.
        print("\n=== Applying & Persisting Cross-Document Links ===")
        pass_result = cross_doc_link_pass_from_db(
            args.db_path,
            output_db_path=args.output,
            strategies=args.strategies,
            confidence_threshold=args.confidence,
        )
        target = pass_result["target_db_path"]
        print(f"Links applied: {pass_result['links_applied']}")
        print(f"Edges persisted to {target}: {pass_result['edges_persisted']}")

        # Reload from the persisted db to confirm the round-trip.
        print("\n=== New Metrics (reloaded from db) ===")
        new_report = diagnose_graph(load_graph_from_db(target))
        new_report.print_summary()

        result["target_db_path"] = target
        result["links_applied"] = pass_result["links_applied"]
        result["edges_persisted"] = pass_result["edges_persisted"]
        result["new_metrics"] = new_report.to_dict()
    else:
        print("\nNo candidates found; nothing to apply.")

    # Output JSON if requested
    if args.json:
        with open(args.json, "w", encoding="utf-8") as f:
            json.dump(result, f, indent=2, ensure_ascii=False)
        print(f"\nResults saved to: {args.json}")


if __name__ == "__main__":
    main()
