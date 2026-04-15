# 🧠 Контекст проекта Plaud2Obsidian

## Что это и зачем

`Plaud2Obsidian` — персональная база знаний по паттерну Karpathy `llm-wiki`.
Источник данных — записи и транскрипции из `Plaud`.
Цель — автоматизировать путь:

`Plaud -> raw source -> reasoning/atomization -> Obsidian-ready notes`

Система должна не сваливать всё в одну кучу, а понимать контекст записи и раскладывать знания по структуре базы.

---

## Текущее состояние

Сейчас в репозитории уже собран локальный рабочий MVP:

- `scripts/fetch_plaud.py` забирает готовые записи из Plaud
- `scripts/fetch_plaud.py` использует `PLAUD_TOKEN` и `PLAUD_API_DOMAIN` из `.env`
- `scripts/fetch_plaud.py` тянет не только записи и detail, но и `filetag` / folder metadata
- `scripts/process_plaud.py` строит ingest-plan под правила из `AGENTS.md`
- `scripts/write_wiki.py` создаёт и обновляет заметки в `vault/`
- `scripts/openclaw_router.py` даёт OpenClaw единый JSON-интерфейс
- `plaud_client.py` работает как вспомогательный Plaud metadata skill для OpenClaw
- `bin/openclaw_*.sh` уже дают готовые entrypoint-ы для VPS/OpenClaw
- `deploy/` уже содержит server-side инструкции и system prompt для OpenClaw
- `index.md` и `log.md` поддерживаются автоматически
- `.state/processed.json` хранит реестр уже обработанных источников

Важно: `ObsidianDataWeave` в текущую runtime-цепочку не встроен. Он был проанализирован как архитектурный референс, но текущая реализация написана отдельно под этот проект.
Важно: upstream `plaud-unofficial` skill не используется "как есть". Он уже адаптирован локально под этот репозиторий и используется как вспомогательный metadata-layer, а не как основной ingest engine.

---

## Текущая структура проекта

```text
Plaud2Obsidian/
├── AGENTS.md
├── CONTEXT.md
├── index.md
├── log.md
├── raw/                 # READONLY для агента: канонические raw JSON из Plaud
├── config/
│   └── plaud_folder_map.yaml
├── vault/               # текущий generated layer для Obsidian
│   ├── people/
│   ├── projects/
│   ├── ideas/
│   ├── concepts/
│   ├── meetings/
│   ├── synthesis/
│   ├── inbox/
│   └── domains/
├── scripts/
│   ├── fetch_plaud.py
│   ├── process_plaud.py
│   ├── write_wiki.py
│   ├── run_ingest.py
│   ├── openclaw_router.py
│   ├── wiki_context.py
│   ├── query_wiki.py
│   └── lint_wiki.py
├── prompts/
├── bin/
│   ├── openclaw_ingest_context.sh
│   ├── openclaw_apply_plan.sh
│   ├── openclaw_status.sh
│   ├── openclaw_query.sh
│   └── openclaw_lint.sh
├── plaud_client.py      # auxiliary Plaud metadata skill / CLI
├── SKILL.md
├── README_PLAUD.md
├── PLAUD_API.md
├── deploy/
├── wiki/                # legacy-слой совместимости, не основной write-target
└── .state/
```

Правило текущей версии:

- `raw/` — только читать, не редактировать вручную
- `vault/` — текущий write-target
- `wiki/` — legacy-структура совместимости; новые записи пишутся не туда
- `index.md` — карта базы
- `log.md` — append-only журнал действий

Примечание: в коде сохранены некоторые legacy-названия модулей вроде `write_wiki.py` и `query_wiki.py`, но текущий write-target уже `vault/`.

---

## Как работает пайплайн сейчас

### Шаг 1 — Получение данных из Plaud

Доступ идёт через неофициальный API по bearer-токену из браузерной сессии Plaud:

- `GET {PLAUD_API_DOMAIN}/file/simple/web`
- `GET {PLAUD_API_DOMAIN}/file/detail/{file_id}`
- `GET {PLAUD_API_DOMAIN}/filetag/`

Текущая схема аутентификации не менялась:

