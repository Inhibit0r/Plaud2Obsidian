from __future__ import annotations

import argparse
import os
import sys
import time
from pathlib import Path
from typing import Any

import requests
from dotenv import load_dotenv

SCRIPT_DIR = Path(__file__).resolve().parent
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))

from common import RAW_DIR, ensure_dir, normalize_date, read_json, sanitize_filename, utc_now_iso, write_json


class PlaudClient:
    def __init__(self, token: str, api_domain: str) -> None:
        self.token = token
        self.api_domain = api_domain.rstrip("/")
        self.session = requests.Session()
        self.session.headers.update({"Authorization": token})

    def get_json(self, endpoint: str) -> Any:
        response = self.session.get(f"{self.api_domain}{endpoint}", timeout=60)
        response.raise_for_status()
        return response.json()

    def list_recordings(self) -> list[dict[str, Any]]:
        data = self.get_json("/file/simple/web")
        if not isinstance(data, list):
            raise RuntimeError(f"Unexpected list response: {data}")
        return data

    def get_detail(self, file_id: str) -> dict[str, Any]:
        data = self.get_json(f"/file/detail/{file_id}")
        if isinstance(data, dict) and "data" in data:
            return data["data"] or {}
        raise RuntimeError(f"Unexpected detail response for {file_id}: {data}")


def load_client() -> PlaudClient:
    load_dotenv()
    token = os.getenv("PLAUD_TOKEN")
    api_domain = os.getenv("PLAUD_API_DOMAIN")
    if not token or not api_domain:
        raise RuntimeError("PLAUD_TOKEN and PLAUD_API_DOMAIN must be set in .env")
    return PlaudClient(token=token, api_domain=api_domain)


def build_raw_recording(list_item: dict[str, Any], detail: dict[str, Any], api_domain: str) -> dict[str, Any]:
    segments = detail.get("trans_result", {}).get("segments", []) or []
    transcript_parts = [str(segment.get("text", "")).strip() for segment in segments if segment.get("text")]
    speakers = []
    for segment in segments:
        speaker = str(segment.get("speaker", "")).strip()
        if speaker and speaker not in speakers:
            speakers.append(speaker)
    create_time = detail.get("create_time") or list_item.get("create_time") or ""
    ai_content = detail.get("ai_content")
    if isinstance(ai_content, str):
        summary = ai_content
    elif ai_content:
        summary = str(ai_content)
    else:
        summary = ""
    return {
        "schema_version": 1,
        "fetched_at": utc_now_iso(),
        "plaud": {
            "api_domain": api_domain,
            "file_id": list_item.get("id"),
            "status": detail.get("status") or list_item.get("status"),
        },
        "name": detail.get("name") or list_item.get("name") or "Untitled recording",
        "date": normalize_date(create_time),
        "create_time": create_time,
        "duration": detail.get("duration") or list_item.get("duration") or 0,
        "summary": summary,
        "transcript": " ".join(transcript_parts).strip(),
        "segments": [
            {
                "start": segment.get("start"),
                "end": segment.get("end"),
                "speaker": segment.get("speaker"),
                "text": segment.get("text"),
            }
            for segment in segments
        ],
        "speakers": speakers,
    }


def raw_filename_for_recording(recording: dict[str, Any]) -> str:
    file_id = recording.get("plaud", {}).get("file_id") or "unknown"
    date_value = recording.get("date") or "unknown-date"
    title = sanitize_filename(recording.get("name") or "untitled", max_length=100)
    return f"{date_value}__{title}__{file_id}.json"


def fetch_and_save_recording(
    client: PlaudClient,
    list_item: dict[str, Any],
    raw_dir: Path,
    refresh: bool = False,
) -> Path:
    detail = client.get_detail(str(list_item["id"]))
    record = build_raw_recording(list_item, detail, api_domain=client.api_domain)
    filename = raw_filename_for_recording(record)
    target_path = raw_dir / filename
    if target_path.exists() and not refresh:
        return target_path
    write_json(target_path, record)
    return target_path


def select_recordings(recordings: list[dict[str, Any]], limit: int | None = None) -> list[dict[str, Any]]:
    filtered = [item for item in recordings if str(item.get("status", "")).lower() in {"done", "completed", ""}]
    sorted_items = sorted(filtered, key=lambda item: item.get("create_time") or "", reverse=True)
    return sorted_items[:limit] if limit else sorted_items


def command_list(args: argparse.Namespace) -> int:
    client = load_client()
    recordings = select_recordings(client.list_recordings(), limit=args.limit)
    for item in recordings:
        print(f"{item.get('id')}\t{item.get('create_time')}\t{item.get('name')}")
    return 0


def command_fetch(args: argparse.Namespace) -> int:
    client = load_client()
    ensure_dir(RAW_DIR)
    recordings = client.list_recordings()

    if args.file_id:
        candidate = next((item for item in recordings if str(item.get("id")) == args.file_id), None)
        if candidate is None:
            raise RuntimeError(f"Recording with id {args.file_id} not found in Plaud account.")
        selected = [candidate]
    else:
        selected = select_recordings(recordings, limit=args.limit)

    saved: list[Path] = []
    for index, item in enumerate(selected, start=1):
        print(f"[{index}/{len(selected)}] fetching {item.get('name')} ({item.get('id')})")
        path = fetch_and_save_recording(client, item, RAW_DIR, refresh=args.refresh)
        saved.append(path)
        if index < len(selected):
            time.sleep(args.sleep_seconds)

    print("\nSaved raw files:")
    for path in saved:
        print(path.relative_to(RAW_DIR.parent))
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Fetch recordings and transcript data from Plaud into raw/")
    subparsers = parser.add_subparsers(dest="command", required=True)

    list_parser = subparsers.add_parser("list", help="List latest Plaud recordings")
    list_parser.add_argument("--limit", type=int, default=10)
    list_parser.set_defaults(func=command_list)

    fetch_parser = subparsers.add_parser("fetch", help="Fetch one or more recordings into raw/")
    fetch_parser.add_argument("--limit", type=int, default=1, help="Fetch the latest N done recordings")
    fetch_parser.add_argument("--file-id", help="Fetch a specific recording id instead of latest N")
    fetch_parser.add_argument("--refresh", action="store_true", help="Overwrite an already saved raw json")
    fetch_parser.add_argument("--sleep-seconds", type=float, default=0.5)
    fetch_parser.set_defaults(func=command_fetch)

    return parser


def main() -> int:
    parser = build_parser()
    args = parser.parse_args()
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())
