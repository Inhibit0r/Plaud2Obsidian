#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

SCRIPT_DIR = Path(__file__).resolve().parent
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))

from common import RAW_DIR, read_json


def _text_len(value: Any) -> int:
    return len(str(value or "").strip())


def audit_raw_file(path: Path, *, prompt_limit: int) -> dict[str, Any]:
    record = read_json(path, default={})
    if not isinstance(record, dict):
        return {
            "raw_file": str(path),
            "status": "error",
            "warnings": ["raw file is not a JSON object"],
        }

    transcript_chars = _text_len(record.get("transcript"))
    summary_chars = _text_len(record.get("summary"))
    segments = record.get("segments") or []
    segment_count = len(segments) if isinstance(segments, list) else 0
    segment_text_chars = 0
    if isinstance(segments, list):
        segment_text_chars = sum(_text_len(segment.get("text")) for segment in segments if isinstance(segment, dict))

    source_chars = segment_text_chars or transcript_chars
    duration_seconds = int(record.get("duration") or 0)
    warnings: list[str] = []
    if source_chars <= 0:
        warnings.append("no transcript text or segment text")
    if duration_seconds >= 900 and source_chars < 2000:
        warnings.append("long recording has suspiciously short transcript text")
    if summary_chars <= 0:
        warnings.append("empty Plaud AI summary")
    if source_chars > prompt_limit:
        warnings.append(f"source text exceeds prompt limit by about {source_chars - prompt_limit} chars")

    status = "ok"
    if any(warning.startswith("no transcript") for warning in warnings):
        status = "error"
    elif warnings:
        status = "warn"

    return {
        "raw_file": str(path),
        "file_id": record.get("plaud", {}).get("file_id"),
        "title": record.get("name"),
        "date": record.get("date"),
        "duration_seconds": duration_seconds,
        "transcript_chars": transcript_chars,
        "segment_count": segment_count,
        "segment_text_chars": segment_text_chars,
        "summary_chars": summary_chars,
        "prompt_limit_chars": prompt_limit,
        "prompt_would_truncate": source_chars > prompt_limit,
        "status": status,
        "warnings": warnings,
    }


def collect_files(args: argparse.Namespace) -> list[Path]:
    if args.raw_file:
        return [args.raw_file]
    return sorted(path for path in RAW_DIR.glob("*.json") if path.is_file())


def main() -> int:
    parser = argparse.ArgumentParser(description="Audit Plaud raw transcript integrity")
    parser.add_argument("--raw-file", type=Path)
    parser.add_argument("--prompt-limit", type=int, default=22000)
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args()

    results = [audit_raw_file(path, prompt_limit=args.prompt_limit) for path in collect_files(args)]
    by_file_id: dict[str, list[dict[str, Any]]] = {}
    for result in results:
        file_id = str(result.get("file_id") or "").strip()
        if file_id:
            by_file_id.setdefault(file_id, []).append(result)
    for duplicates in by_file_id.values():
        if len(duplicates) <= 1:
            continue
        names = [Path(str(item["raw_file"])).name for item in duplicates]
        for item in duplicates:
            item["warnings"].append("duplicate file_id in raw/: " + ", ".join(names))
            if item["status"] == "ok":
                item["status"] = "warn"
    if args.json:
        print(json.dumps(results, ensure_ascii=False, indent=2))
        return 0

    for result in results:
        warnings = "; ".join(result["warnings"]) or "ok"
        print(
            f"{result['status'].upper()}\t"
            f"{result['transcript_chars']} chars\t"
            f"{result['segment_count']} segments\t"
            f"{result['raw_file']}\t"
            f"{warnings}"
        )
    return 1 if any(result["status"] == "error" for result in results) else 0


if __name__ == "__main__":
    raise SystemExit(main())
