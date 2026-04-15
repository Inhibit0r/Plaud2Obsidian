# Plaud API Notes

Краткая памятка по тем endpoint-ам Plaud, которые реально важны для `Plaud2Obsidian`.

## Основные endpoint-ы

### `GET /file/simple/web`

Назначение:

- список записей
- базовые metadata поля
- `filetag_id_list` / tag references

Используется в проекте для:

- выбора последних обработанных записей
- получения `file_id`
- предварительного routing signal по тегам/папкам Plaud

### `GET /file/detail/{file_id}`

Назначение:

- detail по одной записи
- transcript metadata
- summary metadata
- ссылки на downloadable content

Важно:

ответ не всегда содержит transcript/summary inline.
Нужно учитывать два варианта:

1. transcript/summary лежат прямо в detail response
2. detail response содержит `content_list` или `pre_download_content_list`, где есть `data_link`

### `GET /filetag/`

Назначение:

- список Plaud folders / tags
- mapping `filetag_id -> human-readable name`

Используется в проекте для:

- резолва `filetag_id_list`
- передачи `plaud_tag_names` в routing context
- будущего mapping `Plaud folder -> vault folder`

### `GET /file/download/{file_id}`

Назначение:

- скачивание аудио

Для текущего routing pipeline не является критичным.

## Ключевой нюанс по transcript content

Нельзя полагаться только на:

- `.data.trans_result`
- `.data.ai_content`

В текущем проекте поддерживается более надёжная схема:

- читать `detail`
- искать `content_list`
- скачивать `data_link`
- распаковывать `.json.gz`, если нужно
- затем извлекать transcript/summary

## Как это используется в Plaud2Obsidian

### Боевой pipeline

- `scripts/fetch_plaud.py`
- `scripts/process_plaud.py`
- `scripts/write_wiki.py`
- `scripts/openclaw_router.py`

### Вспомогательный skill layer

- `plaud_client.py`
- `SKILL.md`
- `README_PLAUD.md`

Этот layer нужен для:

- metadata inspection
- `filetag` / folder analysis
- routing hints для OpenClaw

Он не должен заменять основной ingest pipeline.
