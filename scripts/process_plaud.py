from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path
from typing import Any

from dotenv import load_dotenv

SCRIPT_DIR = Path(__file__).resolve().parent
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))

from common import (
    PROMPTS_DIR,
    ROOT_DIR,
    STATE_DIR,
    clean_tags,
    load_text,
    normalize_date,
    raw_source_link,
    read_json,
    seconds_to_timestamp,
    utc_now_iso,
    write_json,
)
from llm_client import LLMError, chat_json
from routing import build_record_routing_context
from wiki_context import build_ingest_context, render_note_context_block


def load_record(path: Path) -> dict[str, Any]:
    data = read_json(path)
    if not isinstance(data, dict):
        raise RuntimeError(f"Invalid raw json: {path}")
    return data


def build_transcript_excerpt(record: dict[str, Any], max_chars: int) -> str:
    segments = record.get("segments") or []
    if segments:
        lines: list[str] = []
        used = 0
        for segment in segments:
            text = str(segment.get("text", "")).strip()
            if not text:
                continue
            speaker = str(segment.get("speaker", "")).strip() or "Speaker"
            timestamp = seconds_to_timestamp(segment.get("start"))
            line = f"[{timestamp}] {speaker}: {text}"
            if used + len(line) + 1 > max_chars:
                break
            lines.append(line)
            used += len(line) + 1
        if lines:
            return "\n".join(lines)
    transcript = str(record.get("transcript", "")).strip()
    return transcript[:max_chars]


def build_prompt(record: dict[str, Any], raw_filename: str, existing_context: dict[str, Any]) -> tuple[str, str]:
    ingest_contract = load_text(ROOT_DIR / "AGENTS.md")
    project_context = load_text(ROOT_DIR / "CONTEXT.md")
    index_overview = load_text(ROOT_DIR / "index.md")
    ingest_rules = load_text(PROMPTS_DIR / "plaud_ingest.md")
    max_chars = int(os.getenv("LLM_MAX_SOURCE_CHARS", "22000"))
    transcript_excerpt = build_transcript_excerpt(record, max_chars=max_chars)
    inventory = existing_context.get("inventory", {})
    relevant_notes = existing_context.get("relevant_notes", [])
    routing_context = existing_context.get("routing", {})
    folder_inventory = existing_context.get("folder_inventory", [])
    system_prompt = (
        "Ты аккуратный knowledge-engineering агент. "
        "Верни только валидный JSON без пояснений и markdown."
    )
    user_prompt = f"""
{ingest_rules}

Ниже стратегический контекст проекта:
```md
{project_context}
```

Ниже конституция проекта:
```md
{ingest_contract}
```

Текущий index.md:
```md
{index_overview}
```

Снимок vault:
- inventory_counts: {inventory.get("counts", {})}
- inventory_samples: {inventory.get("samples", {})}

Наиболее релевантные существующие заметки:
{render_note_context_block(relevant_notes)}

Routing context:
- plaud_tag_names: {routing_context.get("plaud_tag_names", [])}
- mapped_roots: {routing_context.get("mapped_roots", [])}
- suggested_folders_by_type: {routing_context.get("suggested_folders_by_type", {})}
- allow_new_folders: {routing_context.get("allow_new_folders")}
- existing_folders_in_vault: {folder_inventory}

Исходная запись:
- raw_filename: {raw_filename}
- source_link: {raw_source_link(raw_filename)}
- file_id: {record.get("plaud", {}).get("file_id")}
- title: {record.get("name")}
- date: {record.get("date")}
- create_time: {record.get("create_time")}
- duration_seconds: {record.get("duration")}
- speakers: {record.get("speakers", [])}
- plaud_tag_names: {record.get("plaud", {}).get("filetag_names", [])}

Plaud AI summary:
{record.get("summary", "") or "(empty)"}

Transcript excerpt:
{transcript_excerpt or "(empty)"}

Схема ответа:
{{
  "source_kind": "meeting|idea|lecture|research|tasks|mixed",
  "meeting": null | {{
    "title": "string",
    "summary": "string",
    "folder": "relative path inside vault, e.g. meetings or domains/work/meetings",
    "participants": ["existing or new person title"],
    "projects": ["existing or new project title"],
    "ideas": ["idea title"],
    "concepts": ["concept title"],
    "decisions": ["bullet"],
    "tasks": ["bullet"],
    "highlights": ["bullet"],
    "tags": ["tag"]
  }},
  "people": [
    {{
      "title": "string",
      "existing_title": "string|null",
      "folder": "relative path inside vault",
      "summary": "string",
      "role": "string",
      "facts": ["bullet"],
      "related_titles": ["note title"],
      "tags": ["tag"]
    }}
  ],
  "projects": [
    {{
      "title": "string",
      "existing_title": "string|null",
      "folder": "relative path inside vault",
      "summary": "string",
      "status": "string",
      "facts": ["bullet"],
      "related_titles": ["note title"],
      "tags": ["tag"]
    }}
  ],
  "ideas": [
    {{
      "title": "string",
      "existing_title": "string|null",
      "folder": "relative path inside vault",
      "summary": "string",
      "details": ["bullet"],
      "related_titles": ["note title"],
      "tags": ["tag"]
    }}
  ],
  "concepts": [
    {{
      "title": "string",
      "existing_title": "string|null",
      "folder": "relative path inside vault",
      "summary": "string",
      "details": ["bullet"],
      "related_titles": ["note title"],
      "tags": ["tag"]
    }}
  ]
}}

Дополнительные требования:
- Не копируй длинные фрагменты транскрипта дословно.
- Используй `existing_title`, только если сущность уже есть в vault и это точно тот же объект.
- Поле `folder` должно быть относительным путём внутри `vault/`.
- Предпочитай уже существующие папки.
- Новую папку создавай только если Plaud tags и содержание записи дают сильный сигнал, что нужен новый раздел.
- Для `meeting.title` делай конкретный human-readable заголовок.
- Если запись не похожа на встречу, `meeting` можно вернуть как null.
- Для слабых упоминаний не создавай сущности.
- `tags` возвращай без `#`.
""".strip()
    return system_prompt, user_prompt


