# Plaud2Obsidian

Локальный MVP-пайплайн:

1. Забирает готовые транскрипции из Plaud в `raw/`.
2. Строит план атомизации под правила из `AGENTS.md`.
3. Создаёт и обновляет заметки в `vault/`.
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
- `vault/**/*.md` — итоговые заметки
- `config/plaud_folder_map.yaml` — mapping Plaud tags/folders -> vault roots

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

OpenClaw в такой схеме становится orchestration- и reasoning-слоем. Инжест, запись в `vault/`, `index.md`, `log.md` и работа с Plaud остаются внутри этого репозитория.

## Production flow: Plaud -> VPS -> OpenClaw -> Obsidian

Рабочая production-схема сейчас такая:

- `Plaud` — источник записей и tag metadata
- `VPS` — runtime, где живёт репозиторий и исполняется pipeline
- `OpenClaw` — reasoning-слой, который строит `plan.json`
- `vault/` — итоговая knowledge base для Obsidian
- `Mac + Obsidian Desktop` — просмотр, поиск и ручная работа с заметками

### Рекомендованный серверный путь

На сервере должен быть:

- `Codex CLI` с выполненным `codex login --device-auth`
- `OpenClaw` с моделью `codex/gpt-5.4`
- `agents.defaults.workspace` pointing at repo root

Проверка smoke-test:

```bash
env -i HOME="$HOME" PATH="$PATH" TERM="${TERM:-xterm}" \
openclaw agent --agent main --local --message 'Ответь одной строкой: OK'
```

Если ответ `OK`, production-flow готов к ingest.

### Один основной ingest-командный путь

Для следующей записи больше не нужно вручную собирать контекст, prompt и apply по отдельности.
Используйте:

```bash
./bin/openclaw_ingest_next.sh --latest 1
```

Для конкретного Plaud file id:

```bash
./bin/openclaw_ingest_next.sh --file-id 2d252b44aec6a216587d0242f0e1539f
```

Для конкретного raw-файла:

```bash
./bin/openclaw_ingest_next.sh --raw-file raw/example.json
```

Для dry-run без записи в `vault/`:

```bash
./bin/openclaw_ingest_next.sh --latest 1 --dry-run
```

Если raw оказался неполным или вы обновили Plaud parsing logic, перетяните источник заново:

```bash
./bin/openclaw_ingest_next.sh --file-id <FILE_ID> --refresh-raw --reprocess
```

Для подготовки context/prompt файлов без вызова `OpenClaw`:

```bash
./bin/openclaw_ingest_next.sh --latest 1 --prepare-only
```

Этот wrapper делает весь production-цикл:

1. строит `ingest_context.json`
2. сохраняет `system_prompt.txt`, `user_prompt.txt`, `raw_file.txt` в `.state/openclaw/`
3. вызывает `openclaw agent --agent main --local`
4. валидирует `.state/openclaw/plan.json`
5. применяет `apply-plan`

### Что делать после каждого серверного ingest

На `VPS`:

```bash
git status --short
find vault -maxdepth 6 -type f | sort
sed -n '1,220p' index.md
sed -n '1,220p' log.md
```

Если результат корректный, коммитите только осмысленные project-файлы:

```bash
git add raw vault index.md log.md config/plaud_folder_map.yaml
git commit -m "ingest: <source title>"
git push
```

### Как смотреть результат в Obsidian

На `Mac`:

1. откройте локальную копию репозитория как `vault` в `Obsidian Desktop`
2. после каждого серверного ingest делайте `git pull`
3. проверяйте новые файлы в `vault/domains/...`, `vault/ideas/...`, `vault/meetings/...`

### Routing policy

`config/plaud_folder_map.yaml` — это основная policy-точка для routing.

Рекомендуемая практика:

- `people` и `projects` держать глобально
- `ideas`, `concepts`, `meetings` маршрутизировать доменно
- новые корни добавлять только для реально устойчивых папок/tag-ов Plaud

### Hygiene

Репозиторий должен хранить knowledge base и pipeline, но не runtime-мусор.

Уже должны быть игнорированы:

- `.venv/`
- `.codex/`
- `.openclaw/`
- `.env.save`
- server-local notes вроде `HEARTBEAT.md`, `IDENTITY.md`, `SOUL.md`, `TOOLS.md`, `USER.md`

`VPS` должен быть runtime-машиной, а не местом постоянного ручного редактирования всего проекта.

### Чеклист проверки

Проверьте, что рабочий контур проходит все пункты:

1. Plaud API жив:

```bash
python scripts/fetch_plaud.py list --limit 5
python plaud_client.py tags
```

2. routing работает:

```bash
python plaud_client.py route-context <FILE_ID>
```

3. OpenClaw/Codex runtime жив:

```bash
env -i HOME="$HOME" PATH="$PATH" TERM="${TERM:-xterm}" \
openclaw agent --agent main --local --message 'Ответь одной строкой: OK'
```

4. wrapper-ингест проходит:

```bash
./bin/openclaw_ingest_next.sh --latest 1
```

5. заметки появляются в `vault/`, `index.md`, `log.md`

6. тот же source при повторном запуске не плодит дубли

## Source integrity и защита от потери контекста

