from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

SCRIPT_DIR = Path(__file__).resolve().parent
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))

from wiki_context import inventory_summary, recent_log_entries, search_notes


def query_wiki(question: str, limit: int = 8) -> dict[str, object]:
    relevant_notes = [note.to_dict() for note in search_notes(question, limit=limit)]
    context_lines: list[str] = []
    for note in relevant_notes:
        context_lines.append(
            f"- [[{note['relative_path'][:-3]}]] ({note['note_type']}): {note['excerpt']}"
        )
    return {
        "question": question,
        "inventory": inventory_summary(),
        "relevant_notes": relevant_notes,
        "context_markdown": "\n".join(context_lines),
        "recent_log_entries": recent_log_entries(),
    }


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Search the local wiki and return machine-readable context")
    parser.add_argument("question")
    parser.add_argument("--limit", type=int, default=8)
    return parser


def main() -> int:
    parser = build_parser()
    args = parser.parse_args()
    result = query_wiki(args.question, limit=args.limit)
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

