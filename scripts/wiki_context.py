from __future__ import annotations

import difflib
import re
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

from common import ROOT_DIR, WIKI_DIR, normalize_title_key, parse_frontmatter


TOKEN_RE = re.compile(r"[A-Za-zА-Яа-яЁё0-9][A-Za-zА-Яа-яЁё0-9_-]{2,}")
WIKILINK_RE = re.compile(r"\[\[([^\]|]+)(?:\|[^\]]+)?\]\]")
NOTE_TYPE_BY_FOLDER = {
    "people": "person",
    "projects": "project",
    "ideas": "idea",
    "meetings": "meeting",
    "synthesis": "synthesis",
}


@dataclass
class WikiNote:
    title: str
    note_type: str
    path: str
    relative_path: str
    tags: list[str]
    source: str
    excerpt: str
    outgoing_links: list[str]

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def _iter_note_paths() -> list[Path]:
    if not WIKI_DIR.exists():
        return []
    return [
        path
        for path in sorted(WIKI_DIR.rglob("*.md"))
        if not path.name.startswith(".")
    ]


def _summarize_body(body: str, max_chars: int = 320) -> str:
    pieces: list[str] = []
    for line in body.splitlines():
        stripped = line.strip()
        if not stripped:
            continue
        if stripped.startswith("#"):
            continue
        if stripped.startswith("- "):
            stripped = stripped[2:].strip()
        pieces.append(stripped)
        if len(" ".join(pieces)) >= max_chars:
            break
    summary = " ".join(pieces).strip()
    if len(summary) > max_chars:
        summary = summary[:max_chars].rstrip() + "..."
    return summary


def extract_wikilink_targets(text: str) -> list[str]:
    targets: list[str] = []
    seen: set[str] = set()
    for raw_target in WIKILINK_RE.findall(text):
        target = raw_target.strip()
        if not target:
            continue
        key = normalize_title_key(target.split("/")[-1])
        if key in seen:
            continue
        seen.add(key)
        targets.append(target)
    return targets


def load_note_summary(path: Path) -> WikiNote:
    frontmatter, body = parse_frontmatter(path.read_text(encoding="utf-8"))
    folder_name = path.parent.name
    note_type = str(frontmatter.get("type") or NOTE_TYPE_BY_FOLDER.get(folder_name, "idea")).strip() or "idea"
    return WikiNote(
        title=path.stem,
        note_type=note_type,
        path=str(path),
        relative_path=str(path.relative_to(ROOT_DIR)),
        tags=[str(tag) for tag in frontmatter.get("tags", []) if str(tag).strip()],
        source=str(frontmatter.get("source", "")).strip(),
        excerpt=_summarize_body(body),
        outgoing_links=extract_wikilink_targets(body),
    )


def list_wiki_notes() -> list[WikiNote]:
    return [load_note_summary(path) for path in _iter_note_paths()]


def inventory_summary() -> dict[str, Any]:
    notes = list_wiki_notes()
    by_type: dict[str, list[str]] = {}
    for note in notes:
        by_type.setdefault(note.note_type, []).append(note.title)
    counts = {note_type: len(titles) for note_type, titles in sorted(by_type.items())}
    samples = {note_type: sorted(titles)[:8] for note_type, titles in sorted(by_type.items())}
    return {
        "counts": counts,
        "samples": samples,
        "total_notes": len(notes),
    }


def _tokenize(text: str) -> list[str]:
    return [token.casefold() for token in TOKEN_RE.findall(text or "")]


def _score_note(note: WikiNote, query: str, query_tokens: list[str]) -> float:
    haystack_title = note.title.casefold()
    haystack_excerpt = note.excerpt.casefold()
    haystack_tags = " ".join(note.tags).casefold()
    score = 0.0
    lowered_query = query.casefold().strip()
    if lowered_query and lowered_query in haystack_title:
        score += 15.0
    for token in query_tokens:
        if token in haystack_title:
            score += 6.0
        if token in haystack_excerpt:
            score += 2.0
        if token in haystack_tags:
            score += 1.5
    score += difflib.SequenceMatcher(None, lowered_query, haystack_title).ratio() * 4.0
    return score


