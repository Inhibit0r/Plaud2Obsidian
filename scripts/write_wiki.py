from __future__ import annotations

import argparse
import json
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any

SCRIPT_DIR = Path(__file__).resolve().parent
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))

from common import (
    ROOT_DIR,
    STATE_DIR,
    WIKI_DIR,
    append_source_block,
    append_unique_bullets,
    clean_tags,
    dump_frontmatter,
    ensure_dir,
    normalize_date,
    normalize_title_key,
    note_link,
    parse_frontmatter,
    read_json,
    render_note,
    sanitize_filename,
    write_json,
)


SECTION_PATHS = {
    "person": WIKI_DIR / "people",
    "project": WIKI_DIR / "projects",
    "idea": WIKI_DIR / "ideas",
    "concept": WIKI_DIR / "ideas",
    "meeting": WIKI_DIR / "meetings",
    "synthesis": WIKI_DIR / "synthesis",
}

INDEX_HEADERS = {
    "person": "## 👥 Люди (wiki/people/)",
    "project": "## 🚀 Проекты (wiki/projects/)",
    "idea": "## 💡 Идеи и концепты (wiki/ideas/)",
    "concept": "## 💡 Идеи и концепты (wiki/ideas/)",
    "meeting": "## 📋 Встречи (wiki/meetings/)",
    "synthesis": "## 🔍 Синтез и анализ (wiki/synthesis/)",
}


@dataclass
class WriteResult:
    created: list[str]
    updated: list[str]
    skipped: list[str]


def registry_path() -> Path:
    return STATE_DIR / "processed.json"


def load_registry() -> dict[str, Any]:
    return read_json(registry_path(), default={"schema_version": 1, "sources": {}})


def save_registry(registry: dict[str, Any]) -> None:
    write_json(registry_path(), registry)


def load_plan(path: Path) -> dict[str, Any]:
    data = read_json(path)
    if not isinstance(data, dict):
        raise RuntimeError(f"Invalid plan file: {path}")
    return data


def scan_existing_titles() -> dict[str, dict[str, Path]]:
    index: dict[str, dict[str, Path]] = {}
    for note_type, folder in SECTION_PATHS.items():
        ensure_dir(folder)
        entries: dict[str, Path] = {}
        for path in sorted(folder.glob("*.md")):
            if path.name.startswith("."):
                continue
            entries[normalize_title_key(path.stem)] = path
        index[note_type] = entries
    return index


def note_path_for(note_type: str, title: str, existing_titles: dict[str, dict[str, Path]]) -> tuple[Path, bool]:
    key = normalize_title_key(title)
    if key in existing_titles.get(note_type, {}):
        return existing_titles[note_type][key], True
    folder = SECTION_PATHS[note_type]
    filename = sanitize_filename(title) + ".md"
    return folder / filename, False


def build_frontmatter(date_value: str, source_link: str, note_type: str, tags: list[str]) -> dict[str, Any]:
    return {
        "date": normalize_date(date_value),
        "tags": clean_tags(tags, fallback=["plaud", note_type]),
        "source": source_link,
        "type": note_type,
    }


def make_meeting_markdown(plan: dict[str, Any], meeting: dict[str, Any]) -> str:
    meta = plan["meta"]
    sections = [
        ("Summary", meeting.get("summary", "")),
        ("Participants", [note_link(title) for title in meeting.get("participants", [])]),
        ("Projects", [note_link(title) for title in meeting.get("projects", [])]),
        ("Ideas", [note_link(title) for title in meeting.get("ideas", [])]),
        ("Concepts", [note_link(title) for title in meeting.get("concepts", [])]),
        ("Decisions", meeting.get("decisions", [])),
        ("Tasks", meeting.get("tasks", [])),
        ("Highlights", meeting.get("highlights", [])),
        ("Sources", [meta["source_link"]]),
    ]
    frontmatter = build_frontmatter(meta["source_date"], meta["source_link"], "meeting", meeting.get("tags", []))
    return render_note(frontmatter, meeting["title"], sections)


def make_person_markdown(plan: dict[str, Any], note: dict[str, Any], context_title: str) -> str:
    meta = plan["meta"]
    mention_heading = f"### {meta['source_date']} — {note_link(context_title)}"
    mention_lines = [mention_heading]
    mention_lines.extend(f"- {item}" for item in note.get("facts", []))
    sections = [
        ("Summary", note.get("summary", "")),
        ("Role", note.get("role", "")),
        ("Facts", note.get("facts", [])),
        ("Related", [note_link(title) for title in note.get("related_titles", [])]),
        ("Mentions", "\n".join(mention_lines)),
        ("Sources", [meta["source_link"]]),
    ]
    frontmatter = build_frontmatter(meta["source_date"], meta["source_link"], "person", note.get("tags", []))
    return render_note(frontmatter, note["title"], sections)


