from __future__ import annotations

import argparse
import gzip
import json
import os
import re
import sys
import time
from datetime import datetime
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

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


def _coerce_string_list(value: Any) -> list[str]:
    parsed = _parse_maybe_json(value)
    if parsed is None:
        return []
    if isinstance(parsed, list):
        return [str(item).strip() for item in parsed if str(item).strip()]
    if isinstance(parsed, str):
        raw = parsed.strip()
        if not raw:
            return []
        if "," in raw:
            return [item.strip() for item in raw.split(",") if item.strip()]
        return [raw]
    text = str(parsed).strip()
    return [text] if text else []


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


def _iter_nodes(value: Any) -> Any:
    parsed = _parse_maybe_json(value)
    yield parsed
    if isinstance(parsed, dict):
        for child in parsed.values():
            yield from _iter_nodes(child)
    elif isinstance(parsed, list):
        for child in parsed:
            yield from _iter_nodes(child)


def _collapse_text(value: Any) -> str:
    parsed = _parse_maybe_json(value)
    if isinstance(parsed, str):
        return parsed.strip()
    if isinstance(parsed, list):
        parts = [_collapse_text(item) for item in parsed]
        return "\n".join(part for part in parts if part).strip()
    if isinstance(parsed, dict):
        prioritized_keys = ("title", "summary", "content", "text", "note", "description")
        parts: list[str] = []
        seen: set[str] = set()
        for key in prioritized_keys:
            if key not in parsed:
                continue
            part = _collapse_text(parsed.get(key))
            if part and part not in seen:
                seen.add(part)
                parts.append(part)
        for key, raw_value in parsed.items():
            if key in prioritized_keys:
                continue
            part = _collapse_text(raw_value)
            if part and part not in seen:
                seen.add(part)
                parts.append(part)
        return "\n".join(parts).strip()
    if parsed is None:
        return ""
    return str(parsed).strip()


def _normalize_api_domain(value: str) -> str:
    raw = str(value or "").strip()
    if not raw:
        raise RuntimeError("PLAUD_API_DOMAIN must not be empty.")

    # Some copied values end up like: `api.plaud.ai (http://api.plaud.ai/)`.
    raw = re.sub(r"\s*\([^)]*\)\s*$", "", raw).strip()
    if "://" not in raw:
        raw = f"https://{raw}"

    parsed = urlparse(raw)
    if not parsed.netloc:
        raise RuntimeError(f"Invalid PLAUD_API_DOMAIN: {value!r}")
    if any(ch.isspace() for ch in parsed.netloc) or "(" in parsed.netloc or ")" in parsed.netloc:
        raise RuntimeError(f"Invalid PLAUD_API_DOMAIN host: {parsed.netloc!r}")

    return f"{parsed.scheme or 'https'}://{parsed.netloc}".rstrip("/")


def _extract_tag_entries(value: Any) -> list[dict[str, str]]:
    entries: list[dict[str, str]] = []
    seen: set[str] = set()

    def walk(node: Any) -> None:
        parsed = _parse_maybe_json(node)
        if isinstance(parsed, list):
            for item in parsed:
                walk(item)
            return
        if not isinstance(parsed, dict):
            return

        tag_id = parsed.get("id") or parsed.get("filetag_id") or parsed.get("tag_id") or parsed.get("folder_id")
        tag_name = (
            parsed.get("name")
            or parsed.get("filetag_name")
            or parsed.get("tag_name")
            or parsed.get("folder_name")
            or parsed.get("title")
        )
        tag_id_text = str(tag_id).strip() if tag_id is not None else ""
        tag_name_text = str(tag_name).strip() if tag_name is not None else ""
        if tag_id_text and tag_name_text and tag_id_text not in seen:
            seen.add(tag_id_text)
            entries.append({"id": tag_id_text, "name": tag_name_text})

        for child in parsed.values():
            walk(child)

    walk(value)
    return entries


def _extract_tag_ids(*values: Any) -> list[str]:
    seen: set[str] = set()
    result: list[str] = []
    for value in values:
        for candidate in _coerce_string_list(value):
            key = candidate.casefold()
            if key in seen:
                continue
            seen.add(key)
            result.append(candidate)
    return result


