from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from dotenv import load_dotenv

SCRIPT_DIR = Path(__file__).resolve().parent
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))

from common import STATE_DIR, read_json, write_json
from process_plaud import build_ingest_bundle, load_record, process_raw_file, validate_plan
from query_wiki import query_wiki
from routing import routing_snapshot
from run_ingest import collect_raw_files
from wiki_context import audit_vault, inventory_summary, recent_log_entries
from write_wiki import apply_plan


def run_ingest_operation(args: argparse.Namespace) -> dict[str, object]:
    raw_files = collect_raw_files(args)
    results: list[dict[str, object]] = []
    for raw_file in raw_files:
        plan, plan_path = process_raw_file(raw_file)
        write_result = apply_plan(plan, dry_run=args.dry_run, reprocess=args.reprocess)
        results.append(
            {
                "raw_file": str(raw_file),
                "plan_file": str(plan_path),
                "created": write_result.created,
                "updated": write_result.updated,
                "skipped": write_result.skipped,
                "used_fallback": bool(plan.get("meta", {}).get("used_fallback")),
                "source_title": plan.get("meta", {}).get("source_title"),
            }
        )
    return {
        "operation": "ingest",
        "results": results,
        "inventory": inventory_summary(),
        "routing": routing_snapshot(),
        "recent_log_entries": recent_log_entries(),
    }


def run_ingest_context_operation(args: argparse.Namespace) -> dict[str, object]:
    raw_files = collect_raw_files(args)
    bundles = [build_ingest_bundle(raw_file) for raw_file in raw_files]
    return {
        "operation": "ingest-context",
        "sources": bundles,
        "inventory": inventory_summary(),
        "routing": routing_snapshot(),
        "recent_log_entries": recent_log_entries(),
    }


def run_apply_plan_operation(args: argparse.Namespace) -> dict[str, object]:
    raw_record = load_record(args.raw_file)
    raw_filename = args.raw_file.name
    candidate_plan = read_json(args.plan_file)
    if not isinstance(candidate_plan, dict):
        raise RuntimeError(f"Invalid plan json: {args.plan_file}")
    validated_plan = validate_plan(candidate_plan, record=raw_record, raw_filename=raw_filename)
    stored_plan_path = STATE_DIR / "plans" / f"{args.raw_file.stem}.openclaw.plan.json"
    write_json(stored_plan_path, validated_plan)
    result = apply_plan(validated_plan, dry_run=args.dry_run, reprocess=args.reprocess)
    return {
        "operation": "apply-plan",
        "raw_file": str(args.raw_file),
        "input_plan_file": str(args.plan_file),
        "stored_plan_file": str(stored_plan_path),
        "created": result.created,
        "updated": result.updated,
        "skipped": result.skipped,
        "inventory": inventory_summary(),
        "routing": routing_snapshot(),
        "recent_log_entries": recent_log_entries(),
    }


def run_query_operation(args: argparse.Namespace) -> dict[str, object]:
    result = query_wiki(args.question, limit=args.limit)
    result["operation"] = "query"
    return result


def run_lint_operation(_: argparse.Namespace) -> dict[str, object]:
    result = audit_vault()
    result["operation"] = "lint"
    return result


def run_status_operation(_: argparse.Namespace) -> dict[str, object]:
    return {
        "operation": "status",
        "inventory": inventory_summary(),
        "routing": routing_snapshot(),
        "recent_log_entries": recent_log_entries(),
    }


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Single OpenClaw-friendly router for Plaud2Obsidian")
    subparsers = parser.add_subparsers(dest="command", required=True)

    ingest = subparsers.add_parser("ingest", help="Fetch/process/write Plaud transcripts")
    ingest_group = ingest.add_mutually_exclusive_group(required=False)
    ingest_group.add_argument("--raw-file", type=Path)
    ingest_group.add_argument("--file-id")
    ingest_group.add_argument("--latest", type=int)
    ingest.add_argument("--dry-run", action="store_true")
    ingest.add_argument("--refresh-raw", action="store_true")
    ingest.add_argument("--reprocess", action="store_true")
    ingest.set_defaults(func=run_ingest_operation)

    ingest_context = subparsers.add_parser("ingest-context", help="Return full ingest context for OpenClaw reasoning")
    ingest_context_group = ingest_context.add_mutually_exclusive_group(required=False)
    ingest_context_group.add_argument("--raw-file", type=Path)
    ingest_context_group.add_argument("--file-id")
    ingest_context_group.add_argument("--latest", type=int)
    ingest_context.add_argument("--refresh-raw", action="store_true")
    ingest_context.set_defaults(func=run_ingest_context_operation)

    apply_plan = subparsers.add_parser("apply-plan", help="Apply an externally generated ingest plan")
    apply_plan.add_argument("--raw-file", type=Path, required=True)
    apply_plan.add_argument("--plan-file", type=Path, required=True)
    apply_plan.add_argument("--dry-run", action="store_true")
    apply_plan.add_argument("--reprocess", action="store_true")
    apply_plan.set_defaults(func=run_apply_plan_operation)

    query = subparsers.add_parser("query", help="Search wiki context for OpenClaw")
    query.add_argument("question")
    query.add_argument("--limit", type=int, default=8)
    query.set_defaults(func=run_query_operation)

    lint = subparsers.add_parser("lint", help="Audit wiki for OpenClaw")
    lint.set_defaults(func=run_lint_operation)

    status = subparsers.add_parser("status", help="Return wiki inventory and recent log state")
    status.set_defaults(func=run_status_operation)

    return parser


def main() -> int:
    load_dotenv()
    parser = build_parser()
    args = parser.parse_args()
    result = args.func(args)
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