def fallback_plan(record: dict[str, Any], raw_filename: str) -> dict[str, Any]:
    summary = str(record.get("summary", "")).strip()
    transcript = str(record.get("transcript", "")).strip()
    source_kind = "meeting" if len(record.get("speakers") or []) > 1 else "idea"
    source_title = str(record.get("name") or "Без названия").strip() or "Без названия"
    routing_context = build_record_routing_context(record)
    highlights: list[str] = []
    if summary:
        highlights.append(summary[:300].strip())
    if transcript:
        highlights.append(transcript[:300].strip())
    if source_kind == "meeting":
        meeting = {
            "title": source_title,
            "summary": summary or transcript[:500] or "Запись из Plaud без AI-summary.",
            "folder": routing_context.get("suggested_folders_by_type", {}).get("meeting"),
            "participants": [str(speaker).strip() for speaker in (record.get("speakers") or []) if str(speaker).strip()],
            "projects": [],
            "ideas": [],
            "concepts": [],
            "decisions": [],
            "tasks": [],
            "highlights": highlights[:4],
            "tags": ["plaud", "meeting"],
        }
        return {
            "source_kind": "meeting",
            "meeting": meeting,
            "people": [],
            "projects": [],
            "ideas": [],
            "concepts": [],
            "meta": {
                "used_fallback": True,
                "reason": "LLM unavailable or invalid response",
                "generated_at": utc_now_iso(),
                "raw_filename": raw_filename,
            },
        }
    idea = {
        "title": source_title,
        "existing_title": None,
        "folder": routing_context.get("suggested_folders_by_type", {}).get("idea"),
        "summary": summary or transcript[:500] or "Голосовая заметка из Plaud.",
        "details": highlights[:4],
        "related_titles": [],
        "tags": ["plaud", "idea"],
    }
    return {
        "source_kind": "idea",
        "meeting": None,
        "people": [],
        "projects": [],
        "ideas": [idea],
        "concepts": [],
        "meta": {
            "used_fallback": True,
            "reason": "LLM unavailable or invalid response",
            "generated_at": utc_now_iso(),
            "raw_filename": raw_filename,
        },
    }


def _normalize_note_items(
    items: list[dict[str, Any]] | None,
    *,
    default_type: str,
) -> list[dict[str, Any]]:
    normalized: list[dict[str, Any]] = []
    for item in items or []:
        title = str(item.get("existing_title") or item.get("title") or "").strip()
        if not title:
            continue
        normalized.append(
            {
                "title": str(item.get("title") or title).strip() or title,
                "existing_title": str(item.get("existing_title") or "").strip() or None,
                "folder": str(item.get("folder") or "").strip() or None,
                "summary": str(item.get("summary", "")).strip(),
                "role": str(item.get("role", "")).strip(),
                "status": str(item.get("status", "")).strip(),
                "facts": [str(value).strip() for value in item.get("facts", []) if str(value).strip()],
                "details": [str(value).strip() for value in item.get("details", []) if str(value).strip()],
                "related_titles": [str(value).strip() for value in item.get("related_titles", []) if str(value).strip()],
                "tags": clean_tags(item.get("tags"), fallback=["plaud", default_type]),
                "type": default_type,
            }
        )
    return normalized