def _extract_segments(detail: dict[str, Any]) -> list[dict[str, Any]]:
    for node in _iter_nodes(detail):
        if not isinstance(node, dict):
            continue
        candidate = _parse_maybe_json(node.get("trans_result"))
        if isinstance(candidate, dict) and isinstance(candidate.get("segments"), list):
            return _normalize_segments([segment for segment in candidate["segments"] if isinstance(segment, dict)])
        if isinstance(candidate, list):
            return _normalize_segments([segment for segment in candidate if isinstance(segment, dict)])
        for key in ("segments", "trans_segments", "speaker_segments", "utterances", "paragraphs", "sentence_list"):
            value = _parse_maybe_json(node.get(key))
            if isinstance(value, list):
                normalized = _normalize_segments([segment for segment in value if isinstance(segment, dict)])
                if any(segment.get("text") for segment in normalized):
                    return normalized
    return []


def _extract_summary(detail: dict[str, Any]) -> str:
    for node in _iter_nodes(detail):
        if not isinstance(node, dict):
            continue
        for key in ("ai_content", "summary", "ai_summary", "note_content", "note", "abstract", "memo"):
            if key not in node:
                continue
            text = _collapse_text(node.get(key))
            if text:
                return text
    return ""


def _extract_transcript(detail: dict[str, Any], segments: list[dict[str, Any]]) -> str:
    if segments:
        parts = [str(segment.get("text", "")).strip() for segment in segments if segment.get("text")]
        return " ".join(parts).strip()
    best = ""
    for node in _iter_nodes(detail):
        if not isinstance(node, dict):
            continue
        for key in ("transcript", "transcription", "trans_content", "text", "content", "full_text"):
            if key not in node:
                continue
            text = _collapse_text(node.get(key))
            if len(text) > len(best):
                best = text
    return best


class PlaudClient:
    def __init__(self, token: str, api_domain: str) -> None:
        self.token = token
        self.api_domain = _normalize_api_domain(api_domain)
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
        if not api_domain:
            return None
        return _normalize_api_domain(api_domain)

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
        normalized["filetag_ids"] = _extract_tag_ids(
            item.get("filetag_id_list"),
            item.get("tag_id_list"),
            item.get("file_tag_id_list"),
        )
        if "status" not in normalized:
            normalized["status"] = "done" if item.get("is_trans") or item.get("is_summary") else "pending"
        return normalized

    def list_recordings(self) -> list[dict[str, Any]]:
        data = self.get_json("/file/simple/web")
        recordings = self._extract_list_payload(data)
        return [self._normalize_list_item(item) for item in recordings]

    def get_file_tags(self) -> Any:
        return self.get_json("/filetag/")

    def get_tag_name_map(self) -> dict[str, str]:
        return {entry["id"]: entry["name"] for entry in _extract_tag_entries(self.get_file_tags())}

    def get_detail(self, file_id: str) -> dict[str, Any]:
        data = self.get_json(f"/file/detail/{file_id}")
        if isinstance(data, dict) and "data" in data:
            detail = data["data"] or {}
            if isinstance(detail, dict):
                return self._expand_detail_content(detail)
            return {}
        raise RuntimeError(f"Unexpected detail response for {file_id}: {data}")

    def _expand_detail_content(self, detail: dict[str, Any]) -> dict[str, Any]:
        entries = self._extract_download_entries(detail)
        if not entries:
            return detail
        downloaded: list[dict[str, Any]] = []
        for entry in entries:
            data_link = str(entry.get("data_link") or entry.get("download_link") or entry.get("url") or "").strip()
            if not data_link:
                continue
            payload = self._download_payload(data_link)
            if payload is None:
                continue
            downloaded.append({"meta": entry, "payload": payload})
        if not downloaded:
            return detail
        enriched = dict(detail)
        enriched["_downloaded_content"] = downloaded
        return enriched

    @staticmethod
    def _extract_download_entries(detail: dict[str, Any]) -> list[dict[str, Any]]:
        entries: list[dict[str, Any]] = []
        seen: set[str] = set()
        for key in ("content_list", "pre_download_content_list"):
            raw_entries = detail.get(key)
            if not isinstance(raw_entries, list):
                continue
            for item in raw_entries:
                if not isinstance(item, dict):
                    continue
                data_link = str(item.get("data_link") or item.get("download_link") or item.get("url") or "").strip()
                if not data_link or data_link in seen:
                    continue
                seen.add(data_link)
                entries.append(item)
        return entries

    def _download_payload(self, url: str) -> Any:
        # `data_link` from Plaud detail is a presigned S3 URL.
        # It must be fetched without the Plaud bearer header, otherwise S3
        # rejects the request because two auth mechanisms are present.
        response = requests.get(url, timeout=60)
        response.raise_for_status()
        content = response.content
        if url.endswith(".gz") or content[:2] == b"\x1f\x8b":
            try:
                content = gzip.decompress(content)
            except OSError:
                pass
        text = content.decode("utf-8", errors="replace").strip()
        if not text:
            return None
        parsed = _parse_maybe_json(text)
        return parsed


