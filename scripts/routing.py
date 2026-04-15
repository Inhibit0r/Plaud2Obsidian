from __future__ import annotations

from pathlib import Path
from typing import Any

import yaml

from common import CONFIG_DIR, VAULT_DIR, ensure_dir


DEFAULT_ROUTING_CONFIG: dict[str, Any] = {
    "defaults": {
        "route_people_globally": True,
        "route_projects_globally": True,
        "allow_new_folders": True,
    },
    "type_folders": {
        "person": "people",
        "project": "projects",
        "idea": "ideas",
        "concept": "concepts",
        "meeting": "meetings",
        "synthesis": "synthesis",
    },
    "plaud_tag_roots": {},
}


def routing_config_path() -> Path:
    return CONFIG_DIR / "plaud_folder_map.yaml"


def load_routing_config() -> dict[str, Any]:
    path = routing_config_path()
    if not path.exists():
        return DEFAULT_ROUTING_CONFIG
    loaded = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    config = {
        "defaults": dict(DEFAULT_ROUTING_CONFIG["defaults"]),
        "type_folders": dict(DEFAULT_ROUTING_CONFIG["type_folders"]),
        "plaud_tag_roots": dict(DEFAULT_ROUTING_CONFIG["plaud_tag_roots"]),
    }
    for key in ("defaults", "type_folders", "plaud_tag_roots", "mappings"):
        value = loaded.get(key)
        if not isinstance(value, dict):
            continue
        target_key = "plaud_tag_roots" if key == "mappings" else key
        config[target_key].update(value)
    return config


def default_type_folder(note_type: str, config: dict[str, Any] | None = None) -> str:
    routing = config or load_routing_config()
    return str(routing.get("type_folders", {}).get(note_type, "inbox")).strip() or "inbox"


def _sanitize_folder_segment(segment: str) -> str:
    cleaned = "".join(char for char in segment.strip().replace("\\", "/") if char not in ':*?"<>|')
    cleaned = cleaned.strip().strip(".")
    return cleaned


def normalize_relative_folder(folder: str | None) -> str | None:
    if folder is None:
        return None
    raw = str(folder).strip().replace("\\", "/")
    if not raw:
        return None
    parts = []
    for part in raw.split("/"):
        cleaned = _sanitize_folder_segment(part)
        if not cleaned or cleaned in {".", ".."}:
            continue
        parts.append(cleaned)
    if not parts:
        return None
    return "/".join(parts)


def mapped_roots_for_tag_names(tag_names: list[str], config: dict[str, Any] | None = None) -> list[str]:
    routing = config or load_routing_config()
    mapping = routing.get("plaud_tag_roots", {})
    roots: list[str] = []
    seen: set[str] = set()
    for tag_name in tag_names:
        mapped = normalize_relative_folder(mapping.get(tag_name))
        if not mapped or mapped in seen:
            continue
        seen.add(mapped)
        roots.append(mapped)
    return roots


def suggested_folder_for_type(
    note_type: str,
    *,
    tag_names: list[str] | None = None,
    explicit_folder: str | None = None,
    config: dict[str, Any] | None = None,
) -> str:
    routing = config or load_routing_config()
    if explicit_folder:
        normalized = normalize_relative_folder(explicit_folder)
        if normalized:
            return normalized

    defaults = routing.get("defaults", {})
    type_folder = default_type_folder(note_type, routing)
    if note_type == "person" and defaults.get("route_people_globally", True):
        return type_folder
    if note_type == "project" and defaults.get("route_projects_globally", True):
        return type_folder

    mapped_roots = mapped_roots_for_tag_names(tag_names or [], routing)
    if mapped_roots:
        return f"{mapped_roots[0]}/{type_folder}"
    return type_folder


def build_record_routing_context(record: dict[str, Any], config: dict[str, Any] | None = None) -> dict[str, Any]:
    routing = config or load_routing_config()
    tag_names = [str(value).strip() for value in record.get("plaud", {}).get("filetag_names", []) if str(value).strip()]
    mapped_roots = mapped_roots_for_tag_names(tag_names, routing)
    suggested_folders = {
        note_type: suggested_folder_for_type(note_type, tag_names=tag_names, config=routing)
        for note_type in ("meeting", "person", "project", "idea", "concept", "synthesis")
    }
    return {
        "plaud_tag_names": tag_names,
        "mapped_roots": mapped_roots,
        "suggested_folders_by_type": suggested_folders,
        "allow_new_folders": bool(routing.get("defaults", {}).get("allow_new_folders", True)),
    }


def existing_folder_inventory(root: Path | None = None) -> list[str]:
    target_root = root or VAULT_DIR
    if not target_root.exists():
        return []
    folders: list[str] = []
    for path in sorted(target_root.rglob("*")):
        if not path.is_dir() or path.name.startswith("."):
            continue
        folders.append(str(path.relative_to(target_root)))
    return folders


def ensure_default_vault_layout() -> None:
    routing = load_routing_config()
    for folder in routing.get("type_folders", {}).values():
        normalized = normalize_relative_folder(folder)
        if normalized:
            ensure_dir(VAULT_DIR / normalized)
    ensure_dir(VAULT_DIR / "inbox")
    ensure_dir(VAULT_DIR / "domains")


def routing_snapshot() -> dict[str, Any]:
    routing = load_routing_config()
    return {
        "config_path": str(routing_config_path()),
        "config": routing,
        "existing_folders": existing_folder_inventory(),
    }