- на сервере в `.env` лежит `PLAUD_TOKEN=bearer ...`
- там же лежит `PLAUD_API_DOMAIN=...`
- все запросы к Plaud идут через bearer token, как в статье Пименова про неофициальный личный API

Текущая реализация уже умеет:

- получать список записей
- вытягивать detail по `file_id`
- вытягивать `filetag` / папки Plaud
- обрабатывать redirect domain от Plaud
- разбирать `content_list -> data_link`
- скачивать presigned payload
- распаковывать `.json.gz`, если transcript/summary лежат не inline

Канонический raw-формат сейчас — `raw/*.json`, а не `.md`.

### Шаг 2 — Построение ingest-plan

`scripts/process_plaud.py`:

- читает один raw JSON
- подмешивает контекст из `AGENTS.md`, `CONTEXT.md`, `index.md`
- подмешивает routing context из `config/plaud_folder_map.yaml`
- подмешивает `plaud_tag_names` и suggested folders
- добавляет релевантные существующие заметки из `vault/`
- просит LLM вернуть строго JSON-план
- при недоступном LLM делает fallback-план

Схема плана рассчитана на:

- `meeting`
- `person`
- `project`
- `idea`
- `concept`

### Шаг 3 — Детерминированная запись в базу

`scripts/write_wiki.py`:

- пишет новые или обновляет существующие заметки
- раскладывает их по `vault/people`, `vault/projects`, `vault/ideas`, `vault/concepts`, `vault/meetings`
- умеет писать в доменные папки вроде `vault/domains/<домен>/...`, если это пришло в ingest-plan
- обновляет `index.md`
- дописывает `log.md`
- отмечает source как обработанный в `.state/processed.json`

### Шаг 4 — OpenClaw-ready orchestration

`scripts/openclaw_router.py` предоставляет единый интерфейс для агента:

- `status`
- `ingest`
- `ingest-context`
- `apply-plan`
- `query`
- `lint`

Это позволяет использовать два режима:

- self-contained ingest: repo сам строит plan и сам применяет его
- brain-mode: OpenClaw получает полный ingest-context, сам строит plan и отдаёт его обратно на `apply-plan`

Рекомендованный целевой режим для сервера:

- `Plaud -> VPS via bearer token`
- `OpenClaw -> reasoning over ingest-context`
- `Plaud2Obsidian -> deterministic write into vault/`

Для этого уже добавлены shell entrypoint-ы:

- `bin/openclaw_ingest_context.sh`
- `bin/openclaw_apply_plan.sh`
- `bin/openclaw_status.sh`
- `bin/openclaw_query.sh`
- `bin/openclaw_lint.sh`

---

## Роль OpenClaw

Текущая правильная модель такая:

- `Plaud2Obsidian` = memory + execution layer
- `OpenClaw` = reasoning + orchestration layer

OpenClaw не должен быть Obsidian plugin.
Obsidian не требует отдельного логина для этой схемы.
Достаточно, чтобы Obsidian открыл папку этого репозитория как vault, либо локальную git-копию этого репозитория.

То есть рабочая модель такая:

- `Plaud` = источник данных
- `VPS` = место, где живёт репозиторий и исполняется pipeline
- `OpenClaw` = мозг, который решает routing и структуру итоговых заметок
- `Obsidian Desktop` = клиент, который открывает локальную копию vault
- `Obsidian Web` напрямую не участвует в ingest-цепочке, если отдельно не настраивать sync-слой

На текущем этапе OpenClaw нужен не для простого переноса текста, а чтобы решать:

- что это за запись по типу
- какие сущности создать
- какие существующие заметки обновить
- как назвать заметки
- как связать их между собой

---

## Инструменты и роли