Raw JSON в `raw/` остаётся каноническим источником. При `apply-plan` дополнительно создаётся Markdown-копия полного источника в:

```text
vault/raw/<raw_filename>.md
```

Это нужно, чтобы Obsidian индексировал полный transcript, а не только атомарные заметки.

Важно: OpenClaw не всегда должен получать весь transcript в один prompt. По умолчанию planning prompt получает excerpt до `LLM_MAX_SOURCE_CHARS=22000`, а полный transcript сохраняется в `raw/` и `vault/raw/`.

Проверить, будет ли transcript усечён для prompt-а:

```bash
python scripts/audit_raw_integrity.py
python scripts/audit_raw_integrity.py --raw-file raw/example.json
```

JSON-вывод для автоматических проверок:

```bash
python scripts/audit_raw_integrity.py --json
```

Если видите `prompt_would_truncate=true`, это не значит, что transcript потерян. Это значит, что для reasoning нужен chunked/deep ingest режим, если вы хотите извлечь все детали из очень длинной записи.

Если audit показывает `long recording has suspiciously short transcript text` или `no transcript text`, сначала перетяните raw:

```bash
./bin/openclaw_ingest_next.sh --file-id <FILE_ID> --refresh-raw --prepare-only
python scripts/audit_raw_integrity.py --raw-file raw/<REFETCHED_FILE>.json
```

Если raw стал нормальным, запускайте reprocess:

```bash
./bin/openclaw_ingest_next.sh --file-id <FILE_ID> --refresh-raw --reprocess
```

Практические правила:

- `raw/*.json` — полный источник, не редактировать
- `vault/raw/*.md` — полный Markdown transcript для Obsidian-поиска
- `vault/ideas`, `vault/concepts`, `vault/meetings` — атомарные знания, извлечённые из источника
- если запись очень длинная и важна "от и до", используйте повышенный `LLM_MAX_SOURCE_CHARS` или отдельный chunked ingest режим

Для ручного увеличения prompt лимита на один запуск:

```bash
LLM_MAX_SOURCE_CHARS=80000 ./bin/openclaw_ingest_next.sh --file-id <FILE_ID>
```

Не ставьте слишком большой лимит по умолчанию: лучше хранить полный transcript в Obsidian и отдельно запускать deep ingest для длинных источников.

## Автосинхронизация на Mac

Базовая схема синхронизации:

```text
VPS -> git push -> GitHub -> git pull -> Mac -> Obsidian
```

Obsidian сам не забирает файлы с VPS. Он видит локальную папку. Чтобы не делать `git pull` руками, используйте один из вариантов.

### Вариант A: Obsidian Git plugin

В Obsidian установите community plugin `Obsidian Git`.

Рекомендуемые настройки:

- Pull on startup: enabled
- Auto pull interval: 5 minutes
- Auto commit: disabled, пока не нужна двусторонняя синхронизация
- Auto push: disabled, пока не нужна двусторонняя синхронизация

### Вариант B: macOS launchd auto-pull

Создайте скрипт:

```bash
mkdir -p ~/bin
cat > ~/bin/plaud2obsidian-pull.sh <<'EOF'
#!/usr/bin/env bash
set -euo pipefail
cd "/Users/a0000/Desktop/Прога/Plaud2Obsidian"
git pull --ff-only
EOF
chmod +x ~/bin/plaud2obsidian-pull.sh
```

Потом создайте `launchd` job:

```bash
mkdir -p ~/Library/LaunchAgents
cat > ~/Library/LaunchAgents/com.plaud2obsidian.pull.plist <<'EOF'
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN"
  "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
  <key>Label</key>
  <string>com.plaud2obsidian.pull</string>
  <key>ProgramArguments</key>
  <array>
    <string>/Users/a0000/bin/plaud2obsidian-pull.sh</string>
  </array>
  <key>StartInterval</key>
  <integer>300</integer>
  <key>RunAtLoad</key>
  <true/>
  <key>StandardOutPath</key>
  <string>/tmp/plaud2obsidian-pull.out</string>
  <key>StandardErrorPath</key>
  <string>/tmp/plaud2obsidian-pull.err</string>
</dict>
</plist>
EOF
launchctl load ~/Library/LaunchAgents/com.plaud2obsidian.pull.plist
```

Проверка:

```bash
launchctl list | grep plaud2obsidian
tail -50 /tmp/plaud2obsidian-pull.err
```

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
- для ingest подмешивает `CONTEXT.md`, `AGENTS.md`, `index.md`, routing config и релевантные существующие `vault/` заметки в planning prompt;
- поддерживает brain-mode: OpenClaw может сам запросить `ingest-context`, сам построить план и затем применить его через `apply-plan`;
- позволяет OpenClaw быть orchestration-мозгом, а репозиторию оставаться долговременной памятью и deterministic execution layer.

## Vault routing

Текущий write-target — `vault/`, а не `wiki/`.

Базовая структура:

- `vault/people`
- `vault/projects`
- `vault/ideas`
- `vault/concepts`
- `vault/meetings`
- `vault/synthesis`
- `vault/inbox`
- `vault/domains/*`

Plaud folder/tag metadata подтягивается через `/filetag/` и сохраняется в raw metadata. Mapping задаётся в `config/plaud_folder_map.yaml`.
