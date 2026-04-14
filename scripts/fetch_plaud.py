from __future__ import annotations

import argparse
import json
import os
import sys
import time
from datetime import datetime
from pathlib import Path
from typing import Any

import requests
from dotenv import load_dotenv

SCRIPT_DIR = Path(__file__).resolve().parent
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))

from common import RAW_DIR, ensure_dir, normalize_date, read_json, sanitize_filename, utc_now_iso, write_json


def _coerce_duration_seconds(value: Any) -> int:
    if value is None:
        return 0
    try:
        numeric = int(float(value))
    except (TypeError, ValueError):
        return 0
    if numeric >= 10000:
        return max(numeric // 1000, 0)
    return max(numeric, 0)


def _coerce_sort_timestamp(value: Any) -> int:
    if value is None:
        return 0
    try:
        numeric = int(float(value))
    except (TypeError, ValueError):
        return 0
    if numeric <= 0:
        return 0
    if numeric > 10_000_000_000:
        return numeric
    return numeric * 1000


def _normalize_timestamp_value(value: Any) -> str:
    if isinstance(value, str):
        raw = value.strip()
        if not raw:
            return ""
        try:
            parsed = datetime.fromisoformat(raw.replace("Z", "+00:00"))
            return parsed.strftime("%Y-%m-%dT%H:%M:%SZ")
        except ValueError:
            return raw
    numeric = _coerce_sort_timestamp(value)
    if not numeric:
        return ""
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(numeric / 1000))


def _parse_maybe_json(value: Any) -> Any:
    if not isinstance(value, str):
        return value
    raw = value.strip()
    if not raw or raw[0] not in "[{":
        return value
    try:
        return json.loads(raw)
    except json.JSONDecodeError:
        return value


def _normalize_segments(segments: list[dict[str, Any]]) -> list[dict[str, Any]]:
    normalized: list[dict[str, Any]] = []
    for segment in segments:
        normalized.append(
            {
                "start": _coerce_duration_seconds(segment.get("start")),
                "end": _coerce_duration_seconds(segment.get("end")),
                "speaker": segment.get("speaker"),
                "text": segment.get("text"),
            }
        )
    return normalized


def _extract_segments(detail: dict[str, Any]) -> list[dict[str, Any]]:
    candidate = _parse_maybe_json(detail.get("trans_result"))
    if isinstance(candidate, dict) and isinstance(candidate.get("segments"), list):
        return _normalize_segments([segment for segment in candidate["segments"] if isinstance(segment, dict)])
    if isinstance(candidate, list):
        return _normalize_segments([segment for segment in candidate if isinstance(segment, dict)])
    for key in ("segments", "trans_segments", "speaker_segments"):
        value = _parse_maybe_json(detail.get(key))
        if isinstance(value, list):
            return _normalize_segments([segment for segment in value if isinstance(segment, dict)])
    return []


def _extract_summary(detail: dict[str, Any]) -> str:
    for key in ("ai_content", "summary", "ai_summary", "note_content", "note"):
        value = _parse_maybe_json(detail.get(key))
        if isinstance(value, str) and value.strip():
            return value.strip()
        if isinstance(value, dict):
            parts = [str(item).strip() for item in value.values() if str(item).strip()]
            if parts:
                return "\n".join(parts)
        if isinstance(value, list):
            parts = [str(item).strip() for item in value if str(item).strip()]
            if parts:
                return "\n".join(parts)
    return ""


def _extract_transcript(detail: dict[str, Any], segments: list[dict[str, Any]]) -> str:
    if segments:
        parts = [str(segment.get("text", "")).strip() for segment in segments if segment.get("text")]
        return " ".join(parts).strip()
    for key in ("transcript", "transcription", "trans_content", "text", "content"):
        value = detail.get(key)
        if isinstance(value, str) and value.strip():
            return value.strip()
    return ""


class PlaudClient:
    def __init__(self, token: str, api_domain: str) -> None:
        self.token = token
        self.api_domain = api_domain.rstrip("/")
        self.session = requests.Session()
        self.session.headers.update({"Authorization": token})

    def get_json(self, endpoint: str) -> Any:
        response = self.session.get(f"{self.api_domain}{endpoint}", timeout=60)
        response.raise_for_status()
        data = response.json()
        redirected_domain = self._extract_redirect_domain(data)
        if redirected_domain and redirected_domain != self.api_domain:
            self.api_domain = redirected_domain
            response = self.session.get(f"{self.api_domain}{endpoint}", timeout=60)
            response.raise_for_status()
            data = response.json()
        return data

    @staticmethod
    def _extract_redirect_domain(data: Any) -> str | None:
        if not isinstance(data, dict):
            return None
        if data.get("status") != -302:
            return None
        domains = data.get("data", {}).get("domains", {})
        api_domain = str(domains.get("api") or "").strip()
        return api_domain.rstrip("/") or None

    @staticmethod
    def _extract_list_payload(data: Any) -> list[dict[str, Any]]:
        if isinstance(data, list):
            return [item for item in data if isinstance(item, dict)]
        if isinstance(data, dict) and isinstance(data.get("data_file_list"), list):
            return [item for item in data["data_file_list"] if isinstance(item, dict)]
        raise RuntimeError(f"Unexpected list response: {data}")

    @staticmethod
    def _normalize_list_item(item: dict[str, Any]) -> dict[str, Any]:
        normalized = dict(item)
        normalized["name"] = (
            str(item.get("name") or item.get("filename") or item.get("fullname") or "Untitled recording").strip()
            or "Untitled recording"
        )
        normalized["create_time"] = _normalize_timestamp_value(
            item.get("create_time") or item.get("start_time") or item.get("version_ms") or item.get("edit_time")
        )
        normalized["sort_ts"] = _coerce_sort_timestamp(
            item.get("start_time") or item.get("version_ms") or item.get("edit_time") or item.get("create_time")
        )
        normalized["duration"] = _coerce_duration_seconds(item.get("duration"))
        if "status" not in normalized:
            normalized["status"] = "done" if item.get("is_trans") or item.get("is_summary") else "pending"
        return normalized

    def list_recordings(self) -> list[dict[str, Any]]:
        data = self.get_json("/file/simple/web")
        recordings = self._extract_list_payload(data)
        return [self._normalize_list_item(item) for item in recordings]

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
    list_item = PlaudClient._normalize_list_item(list_item)
    segments = _extract_segments(detail)
    transcript = _extract_transcript(detail, segments)
    speakers = []
    for segment in segments:
        speaker = str(segment.get("speaker", "")).strip()
        if speaker and speaker not in speakers:
            speakers.append(speaker)
    create_time = _normalize_timestamp_value(detail.get("create_time")) or list_item.get("create_time") or ""
    summary = _extract_summary(detail)
    duration = _coerce_duration_seconds(detail.get("duration")) or int(list_item.get("duration") or 0)
    return {
        "schema_version": 1,
        "fetched_at": utc_now_iso(),
        "plaud": {
            "api_domain": api_domain,
            "file_id": list_item.get("id"),
            "status": detail.get("status") or list_item.get("status"),
        },
        "name": str(detail.get("name") or detail.get("filename") or list_item.get("name") or "Untitled recording").strip()
        or "Untitled recording",
        "date": normalize_date(create_time),
        "create_time": create_time,
        "duration": duration,
        "summary": summary,
        "transcript": transcript,
        "segments": segments,
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
    sorted_items = sorted(filtered, key=lambda item: int(item.get("sort_ts") or 0), reverse=True)
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
