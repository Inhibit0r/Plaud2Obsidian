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
- `scripts/process_plaud.py` строит ingest-plan под правила из `AGENTS.md`
- `scripts/write_wiki.py` создаёт и обновляет заметки в `vault/`
- `scripts/openclaw_router.py` даёт OpenClaw единый JSON-интерфейс
- `index.md` и `log.md` поддерживаются автоматически
- `.state/processed.json` хранит реестр уже обработанных источников

Важно: `ObsidianDataWeave` в текущую runtime-цепочку не встроен. Он был проанализирован как архитектурный референс, но текущая реализация написана отдельно под этот проект.

---

## Текущая структура проекта

```text
Plaud2Obsidian/
├── AGENTS.md
├── CONTEXT.md
├── index.md
├── log.md
├── raw/                 # READONLY для агента: канонические raw JSON из Plaud
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
├── deploy/
└── .state/
```

Правило текущей версии:

- `raw/` — только читать, не редактировать вручную
- `vault/` — текущий write-target
- `index.md` — карта базы
- `log.md` — append-only журнал действий

Примечание: в коде сохранены некоторые legacy-названия модулей вроде `write_wiki.py` и `query_wiki.py`, но текущий write-target уже `vault/`.

---

## Как работает пайплайн сейчас

### Шаг 1 — Получение данных из Plaud

Доступ идёт через неофициальный API по bearer-токену из браузерной сессии Plaud:

- `GET {PLAUD_API_DOMAIN}/file/simple/web`
- `GET {PLAUD_API_DOMAIN}/file/detail/{file_id}`

Текущая реализация уже умеет:

- получать список записей
- вытягивать detail по `file_id`
- обрабатывать redirect domain от Plaud
- разбирать `content_list -> data_link`
- скачивать presigned payload
- распаковывать `.json.gz`, если transcript/summary лежат не inline

Канонический raw-формат сейчас — `raw/*.json`, а не `.md`.

### Шаг 2 — Построение ingest-plan

`scripts/process_plaud.py`:

- читает один raw JSON
- подмешивает контекст из `AGENTS.md`, `CONTEXT.md`, `index.md`
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

---

## Роль OpenClaw

Текущая правильная модель такая:

- `Plaud2Obsidian` = memory + execution layer
- `OpenClaw` = reasoning + orchestration layer

OpenClaw не должен быть Obsidian plugin.
Obsidian не требует отдельного логина для этой схемы.
Достаточно, чтобы Obsidian открыл папку этого репозитория как vault, либо локальную git-копию этого репозитория.

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
| `scripts/process_plaud.py` | Построение ingest-plan |
| `scripts/write_wiki.py` | Детерминированная запись в базу |
| `scripts/openclaw_router.py` | JSON-interface для OpenClaw |
| `OpenClaw` | Brain/orchestrator, особенно в `ingest-context -> apply-plan` |
| `Codex CLI` / OpenAI-compatible backend | LLM backend для planning |
| `DeepWiki MCP` | Анализ внешних репозиториев и reference-исследование |
| `Obsidian` | Клиент для просмотра и работы с файлами vault |

---

## Что уже сделано

- [x] Реальный `fetch_plaud.py` с рабочими endpoint-ами Plaud
- [x] Канонический raw JSON pipeline
- [x] Локальный ingest `fetch -> process -> write`
- [x] Автообновление `index.md` и `log.md`
- [x] `.state/processed.json` для idempotency
- [x] `openclaw_router.py` для серверной интеграции
- [x] `status/query/lint` как отдельные операции
- [x] `ingest-context -> apply-plan` как brain-mode для OpenClaw
- [x] `deploy/` и `bin/` для VPS/OpenClaw запуска

---

## Что ещё не сделано

Следующий слой работ:

- [x] Перевести write-target на `vault/`
- [x] Добавить базовую структуру `vault/` и `config/plaud_folder_map.yaml`
- [x] Добавить поддержку папок/тегов Plaud через `/filetag/`
- [ ] Довести mapping `Plaud folder/tag -> target folder` под ваши реальные папки
- [ ] Дать OpenClaw управляемое создание новых разделов, а не только работу по фиксированным папкам
- [ ] Усилить `query` и `lint` до полного соответствия `AGENTS.md`
- [ ] Добавить git sync layer для серверного режима
- [ ] Адаптировать внешний skill `plaud-unofficial` как вспомогательный OpenClaw skill для metadata/tags, а не как главный ingest engine

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

### Query

Команда уровня:

`"Что обсуждалось с Алексом?"`

Текущая реализация:

- ищет релевантные заметки в `vault/`
- возвращает structured context для OpenClaw

### Lint

Команда уровня:

`"Проведи уборку"`

Текущая реализация:

- считает inventory
- ищет orphan notes
- ищет notes missing in index
- ищет unresolved wikilinks
- ищет merge candidates

---

## Ключевое ограничение текущей версии

Система уже умеет автоматически обрабатывать записи Plaud и писать структурированные заметки, но routing по более богатой доменной структуре ещё не доведён до конца.

Сейчас write-target — это `vault/` с секциями и доменным routing.
Следующий этап — сделать routing умнее:

- учитывать Plaud folders/tags
- различать домены и разделы
- при необходимости создавать новые папки по правилам
- сохранить при этом deterministic writer и контроль над хаосом