def validate_plan(plan: dict[str, Any], record: dict[str, Any], raw_filename: str) -> dict[str, Any]:
    source_kind = str(plan.get("source_kind") or "mixed").strip() or "mixed"
    meeting = plan.get("meeting")
    meeting_normalized: dict[str, Any] | None = None
    if isinstance(meeting, dict) and str(meeting.get("title", "")).strip():
        meeting_normalized = {
            "title": str(meeting.get("title")).strip(),
            "summary": str(meeting.get("summary", "")).strip(),
            "folder": str(meeting.get("folder") or "").strip() or None,
            "participants": [str(value).strip() for value in meeting.get("participants", []) if str(value).strip()],
            "projects": [str(value).strip() for value in meeting.get("projects", []) if str(value).strip()],
            "ideas": [str(value).strip() for value in meeting.get("ideas", []) if str(value).strip()],
            "concepts": [str(value).strip() for value in meeting.get("concepts", []) if str(value).strip()],
            "decisions": [str(value).strip() for value in meeting.get("decisions", []) if str(value).strip()],
            "tasks": [str(value).strip() for value in meeting.get("tasks", []) if str(value).strip()],
            "highlights": [str(value).strip() for value in meeting.get("highlights", []) if str(value).strip()],
            "tags": clean_tags(meeting.get("tags"), fallback=["plaud", "meeting"]),
        }

    people = _normalize_note_items(plan.get("people"), default_type="person")
    projects = _normalize_note_items(plan.get("projects"), default_type="project")
    ideas = _normalize_note_items(plan.get("ideas"), default_type="idea")
    concepts = _normalize_note_items(plan.get("concepts"), default_type="concept")

    if not meeting_normalized and not any([people, projects, ideas, concepts]):
        return fallback_plan(record, raw_filename)

    return {
        "source_kind": source_kind,
        "meeting": meeting_normalized,
        "people": people,
        "projects": projects,
        "ideas": ideas,
        "concepts": concepts,
        "meta": {
            "used_fallback": bool(plan.get("meta", {}).get("used_fallback", False)),
            "generated_at": utc_now_iso(),
            "raw_filename": raw_filename,
            "source_link": raw_source_link(raw_filename),
            "source_title": str(record.get("name") or "").strip(),
            "source_date": normalize_date(record.get("date") or record.get("create_time")),
            "file_id": record.get("plaud", {}).get("file_id"),
            "routing": build_record_routing_context(record),
        },
    }


def process_raw_file(raw_path: Path) -> tuple[dict[str, Any], Path]:
    load_dotenv()
    record = load_record(raw_path)
    raw_filename = raw_path.name
    existing_context = build_ingest_context(record)
    system_prompt, user_prompt = build_prompt(record, raw_filename=raw_filename, existing_context=existing_context)
    try:
        plan = chat_json(system_prompt=system_prompt, user_prompt=user_prompt)
    except (LLMError, RuntimeError) as exc:
        print(f"Warning: LLM planning failed, using fallback plan. Reason: {exc}", file=sys.stderr)
        plan = fallback_plan(record, raw_filename=raw_filename)
    validated = validate_plan(plan, record=record, raw_filename=raw_filename)
    plan_path = STATE_DIR / "plans" / f"{raw_path.stem}.plan.json"
    write_json(plan_path, validated)
    return validated, plan_path


def build_ingest_bundle(raw_path: Path) -> dict[str, Any]:
    load_dotenv()
    record = load_record(raw_path)
    raw_filename = raw_path.name
    existing_context = build_ingest_context(record)
    system_prompt, user_prompt = build_prompt(record, raw_filename=raw_filename, existing_context=existing_context)
    return {
        "raw_file": str(raw_path),
        "raw_filename": raw_filename,
        "record": record,
        "existing_context": existing_context,
        "system_prompt": system_prompt,
        "user_prompt": user_prompt,
    }


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Build an ingest plan for one Plaud raw json")
    parser.add_argument("raw_file", type=Path)
    parser.add_argument("--print-plan", action="store_true")
    return parser


def main() -> int:
    parser = build_parser()
    args = parser.parse_args()
    plan, plan_path = process_raw_file(args.raw_file)
    print(plan_path)
    if args.print_plan:
        import json

        print(json.dumps(plan, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
