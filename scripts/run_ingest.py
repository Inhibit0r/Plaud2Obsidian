from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from dotenv import load_dotenv

SCRIPT_DIR = Path(__file__).resolve().parent
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))

from fetch_plaud import fetch_and_save_recording, load_client, select_recordings
from process_plaud import process_raw_file
from write_wiki import apply_plan
from common import RAW_DIR


def collect_raw_files(args: argparse.Namespace) -> list[Path]:
    if args.raw_file:
        return [args.raw_file]

    client = load_client()
    recordings = client.list_recordings()

    if args.file_id:
        selected = [item for item in recordings if str(item.get("id")) == args.file_id]
        if not selected:
            raise RuntimeError(f"Recording with id {args.file_id} not found.")
    else:
        limit = args.latest or 1
        selected = select_recordings(recordings, limit=limit)

    raw_files: list[Path] = []
    for item in selected:
        raw_files.append(fetch_and_save_recording(client, item, raw_dir=RAW_DIR, refresh=args.refresh_raw))
    return raw_files


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Fetch, process, and write Plaud recordings into the local wiki")
    source_group = parser.add_mutually_exclusive_group(required=False)
    source_group.add_argument("--raw-file", type=Path, help="Process an existing raw json file")
    source_group.add_argument("--file-id", help="Fetch and process a specific Plaud recording id")
    source_group.add_argument("--latest", type=int, help="Fetch and process the latest N recordings")
    parser.add_argument("--dry-run", action="store_true", help="Build plans and print results without writing wiki state")
    parser.add_argument("--refresh-raw", action="store_true", help="Re-fetch raw json even if it already exists")
    parser.add_argument("--reprocess", action="store_true", help="Process a source even if it is already in .state/processed.json")
    return parser


def main() -> int:
    load_dotenv()
    parser = build_parser()
    args = parser.parse_args()
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
            }
        )
    print(json.dumps(results, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