| Инструмент | Роль |
|------------|------|
| `Plaud API` | Источник записей, transcript metadata и summary |
| `scripts/fetch_plaud.py` | Выгрузка канонических raw JSON |
| `config/plaud_folder_map.yaml` | Mapping `Plaud folder/tag -> vault folder` |
| `scripts/process_plaud.py` | Построение ingest-plan |
| `scripts/write_wiki.py` | Детерминированная запись в базу |
| `scripts/openclaw_router.py` | JSON-interface для OpenClaw |
| `plaud_client.py` | Auxiliary Plaud metadata skill / CLI для OpenClaw |
| `bin/openclaw_*.sh` | Готовые entrypoint-ы для VPS/OpenClaw |
| `OpenClaw` | Brain/orchestrator, особенно в `ingest-context -> apply-plan` |
| `Codex CLI` / OpenAI-compatible backend | LLM backend для self-contained planning, если OpenClaw не строит plan сам |
| `DeepWiki MCP` | Анализ внешних репозиториев и reference-исследование |
| `Obsidian` | Клиент для просмотра и работы с файлами vault |

---

## Что уже сделано

- [x] Реальный `fetch_plaud.py` с рабочими endpoint-ами Plaud
- [x] Bearer token flow из `.env` для серверного Plaud-доступа
- [x] Канонический raw JSON pipeline
- [x] Поддержка `filetag` / папок Plaud
- [x] Локальный ingest `fetch -> process -> write`
- [x] Автообновление `index.md` и `log.md`
- [x] `.state/processed.json` для idempotency
- [x] `openclaw_router.py` для серверной интеграции
- [x] `status/query/lint` как отдельные операции
- [x] `ingest-context -> apply-plan` как brain-mode для OpenClaw
- [x] Базовый routing через `config/plaud_folder_map.yaml`
- [x] Адаптация `plaud-unofficial` в виде вспомогательного skill layer (`plaud_client.py`, `SKILL.md`, `README_PLAUD.md`, `PLAUD_API.md`)
- [x] `deploy/` и `bin/` для VPS/OpenClaw запуска
- [x] Серверный bearer-token flow без перехода на OAuth или официальный Plaud API

---

## Что ещё не сделано

Следующий слой работ:

- [ ] Довести mapping `Plaud folder/tag -> target folder` под ваши реальные папки
- [ ] Дать OpenClaw управляемое создание новых разделов, а не только работу по фиксированным папкам
- [ ] Добавить более строгую policy для autocreation новых папок
- [ ] Усилить `query` и `lint` до полного соответствия `AGENTS.md`
- [ ] Добавить git sync layer для серверного режима
- [ ] Довести серверный operational prompt OpenClaw до production-вида

---

## Режимы работы

### Ingest

Команда уровня:

`"Обработай новую запись"`

Поток:

1. получить raw из Plaud или взять существующий raw JSON
2. собрать ingest-context
3. построить plan
4. применить plan
5. обновить `vault/`, `index.md`, `log.md`

Боевой серверный вариант для этой фазы:

1. `OpenClaw` или оператор вызывает `openclaw_ingest_context.sh`
2. `OpenClaw` читает `system_prompt` и `user_prompt`
3. `OpenClaw` возвращает валидный `plan.json`
4. `openclaw_apply_plan.sh` применяет план к `vault/`

### Query

Команда уровня:

`"Что обсуждалось с Алексом?"`

Текущая реализация:

- ищет релевантные заметки в `vault/`
- возвращает structured context для OpenClaw
- пока не является полноценным answer-engine с цитатами из `raw/`

### Lint

Команда уровня:

`"Проведи уборку"`

Текущая реализация:

- считает inventory
- ищет orphan notes
- ищет notes missing in index
- ищет unresolved wikilinks
- ищет merge candidates
- пока не покрывает весь набор проверок из `AGENTS.md`

---

## Ключевое ограничение текущей версии

Система уже умеет автоматически забирать записи Plaud по bearer-token flow, строить ingest-context для OpenClaw и писать структурированные заметки в `vault/`.

Главное незавершённое место сейчас — не Plaud-доступ и не базовый ingest, а policy-layer вокруг routing:

- точнее использовать Plaud folders/tags как сильный сигнал, а не только подсказку
- различать домены и разделы без лишнего размножения папок
- безопасно создавать новые папки только при достаточной уверенности
- усилить query/lint так, чтобы они действительно соответствовали конституции из `AGENTS.md`

То есть следующая цель — не переписывать bearer-flow или fetch-слой, а сделать brain-layer стабильнее и строже в правилах маршрутизации.
