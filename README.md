# Plaud2Obsidian

Локальный MVP-пайплайн:

1. Забирает готовые транскрипции из Plaud в `raw/`.
2. Строит план атомизации под правила из `AGENTS.md`.
3. Создаёт и обновляет заметки в `wiki/`.
4. Обновляет `index.md` и `log.md`.

## Быстрый старт

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env
```

Заполните `.env`, затем проверьте Plaud:

```bash
python3 scripts/fetch_plaud.py list --limit 5
```

Сухой прогон последней записи:

```bash
python3 scripts/run_ingest.py --latest 1 --dry-run
```

Полный локальный прогон:

```bash
python3 scripts/run_ingest.py --latest 1
```

Если хотите обработать конкретный raw-файл без запроса к Plaud:

```bash
python3 scripts/run_ingest.py --raw-file raw/2026-04-14__Example__abc123.json
```

## Что создаётся

- `raw/*.json` — канонические выгрузки Plaud
- `.state/processed.json` — реестр уже обработанных source
- `.state/plans/*.plan.json` — сохранённые планы атомизации
- `wiki/**/*.md` — итоговые заметки

## Важные замечания

- `raw/` не редактируется вручную.
- Если LLM недоступен, пайплайн попробует создать упрощённый fallback-план из Plaud summary и транскрипта.
- Для OpenRouter укажите `LLM_BASE_URL=https://openrouter.ai/api/v1` и при необходимости заполните `LLM_HTTP_REFERER`.

## Варианты LLM backend

### 1. `openai_compatible`

Подходит для OpenAI API, OpenRouter и похожих endpoint-ов.

```env
LLM_BACKEND=openai_compatible
LLM_API_KEY=...
LLM_BASE_URL=https://api.openai.com/v1
LLM_MODEL=gpt-4.1-mini
```

### 2. `codex_exec`

Подходит, если на машине установлен Codex CLI и вы вошли в него через ChatGPT account или API key.

```env
LLM_BACKEND=codex_exec
CODEX_MODEL=
CODEX_SANDBOX=read-only
```

Подготовка машины:

```bash
npm i -g @openai/codex
codex login
```

После этого Python-пайплайн будет вызывать `codex exec` как внешний LLM-бэкенд и `LLM_API_KEY` не понадобится.

## Серверный запуск

Если вы хотите потом обернуть проект в OpenClaw, лучше не менять пайплайн. Пусть OpenClaw просто вызывает готовую команду:

```bash
cd /path/to/Plaud2Obsidian
source .venv/bin/activate
python scripts/run_ingest.py --latest 1
```

Для разового dry-run:

```bash
python scripts/run_ingest.py --latest 1 --dry-run
```

OpenClaw в такой схеме становится только orchestration-слоем. Инжест, запись в `wiki/`, `index.md`, `log.md` и работа с Plaud остаются внутри этого репозитория.

## OpenClaw-ready router

Для серверной интеграции добавлен единый router:

```bash
python scripts/openclaw_router.py status
python scripts/openclaw_router.py ingest --latest 1 --dry-run
python scripts/openclaw_router.py ingest --latest 1
python scripts/openclaw_router.py ingest-context --latest 1
python scripts/openclaw_router.py apply-plan --raw-file raw/<file>.json --plan-file /tmp/plan.json
python scripts/openclaw_router.py query "Что обсуждалось с Алексом?"
python scripts/openclaw_router.py lint
```

Этот router:

- возвращает JSON, который OpenClaw может разбирать без markdown-парсинга;
- для ingest подмешивает `CONTEXT.md`, `AGENTS.md`, `index.md` и релевантные существующие `wiki/` заметки в planning prompt;
- поддерживает brain-mode: OpenClaw может сам запросить `ingest-context`, сам построить план и затем применить его через `apply-plan`;
- позволяет OpenClaw быть orchestration-мозгом, а репозиторию оставаться долговременной памятью и deterministic execution layer.
