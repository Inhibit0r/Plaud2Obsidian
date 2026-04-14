# OpenClaw wrapper

Если вы хотите вызывать проект из OpenClaw, не переносите бизнес-логику в OpenClaw.

Пусть OpenClaw вызывает единый router:

```bash
cd /opt/Plaud2Obsidian
source .venv/bin/activate
python scripts/openclaw_router.py ingest --latest 1
```

Сухой прогон:

```bash
cd /opt/Plaud2Obsidian
source .venv/bin/activate
python scripts/openclaw_router.py ingest --latest 1 --dry-run
```

Контекстный поиск по базе:

```bash
cd /opt/Plaud2Obsidian
source .venv/bin/activate
python scripts/openclaw_router.py query "Что обсуждалось с Алексом?"
```

Аудит базы:

```bash
cd /opt/Plaud2Obsidian
source .venv/bin/activate
python scripts/openclaw_router.py lint
```

Статус памяти и последних операций:

```bash
cd /opt/Plaud2Obsidian
source .venv/bin/activate
python scripts/openclaw_router.py status
```

Если вы хотите, чтобы именно OpenClaw был reasoning-мозгом ingest, используйте brain-mode:

1. Получить полный контекст источника и vault:
```bash
python scripts/openclaw_router.py ingest-context --latest 1
```
2. OpenClaw на своей стороне строит JSON-план под схему из prompt.
3. Применить готовый план:
```bash
python scripts/openclaw_router.py apply-plan --raw-file raw/<file>.json --plan-file /tmp/plan.json
```

Рекомендуемая схема:

1. Plaud2Obsidian отвечает за Plaud API, обработку raw, запись в `wiki/`, `index.md`, `log.md`.
2. OpenClaw отвечает за orchestration и reasoning: когда запускать ingest, когда делать query/lint, как отвечать в Telegram.
3. Для self-contained режима OpenClaw может вызывать `ingest`.
4. Для полноценного brain-mode OpenClaw должен использовать `ingest-context -> собственное reasoning -> apply-plan`.
5. Router возвращает JSON, чтобы OpenClaw получал структурированный результат.
6. LLM backend выбирается через `.env`:
   - `LLM_BACKEND=openai_compatible`
   - `LLM_BACKEND=codex_exec`

OpenClaw должен знать три ключевых файла проекта:

- `CONTEXT.md` — стратегический контекст и архитектура
- `AGENTS.md` — ingest/query/lint contract
- `index.md` — карта памяти