def load_client() -> PlaudClient:
    load_dotenv()
    token = os.getenv("PLAUD_TOKEN")
    api_domain = os.getenv("PLAUD_API_DOMAIN")
    if not token or not api_domain:
        raise RuntimeError("PLAUD_TOKEN and PLAUD_API_DOMAIN must be set in .env")
    return PlaudClient(token=token, api_domain=_normalize_api_domain(api_domain))


def build_raw_recording(
    list_item: dict[str, Any],
    detail: dict[str, Any],
    api_domain: str,
    tag_name_map: dict[str, str] | None = None,
) -> dict[str, Any]:
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
    filetag_ids = _extract_tag_ids(
        detail.get("filetag_id_list"),
        detail.get("tag_id_list"),
        detail.get("file_tag_id_list"),
        list_item.get("filetag_ids"),
    )
    resolved_tag_names: list[str] = []
    seen_names: set[str] = set()
    for tag_id in filetag_ids:
        tag_name = str((tag_name_map or {}).get(tag_id, "")).strip()
        if not tag_name:
            continue
        key = tag_name.casefold()
        if key in seen_names:
            continue
        seen_names.add(key)
        resolved_tag_names.append(tag_name)
    return {
        "schema_version": 1,
        "fetched_at": utc_now_iso(),
        "plaud": {
            "api_domain": api_domain,
            "file_id": list_item.get("id"),
            "status": detail.get("status") or list_item.get("status"),
            "filetag_ids": filetag_ids,
            "filetag_names": resolved_tag_names,
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
    tag_name_map: dict[str, str] | None = None,
) -> Path:
    detail = client.get_detail(str(list_item["id"]))
    record = build_raw_recording(list_item, detail, api_domain=client.api_domain, tag_name_map=tag_name_map)
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
    try:
        tag_name_map = client.get_tag_name_map()
    except Exception:
        tag_name_map = {}
    for item in recordings:
        tag_hint = ",".join(tag_name_map.get(tag_id, tag_id) for tag_id in (item.get("filetag_ids") or []))
        suffix = f"\t{tag_hint}" if tag_hint else ""
        print(f"{item.get('id')}\t{item.get('create_time')}\t{item.get('name')}{suffix}")
    return 0


def command_tags(_: argparse.Namespace) -> int:
    client = load_client()
    print(json.dumps(client.get_file_tags(), ensure_ascii=False, indent=2))
    return 0


def command_fetch(args: argparse.Namespace) -> int:
    client = load_client()
    ensure_dir(RAW_DIR)
    recordings = client.list_recordings()
    try:
        tag_name_map = client.get_tag_name_map()
    except Exception:
        tag_name_map = {}

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
        path = fetch_and_save_recording(client, item, RAW_DIR, refresh=args.refresh, tag_name_map=tag_name_map)
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

    tags_parser = subparsers.add_parser("tags", help="Fetch Plaud filetag/folder metadata")
    tags_parser.set_defaults(func=command_tags)

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
