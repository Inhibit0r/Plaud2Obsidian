# Plaud2Obsidian VPS Deploy

Ниже инструкция для Ubuntu 24.04 / Debian 12 VPS.

Цель:

- хранить репозиторий и Obsidian-базу на сервере;
- дать OpenClaw стабильные команды для `ingest`, `query`, `lint`, `status`;
- не терять контекст при переносе готовых Plaud транскрипций в Obsidian.

## 1. Какой сценарий выбрать

### Рекомендую для первого деплоя: `ingest`

Используйте:

```bash
./bin/openclaw_ingest.sh --latest 1
```

Почему:

- проще в интеграции;
- меньше moving parts;
- уже использует `CONTEXT.md`, `AGENTS.md`, `index.md` и релевантные `wiki/` заметки;
- OpenClaw остаётся управляющим мозгом по таймингу и workflow, но сам ingest-план строится внутри репозитория.

### Когда переходить на `ingest-context -> apply-plan`

Переходите на brain-mode, если хотите, чтобы OpenClaw:

- сам рассуждал над ingest-планом;
- мог объяснять пользователю, почему создаёт именно такие note entities;
- модифицировал план до применения;
- управлял более сложной оркестрацией между несколькими агентами/инструментами.

Тогда поток такой:

```bash
./bin/openclaw_ingest_context.sh --latest 1
./bin/openclaw_apply_plan.sh --raw-file raw/<file>.json --plan-file /tmp/plan.json
```

Итог:

- `ingest` = лучший старт;
- `ingest-context -> apply-plan` = лучший long-term brain-mode.

## 2. Какие пакеты поставить

Под `root` или через `sudo`:

```bash
apt update
apt install -y git curl ca-certificates python3 python3-venv python3-pip nodejs npm jq
```

Если `nodejs` в репозитории системы слишком старый, поставьте LTS из NodeSource или через `nvm`. Для `@openai/codex` нужен рабочий современный Node runtime.

Проверка:

```bash
python3 --version
npm --version
git --version
```

## 3. Как разложить repo на сервере

Рекомендованная раскладка:

```text
/opt/Plaud2Obsidian
```

Пример:

```bash
mkdir -p /opt/Plaud2Obsidian
cd /opt/Plaud2Obsidian
git clone <YOUR_REPO_URL> .
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
chmod +x bin/*.sh
```

Если запускаете не под `root`, лучше создать отдельного пользователя, например `plaud`, и отдать каталог ему:

```bash
useradd -m -s /bin/bash plaud || true
chown -R plaud:plaud /opt/Plaud2Obsidian
```

## 4. Как заполнить `.env`

Создайте файл:

```bash
cp .env.example .env
```

### Вариант A: direct API backend

Подходит, если OpenClaw не должен сам давать LLM backend, а вы используете обычный API.

```env
PLAUD_TOKEN=bearer ...
PLAUD_API_DOMAIN=https://api-euc1.plaud.ai

LLM_BACKEND=openai_compatible
LLM_API_KEY=...
LLM_BASE_URL=https://api.openai.com/v1
LLM_MODEL=gpt-4.1-mini

LLM_MAX_SOURCE_CHARS=22000
LLM_TIMEOUT_SECONDS=120
LLM_TEMPERATURE=0.2
LLM_HTTP_REFERER=
LLM_X_TITLE=Plaud2Obsidian
```

### Вариант B: `codex_exec`

Подходит, если на сервере Codex CLI залогинен и именно он будет LLM backend.

```env
PLAUD_TOKEN=bearer ...
PLAUD_API_DOMAIN=https://api-euc1.plaud.ai

LLM_BACKEND=codex_exec
CODEX_MODEL=
CODEX_SANDBOX=read-only

LLM_MAX_SOURCE_CHARS=22000
LLM_TIMEOUT_SECONDS=120
LLM_TEMPERATURE=0.2
LLM_HTTP_REFERER=
LLM_X_TITLE=Plaud2Obsidian
```

