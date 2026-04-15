from __future__ import annotations

import json
import os
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import yaml


ROOT_DIR = Path(__file__).resolve().parents[1]
RAW_DIR = ROOT_DIR / "raw"
WIKI_DIR = ROOT_DIR / "wiki"
VAULT_DIR = ROOT_DIR / "vault"
CONFIG_DIR = ROOT_DIR / "config"
STATE_DIR = ROOT_DIR / ".state"
PROMPTS_DIR = ROOT_DIR / "prompts"

INVALID_FILENAME_CHARS = re.compile(r'[\\/:*?"<>|]+')
FRONTMATTER_RE = re.compile(r"^---\n(.*?)\n---\n?", re.DOTALL)


def ensure_dir(path: Path) -> Path:
    path.mkdir(parents=True, exist_ok=True)
    return path


def read_json(path: Path, default: Any | None = None) -> Any:
    if not path.exists():
        return default
    return json.loads(path.read_text(encoding="utf-8"))


def write_json(path: Path, data: Any) -> None:
    ensure_dir(path.parent)
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def utc_now_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def local_today() -> str:
    return datetime.now().strftime("%Y-%m-%d")


def sanitize_filename(value: str, max_length: int = 180) -> str:
    cleaned = INVALID_FILENAME_CHARS.sub("-", (value or "").strip())
    cleaned = re.sub(r"\s+", " ", cleaned).strip(" .")
    if not cleaned:
        cleaned = "untitled"
    if len(cleaned) > max_length:
        cleaned = cleaned[:max_length].rstrip(" .")
    return cleaned or "untitled"


def normalize_title_key(value: str) -> str:
    return re.sub(r"\s+", " ", (value or "").strip()).casefold()


def normalize_date(value: str | None) -> str:
    if not value:
        return local_today()
    raw = value.strip()
    if not raw:
        return local_today()
    try:
        return datetime.fromisoformat(raw.replace("Z", "+00:00")).strftime("%Y-%m-%d")
    except ValueError:
        return raw[:10]


def seconds_to_timestamp(value: int | float | None) -> str:
    if value is None:
        return "00:00:00"
    total = max(int(value), 0)
    hours, remainder = divmod(total, 3600)
    minutes, seconds = divmod(remainder, 60)
    return f"{hours:02d}:{minutes:02d}:{seconds:02d}"


def clean_tags(tags: list[str] | None, fallback: list[str] | None = None) -> list[str]:
    values = tags or fallback or []
    cleaned: list[str] = []
    seen: set[str] = set()
    for item in values:
        if not item:
            continue
        tag = re.sub(r"\s+", "-", str(item).strip().lstrip("#"))
        if not tag:
            continue
        key = tag.casefold()
        if key in seen:
            continue
        seen.add(key)
        cleaned.append(tag)
    return cleaned[:8]


def dump_frontmatter(frontmatter: dict[str, Any]) -> str:
    date_value = str(frontmatter.get("date", local_today())).strip() or local_today()
    tags_value = clean_tags(frontmatter.get("tags"), fallback=["plaud"])
    source_value = str(frontmatter.get("source", "")).strip()
    type_value = str(frontmatter.get("type", "idea")).strip() or "idea"
    tags_serialized = ", ".join(tags_value)
    lines = [
        "---",
        f"date: {date_value}",
        f"tags: [{tags_serialized}]",
        f"source: {json.dumps(source_value, ensure_ascii=False)}",
        f"type: {type_value}",
        "---",
    ]
    return "\n".join(lines)


def parse_frontmatter(text: str) -> tuple[dict[str, Any], str]:
    match = FRONTMATTER_RE.match(text)
    if not match:
        return {}, text
    raw_frontmatter = match.group(1)
    data = yaml.safe_load(raw_frontmatter) or {}
    body = text[match.end() :]
    return data, body.lstrip("\n")


def render_note(frontmatter: dict[str, Any], title: str, sections: list[tuple[str, list[str] | str]]) -> str:
    rendered_sections: list[str] = [f"# {title}"]
    for heading, content in sections:
        if isinstance(content, list):
            lines = [f"- {item}" for item in content if item]
            if not lines:
                continue
            rendered_sections.append(f"## {heading}\n" + "\n".join(lines))
        else:
            value = content.strip()
            if not value:
                continue
            rendered_sections.append(f"## {heading}\n{value}")
    return dump_frontmatter(frontmatter) + "\n\n" + "\n\n".join(rendered_sections).rstrip() + "\n"


def append_unique_bullets(body: str, heading: str, items: list[str]) -> str:
    cleaned_items = [item for item in items if item]
    if not cleaned_items:
        return body
    section_header = f"## {heading}"
    missing = [item for item in cleaned_items if f"- {item}" not in body]
    if not missing:
        return body
    block = "\n".join(f"- {item}" for item in missing)
    if section_header not in body:
        body = body.rstrip() + f"\n\n{section_header}\n{block}\n"
    else:
        body = body.rstrip() + f"\n{block}\n"
    return body


def append_source_block(body: str, section_heading: str, block_heading: str, bullets: list[str]) -> str:
    cleaned_bullets = [item for item in bullets if item]
    if not cleaned_bullets:
        return body
    marker = f"### {block_heading}"
    if marker in body:
        return body
    block = marker + "\n" + "\n".join(f"- {item}" for item in cleaned_bullets)
    section_header = f"## {section_heading}"
    if section_header not in body:
        return body.rstrip() + f"\n\n{section_header}\n{block}\n"
    return body.rstrip() + "\n\n" + block + "\n"


def load_text(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def note_link(title: str) -> str:
    return f"[[{title}]]"


def wiki_source_link(raw_filename: str) -> str:
    return f"[[raw/{raw_filename}]]"


def raw_source_link(raw_filename: str) -> str:
    return wiki_source_link(raw_filename)


def scan_markdown_titles(folder: Path) -> dict[str, Path]:
    titles: dict[str, Path] = {}
    if not folder.exists():
        return titles
    for path in sorted(folder.glob("*.md")):
        if path.name.startswith("."):
            continue
        titles[normalize_title_key(path.stem)] = path
    return titles


def require_env(name: str, fallback_names: list[str] | None = None) -> str:
    candidates = [name, *(fallback_names or [])]
    for candidate in candidates:
        value = os.getenv(candidate)
        if value:
            return value
    joined = ", ".join(candidates)
    raise RuntimeError(f"Missing required environment variable: {joined}")
