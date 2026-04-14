# OpenClaw System Notes for Plaud2Obsidian

Ты управляешь репозиторием `Plaud2Obsidian` как внешним memory+execution backend.

## Что важно читать

1. `CONTEXT.md` — зачем существует проект и как устроен pipeline.
2. `AGENTS.md` — конституция ingest/query/lint.
3. `index.md` — текущая карта базы знаний.
4. `log.md` — последние действия.

## Как работать

- Для новых транскрипций не редактируй `raw/` руками.
- Для переноса новых Plaud записей вызывай:
  `python scripts/openclaw_router.py ingest --latest 1`
- Если ты сам должен быть reasoning-мозгом ingest:
  1. `python scripts/openclaw_router.py ingest-context --latest 1`
  2. сгенерируй JSON-план
  3. `python scripts/openclaw_router.py apply-plan --raw-file raw/<file>.json --plan-file /tmp/plan.json`
- Для dry-run:
  `python scripts/openclaw_router.py ingest --latest 1 --dry-run`
- Для ответов по базе вызывай:
  `python scripts/openclaw_router.py query "<вопрос>"`
- Для аудита базы вызывай:
  `python scripts/openclaw_router.py lint`
- Для общего состояния вызывай:
  `python scripts/openclaw_router.py status`

## Роли

- OpenClaw = brain/orchestrator.
- Репозиторий Plaud2Obsidian = долговременная память и deterministic actions layer.
- `openclaw_router.py` = основной интерфейс между агентом и репозиторием.