## 5. Как подготовить Codex backend на сервере

Если выбрали `LLM_BACKEND=codex_exec`:

```bash
npm i -g @openai/codex
codex login
```

После этого проверьте:

```bash
codex exec --skip-git-repo-check --sandbox read-only "Return exactly this JSON: {\"ok\":true}"
```

Если это работает, Python pipeline сможет использовать `codex exec` как reasoning backend.

## 6. Базовая проверка после деплоя

Из корня репозитория:

```bash
source .venv/bin/activate
python scripts/fetch_plaud.py list --limit 5
```

Потом:

```bash
./bin/openclaw_status.sh
./bin/openclaw_ingest.sh --latest 1 --dry-run
```

Если dry-run выглядит нормально:

```bash
./bin/openclaw_ingest.sh --latest 1
```

Потом проверьте:

```bash
./bin/openclaw_status.sh
./bin/openclaw_query.sh "Что обсуждалось в последней записи?"
./bin/openclaw_lint.sh
```

## 7. Как запускать через OpenClaw

OpenClaw лучше не давать прямой доступ ко внутренним python-файлам как к хаотичным командам. Дайте ему короткие стабильные shell entrypoints:

- `./bin/openclaw_status.sh`
- `./bin/openclaw_ingest.sh --latest 1`
- `./bin/openclaw_ingest.sh --latest 1 --dry-run`
- `./bin/openclaw_ingest_context.sh --latest 1`
- `./bin/openclaw_apply_plan.sh --raw-file raw/<file>.json --plan-file /tmp/plan.json`
- `./bin/openclaw_query.sh "Что обсуждалось с Алексом?"`
- `./bin/openclaw_lint.sh`

### Рекомендуемый первый режим для OpenClaw

Дайте OpenClaw такую operational схему:

1. Сначала читать:
   - `CONTEXT.md`
   - `AGENTS.md`
   - `index.md`
   - `log.md`
2. При команде “обработай новую запись” вызывать:
   `./bin/openclaw_ingest.sh --latest 1`
3. При вопросах по базе вызывать:
   `./bin/openclaw_query.sh "<question>"`
4. При уборке вызывать:
   `./bin/openclaw_lint.sh`

### Brain-mode схема для OpenClaw

Если хотите, чтобы OpenClaw сам строил ingest-план:

1. `./bin/openclaw_ingest_context.sh --latest 1`
2. OpenClaw читает JSON-context.
3. OpenClaw сам строит JSON-план.
4. `./bin/openclaw_apply_plan.sh --raw-file raw/<file>.json --plan-file /tmp/plan.json`

## 8. systemd

Если хотите периодический fallback-режим без OpenClaw, можно включить timer:

```bash
cp deploy/systemd/plaud2obsidian-ingest.service /etc/systemd/system/
cp deploy/systemd/plaud2obsidian-ingest.timer /etc/systemd/system/
systemctl daemon-reload
systemctl enable --now plaud2obsidian-ingest.timer
systemctl status plaud2obsidian-ingest.timer
```

Но если OpenClaw уже сам планирует ingest, timer не обязателен.

## 9. Что лучше выбрать именно вам

С вашим текущим контекстом я рекомендую:

1. На первом серверном запуске использовать `ingest`.
2. После стабилизации переключиться на `ingest-context -> apply-plan`.

Причина:

- сейчас вам важнее быстро получить рабочий end-to-end pipeline;
- `ingest` уже сохраняет контекст и не рвёт Obsidian-структуру;
- после первого боевого цикла уже можно спокойно усиливать роль OpenClaw как reasoning-мозга без риска сломать базовую механику.

## 10. Минимальный запуск, если нужно просто завести систему

```bash
cd /opt/Plaud2Obsidian
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env
npm i -g @openai/codex
codex login
chmod +x bin/*.sh
./bin/openclaw_ingest.sh --latest 1 --dry-run
./bin/openclaw_ingest.sh --latest 1
```

