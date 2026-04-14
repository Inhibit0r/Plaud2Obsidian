from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

SCRIPT_DIR = Path(__file__).resolve().parent
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))

from wiki_context import audit_vault


def build_parser() -> argparse.ArgumentParser:
    return argparse.ArgumentParser(description="Audit the local wiki for index gaps, orphans, and link issues")


def main() -> int:
    parser = build_parser()
    parser.parse_args()
    result = audit_vault()
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