def make_project_markdown(plan: dict[str, Any], note: dict[str, Any], context_title: str) -> str:
    meta = plan["meta"]
    update_heading = f"### {meta['source_date']} — {note_link(context_title)}"
    update_lines = [update_heading]
    if note.get("status"):
        update_lines.append(f"- Статус: {note['status']}")
    update_lines.extend(f"- {item}" for item in note.get("facts", []))
    sections = [
        ("Overview", note.get("summary", "")),
        ("Status", note.get("status", "")),
        ("Facts", note.get("facts", [])),
        ("Related", [note_link(title) for title in note.get("related_titles", [])]),
        ("Updates", "\n".join(update_lines)),
        ("Sources", [meta["source_link"]]),
    ]
    frontmatter = build_frontmatter(meta["source_date"], meta["source_link"], "project", note.get("tags", []))
    return render_note(frontmatter, note["title"], sections)


def make_idea_markdown(plan: dict[str, Any], note: dict[str, Any], note_type: str) -> str:
    meta = plan["meta"]
    sections = [
        ("Summary", note.get("summary", "")),
        ("Details", note.get("details", [])),
        ("Related", [note_link(title) for title in note.get("related_titles", [])]),
        ("Sources", [meta["source_link"]]),
    ]
    frontmatter = build_frontmatter(meta["source_date"], meta["source_link"], note_type, note.get("tags", []))
    return render_note(frontmatter, note["title"], sections)


def merge_existing_note(
    path: Path,
    note_type: str,
    note: dict[str, Any],
    plan: dict[str, Any],
    context_title: str,
) -> str:
    existing_frontmatter, body = parse_frontmatter(path.read_text(encoding="utf-8"))
    merged_frontmatter = {
        "date": existing_frontmatter.get("date") or plan["meta"]["source_date"],
        "tags": clean_tags(
            list(existing_frontmatter.get("tags") or []) + list(note.get("tags") or []),
            fallback=["plaud", note_type],
        ),
        "source": existing_frontmatter.get("source") or plan["meta"]["source_link"],
        "type": existing_frontmatter.get("type") or note_type,
    }
    related_links = [note_link(title) for title in note.get("related_titles", [])]
    body = append_unique_bullets(body, "Related", related_links)
    body = append_unique_bullets(body, "Sources", [plan["meta"]["source_link"]])

    block_heading = f"{plan['meta']['source_date']} — {note_link(context_title)}"
    if note_type == "person":
        bullets = []
        if note.get("summary"):
            bullets.append(note["summary"])
        bullets.extend(note.get("facts", []))
        body = append_source_block(body, "Mentions", block_heading, bullets or ["Новая привязка к источнику."])
    elif note_type == "project":
        bullets = []
        if note.get("summary"):
            bullets.append(note["summary"])
        if note.get("status"):
            bullets.append(f"Статус: {note['status']}")
        bullets.extend(note.get("facts", []))
        body = append_source_block(body, "Updates", block_heading, bullets or ["Новая привязка к источнику."])
    else:
        bullets = []
        if note.get("summary"):
            bullets.append(note["summary"])
        bullets.extend(note.get("details", []))
        body = append_source_block(body, "Context Updates", block_heading, bullets or ["Новая привязка к источнику."])

    return dump_frontmatter(merged_frontmatter) + "\n\n" + body.strip() + "\n"


def ensure_index_entry(index_text: str, header: str, line: str) -> str:
    if line in index_text:
        return index_text
    header_start = index_text.find(header)
    if header_start == -1:
        return index_text.rstrip() + f"\n\n{header}\n{line}\n"
    separator = index_text.find("\n\n---", header_start)
    if separator == -1:
        separator = len(index_text)
    prefix = index_text[:separator].rstrip()
    suffix = index_text[separator:]
    return prefix + "\n" + line + "\n" + suffix


def update_index(created_or_updated: list[tuple[str, str, str]], dry_run: bool) -> None:
    index_path = ROOT_DIR / "index.md"
    index_text = index_path.read_text(encoding="utf-8")
    for note_type, title, description in created_or_updated:
        header = INDEX_HEADERS[note_type]
        folder = SECTION_PATHS[note_type].relative_to(ROOT_DIR)
        line = f"- [[{folder}/{title}]] — {description}"
        index_text = ensure_index_entry(index_text, header, line)
    if not dry_run:
        index_path.write_text(index_text, encoding="utf-8")


