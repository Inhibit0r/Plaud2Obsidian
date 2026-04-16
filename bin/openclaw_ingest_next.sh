#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ROOT_DIR="$(cd "${SCRIPT_DIR}/.." && pwd)"

usage() {
  cat <<'EOF'
Usage:
  ./bin/openclaw_ingest_next.sh [--latest N | --file-id ID | --raw-file PATH] [--dry-run] [--prepare-only]

Examples:
  ./bin/openclaw_ingest_next.sh
  ./bin/openclaw_ingest_next.sh --latest 1
  ./bin/openclaw_ingest_next.sh --file-id 2d252b44aec6a216587d0242f0e1539f
  ./bin/openclaw_ingest_next.sh --raw-file raw/example.json --dry-run

Behavior:
  1. Builds ingest context
  2. Extracts system/user prompts into .state/openclaw/
  3. Runs OpenClaw locally via codex/* runtime to generate plan.json
  4. Validates plan.json with jq
  5. Applies the plan unless --prepare-only is used
EOF
}

MODE="latest"
MODE_VALUE="1"
DRY_RUN="0"
PREPARE_ONLY="0"

while [[ $# -gt 0 ]]; do
  case "$1" in
    --latest)
      MODE="latest"
      MODE_VALUE="${2:?Missing value for --latest}"
      shift 2
      ;;
    --file-id)
      MODE="file-id"
      MODE_VALUE="${2:?Missing value for --file-id}"
      shift 2
      ;;
    --raw-file)
      MODE="raw-file"
      MODE_VALUE="${2:?Missing value for --raw-file}"
      shift 2
      ;;
    --dry-run)
      DRY_RUN="1"
      shift
      ;;
    --prepare-only)
      PREPARE_ONLY="1"
      shift
      ;;
    -h|--help)
      usage
      exit 0
      ;;
    *)
      echo "Unknown argument: $1" >&2
      usage >&2
      exit 1
      ;;
  esac
done

cd "${ROOT_DIR}"
source .venv/bin/activate

mkdir -p .state/openclaw

CONTEXT_FILE=".state/openclaw/ingest_context.json"
PLAN_FILE=".state/openclaw/plan.json"
RAW_REF_FILE=".state/openclaw/raw_file.txt"
SYSTEM_PROMPT_FILE=".state/openclaw/system_prompt.txt"
USER_PROMPT_FILE=".state/openclaw/user_prompt.txt"

CONTEXT_ARGS=()
case "${MODE}" in
  latest)
    CONTEXT_ARGS=(--latest "${MODE_VALUE}")
    ;;
  file-id)
    CONTEXT_ARGS=(--file-id "${MODE_VALUE}")
    ;;
  raw-file)
    CONTEXT_ARGS=(--raw-file "${MODE_VALUE}")
    ;;
esac

./bin/openclaw_ingest_context.sh "${CONTEXT_ARGS[@]}" > "${CONTEXT_FILE}"

python - <<'PY'
import json
from pathlib import Path

context_path = Path(".state/openclaw/ingest_context.json")
data = json.loads(context_path.read_text(encoding="utf-8"))
sources = data.get("sources", [])
if not sources:
    raise SystemExit("ingest_context.json does not contain any sources")

src = sources[0]
raw_file = data.get("raw_file") or src["raw_file"]

Path(".state/openclaw/system_prompt.txt").write_text(src["system_prompt"], encoding="utf-8")
Path(".state/openclaw/user_prompt.txt").write_text(src["user_prompt"], encoding="utf-8")
Path(".state/openclaw/raw_file.txt").write_text(raw_file, encoding="utf-8")

print(raw_file)
PY

if [[ "${PREPARE_ONLY}" == "1" ]]; then
  echo "Prepared prompt files:"
  echo "  ${SYSTEM_PROMPT_FILE}"
  echo "  ${USER_PROMPT_FILE}"
  echo "  ${RAW_REF_FILE}"
  echo "  ${CONTEXT_FILE}"
  exit 0
fi

AGENT_MESSAGE="$(cat <<EOF
Работай в репозитории ${ROOT_DIR}.

Прочитай файлы:
- ${ROOT_DIR}/.state/openclaw/system_prompt.txt
- ${ROOT_DIR}/.state/openclaw/user_prompt.txt

Используй их как инструкции для генерации ingest-плана.
Сгенерируй только валидный JSON без пояснений, markdown и code fences.
Сохрани результат в файл:
${ROOT_DIR}/.state/openclaw/plan.json

Проверь файл командой:
jq . ${ROOT_DIR}/.state/openclaw/plan.json

Ответь только одной строкой:
SAVED ${ROOT_DIR}/.state/openclaw/plan.json

Если не удалось, ответь одной строкой:
ERROR: <краткая причина>
EOF
)"

env -i HOME="${HOME}" PATH="${PATH}" TERM="${TERM:-xterm}" \
  openclaw agent --agent main --local --message "${AGENT_MESSAGE}"

jq . "${PLAN_FILE}" >/dev/null

RAW_FILE="$(cat "${RAW_REF_FILE}")"
APPLY_ARGS=(--raw-file "${RAW_FILE}" --plan-file "${PLAN_FILE}")
if [[ "${DRY_RUN}" == "1" ]]; then
  APPLY_ARGS+=(--dry-run)
fi

./bin/openclaw_apply_plan.sh "${APPLY_ARGS[@]}"