def search_notes(query: str, limit: int = 8, note_types: list[str] | None = None) -> list[WikiNote]:
    notes = list_wiki_notes()
    allowed = set(note_types or [])
    query_tokens = _tokenize(query)
    ranked: list[tuple[float, WikiNote]] = []
    for note in notes:
        if allowed and note.note_type not in allowed:
            continue
        score = _score_note(note, query=query, query_tokens=query_tokens)
        if score <= 0:
            continue
        ranked.append((score, note))
    ranked.sort(key=lambda item: item[0], reverse=True)
    return [note for _, note in ranked[:limit]]


def build_ingest_context(record: dict[str, Any], limit: int = 8) -> dict[str, Any]:
    query_parts = [
        str(record.get("name") or ""),
        str(record.get("summary") or ""),
        " ".join(str(speaker) for speaker in (record.get("speakers") or [])),
        str(record.get("transcript") or "")[:4000],
    ]
    query = "\n".join(part for part in query_parts if part).strip()
    relevant_notes = search_notes(query, limit=limit)
    return {
        "inventory": inventory_summary(),
        "relevant_notes": [note.to_dict() for note in relevant_notes],
    }


def render_note_context_block(notes: list[dict[str, Any]]) -> str:
    if not notes:
        return "(no relevant existing notes found)"
    blocks: list[str] = []
    for note in notes:
        blocks.append(
            "\n".join(
                [
                    f"- title: {note['title']}",
                    f"  type: {note['note_type']}",
                    f"  path: {note['relative_path']}",
                    f"  tags: {note.get('tags', [])}",
                    f"  source: {note.get('source', '')}",
                    f"  excerpt: {note.get('excerpt', '')}",
                ]
            )
        )
    return "\n".join(blocks)


def recent_log_entries(limit: int = 5) -> list[str]:
    log_path = ROOT_DIR / "log.md"
    if not log_path.exists():
        return []
    entries = [line.strip() for line in log_path.read_text(encoding="utf-8").splitlines() if line.startswith("## [")]
    return entries[-limit:]


def audit_vault() -> dict[str, Any]:
    notes = list_wiki_notes()
    title_map = {normalize_title_key(note.title): note for note in notes}
    index_text = (ROOT_DIR / "index.md").read_text(encoding="utf-8") if (ROOT_DIR / "index.md").exists() else ""

    incoming_counts = {normalize_title_key(note.title): 0 for note in notes}
    unresolved_links: list[dict[str, str]] = []

    for note in notes:
        for target in note.outgoing_links:
            target_key = normalize_title_key(target.split("/")[-1])
            if target_key in incoming_counts:
                incoming_counts[target_key] += 1
            elif not target.startswith("raw/"):
                unresolved_links.append({"from": note.title, "target": target})

    notes_missing_in_index = [
        {
            "title": note.title,
            "path": note.relative_path,
            "note_type": note.note_type,
        }
        for note in notes
        if f"[[{note.relative_path[:-3]}]]" not in index_text
    ]

    orphans = [
        {
            "title": note.title,
            "path": note.relative_path,
            "note_type": note.note_type,
        }
        for note in notes
        if incoming_counts.get(normalize_title_key(note.title), 0) == 0
    ]

    merge_candidates: list[dict[str, Any]] = []
    for index, left in enumerate(notes):
        left_key = normalize_title_key(left.title)
        for right in notes[index + 1 :]:
            if left.note_type != right.note_type:
                continue
            ratio = difflib.SequenceMatcher(None, left_key, normalize_title_key(right.title)).ratio()
            if ratio >= 0.82:
                merge_candidates.append(
                    {
                        "left": left.title,
                        "right": right.title,
                        "note_type": left.note_type,
                        "similarity": round(ratio, 3),
                    }
                )

    return {
        "inventory": inventory_summary(),
        "notes_missing_in_index": notes_missing_in_index,
        "orphans": orphans,
        "unresolved_wikilinks": unresolved_links,
        "merge_candidates": merge_candidates,
        "recent_log_entries": recent_log_entries(),
    }