def update_log(plan: dict[str, Any], created: list[str], updated: list[str], dry_run: bool) -> None:
    log_path = ROOT_DIR / "log.md"
    source_title = plan["meta"]["source_title"] or plan["meta"]["raw_filename"]
    created_str = ", ".join(note_link(title) for title in created) if created else "нет"
    updated_str = ", ".join(note_link(title) for title in updated) if updated else "нет"
    block = (
        f"\n## [{plan['meta']['source_date']}] ingest | {source_title}\n"
        f"Создано: {created_str}. Обновлено: {updated_str}.\n"
    )
    if dry_run:
        return
    with log_path.open("a", encoding="utf-8") as handle:
        handle.write(block)


def apply_plan(plan: dict[str, Any], *, dry_run: bool = False, reprocess: bool = False) -> WriteResult:
    existing_titles = scan_existing_titles()
    registry = load_registry()
    sources = registry.setdefault("sources", {})
    file_id = str(plan["meta"].get("file_id") or plan["meta"]["raw_filename"])
    if file_id in sources and not reprocess:
        return WriteResult(created=[], updated=[], skipped=[file_id])

    created: list[str] = []
    updated: list[str] = []
    index_updates: list[tuple[str, str, str]] = []
    meeting_plan = plan.get("meeting") or {}
    context_title = meeting_plan.get("title") or plan["meta"]["source_title"] or plan["meta"]["raw_filename"]

    meeting = plan.get("meeting")
    if meeting:
        meeting_path, exists = note_path_for("meeting", meeting["title"], existing_titles)
        meeting_markdown = make_meeting_markdown(plan, meeting)
        if not dry_run:
            ensure_dir(meeting_path.parent)
            meeting_path.write_text(meeting_markdown, encoding="utf-8")
        if exists:
            updated.append(meeting["title"])
        else:
            created.append(meeting["title"])
            existing_titles["meeting"][normalize_title_key(meeting["title"])] = meeting_path
        index_updates.append(("meeting", meeting["title"], meeting.get("summary", "")[:140].strip() or "Запись встречи из Plaud"))

    for note_type_key, note_type in [("people", "person"), ("projects", "project"), ("ideas", "idea"), ("concepts", "concept")]:
        for note in plan.get(note_type_key, []):
            resolved_title = note.get("existing_title") or note["title"]
            path, exists = note_path_for(note_type, resolved_title, existing_titles)
            current_note = dict(note)
            current_note["title"] = resolved_title
            if exists:
                markdown = merge_existing_note(path, note_type, current_note, plan, context_title=context_title)
            else:
                if note_type == "person":
                    markdown = make_person_markdown(plan, current_note, context_title=context_title)
                elif note_type == "project":
                    markdown = make_project_markdown(plan, current_note, context_title=context_title)
                else:
                    markdown = make_idea_markdown(plan, current_note, note_type=note_type)

            if not dry_run:
                ensure_dir(path.parent)
                path.write_text(markdown, encoding="utf-8")

            if exists:
                updated.append(resolved_title)
            else:
                created.append(resolved_title)
                existing_titles[note_type][normalize_title_key(resolved_title)] = path

            summary_text = current_note.get("summary", "")[:140].strip() or "Обновлено из Plaud-источника"
            index_updates.append((note_type, resolved_title, summary_text))

    if not dry_run:
        sources[file_id] = {
            "raw_filename": plan["meta"]["raw_filename"],
            "processed_at": plan["meta"]["generated_at"],
            "source_title": plan["meta"]["source_title"],
            "source_date": plan["meta"]["source_date"],
        }
        save_registry(registry)

    update_index(index_updates, dry_run=dry_run)
    update_log(plan, created=created, updated=updated, dry_run=dry_run)
    return WriteResult(created=created, updated=updated, skipped=[])


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Apply a Plaud ingest plan to wiki/, index.md, and log.md")
    parser.add_argument("plan_file", type=Path)
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--reprocess", action="store_true")
    return parser


def main() -> int:
    parser = build_parser()
    args = parser.parse_args()
    plan = load_plan(args.plan_file)
    result = apply_plan(plan, dry_run=args.dry_run, reprocess=args.reprocess)
    print(json.dumps(result.__dict__, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
