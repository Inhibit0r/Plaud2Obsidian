#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

from dotenv import load_dotenv

SCRIPT_DIR = Path(__file__).resolve().parent
REPO_SCRIPTS_DIR = SCRIPT_DIR / "scripts"
if str(REPO_SCRIPTS_DIR) not in sys.path:
    sys.path.insert(0, str(REPO_SCRIPTS_DIR))

from fetch_plaud import PlaudClient, build_raw_recording, load_client, select_recordings
from routing import build_record_routing_context, routing_snapshot


def _source_variant(detail: dict[str, Any]) -> str:
    if detail.get("_downloaded_content"):
        return "downloaded_payload"
    if detail.get("content_list") or detail.get("pre_download_content_list"):
        return "content_list"
    if detail.get("trans_result") or detail.get("ai_content"):
        return "embedded"
    return "unknown"


def _metadata_for_file(client: PlaudClient, file_id: str) -> dict[str, Any]:
    recordings = client.list_recordings()
    list_item = next((item for item in recordings if str(item.get("id")) == file_id), None)
    if list_item is None:
        raise RuntimeError(f"Recording with id {file_id} not found.")
    tag_name_map = client.get_tag_name_map()
    detail = client.get_detail(file_id)
    record = build_raw_recording(list_item, detail, api_domain=client.api_domain, tag_name_map=tag_name_map)
    routing = build_record_routing_context(record)
    return {
        "file_id": file_id,
        "title": record.get("name"),
        "date": record.get("date"),
        "duration_seconds": record.get("duration"),
        "speakers": record.get("speakers", []),
        "plaud_tag_ids": record.get("plaud", {}).get("filetag_ids", []),
        "plaud_tag_names": record.get("plaud", {}).get("filetag_names", []),
        "has_summary": bool(record.get("summary")),
        "has_transcript": bool(record.get("transcript")),
        "transcript_segments": len(record.get("segments") or []),
        "source_variant": _source_variant(detail),
        "routing": routing,
        "raw_record": record,
    }


def command_list(args: argparse.Namespace) -> int:
    client = load_client()
    recordings = select_recordings(client.list_recordings(), limit=args.limit)
    tag_name_map = client.get_tag_name_map()
    enriched: list[dict[str, Any]] = []
    for item in recordings:
        tag_names = [tag_name_map[tag_id] for tag_id in item.get("filetag_ids", []) if tag_id in tag_name_map]
        enriched.append(
            {
                "id": item.get("id"),
                "name": item.get("name"),
                "create_time": item.get("create_time"),
                "duration": item.get("duration"),
                "status": item.get("status"),
                "filetag_ids": item.get("filetag_ids", []),
                "filetag_names": tag_names,
            }
        )
    if args.json:
        print(json.dumps(enriched, ensure_ascii=False, indent=2))
        return 0
    for item in enriched:
        tags = ",".join(item.get("filetag_names", []))
        suffix = f" [{tags}]" if tags else ""
        print(f"{item['id']}\t{item['create_time']}\t{item['name']}{suffix}")
    return 0


def command_details(args: argparse.Namespace) -> int:
    client = load_client()
    detail = client.get_detail(args.file_id)
    print(json.dumps(detail, ensure_ascii=False, indent=2))
    return 0


def command_tags(_: argparse.Namespace) -> int:
    client = load_client()
    print(json.dumps(client.get_file_tags(), ensure_ascii=False, indent=2))
    return 0


def command_metadata(args: argparse.Namespace) -> int:
    client = load_client()
    metadata = _metadata_for_file(client, args.file_id)
    print(json.dumps(metadata, ensure_ascii=False, indent=2))
    return 0


def command_route_context(args: argparse.Namespace) -> int:
    client = load_client()
    metadata = _metadata_for_file(client, args.file_id)
    output = {
        "file_id": metadata["file_id"],
        "title": metadata["title"],
        "plaud_tag_names": metadata["plaud_tag_names"],
        "routing": metadata["routing"],
        "routing_snapshot": routing_snapshot(),
    }
    print(json.dumps(output, ensure_ascii=False, indent=2))
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Auxiliary Plaud metadata client for Plaud2Obsidian/OpenClaw",
    )
    subparsers = parser.add_subparsers(dest="command", required=True)

    list_parser = subparsers.add_parser("list", help="List latest Plaud recordings")
    list_parser.add_argument("--limit", type=int, default=10)
    list_parser.add_argument("--json", action="store_true")
    list_parser.set_defaults(func=command_list)

    details_parser = subparsers.add_parser("details", help="Dump raw Plaud detail response")
    details_parser.add_argument("file_id")
    details_parser.set_defaults(func=command_details)

    tags_parser = subparsers.add_parser("tags", help="Dump Plaud filetag/folder metadata")
    tags_parser.set_defaults(func=command_tags)

    metadata_parser = subparsers.add_parser("metadata", help="Return normalized Plaud metadata for one recording")
    metadata_parser.add_argument("file_id")
    metadata_parser.set_defaults(func=command_metadata)

    route_parser = subparsers.add_parser("route-context", help="Return routing hints for Plaud2Obsidian/OpenClaw")
    route_parser.add_argument("file_id")
    route_parser.set_defaults(func=command_route_context)
    return parser


def main() -> int:
    load_dotenv(SCRIPT_DIR / ".env")
    parser = build_parser()
    args = parser.parse_args()
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())
