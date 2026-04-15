---
name: plaud-api
description: Auxiliary Plaud metadata skill for Plaud2Obsidian and OpenClaw - use it to inspect Plaud folders/tags, normalize metadata, and produce routing hints
aliases:
  - plaud
  - plaud-recordings
  - plaud-metadata
---

# Plaud API Skill

Этот skill больше не рассматривается как основной ingest engine.
Его роль в этом репозитории:

- вытащить метаданные Plaud
- получить `filetag` / folder information
- дать OpenClaw нормализованный routing context
- не дублировать основной pipeline `scripts/fetch_plaud.py -> process_plaud.py -> write_wiki.py`

## Что важно

Используйте `plaud_client.py` из этого репозитория как вспомогательный CLI для metadata и routing hints.

Он уже опирается на текущую реализацию `Plaud2Obsidian`, а не на старое предположение, что transcript всегда лежит прямо в `.data.trans_result`, а summary — прямо в `.data.ai_content`.

Поддерживаются оба сценария:

- embedded response fields
- `content_list -> data_link -> .json.gz`

## Когда использовать этот skill

Используйте его, если нужно:

- посмотреть список записей Plaud
- получить `filetag` / папки Plaud
- нормализовать metadata по одному `file_id`
- дать OpenClaw routing hints до построения ingest-plan

Не используйте его как замену основному ingest pipeline.

## Настройка

Создайте `.env` рядом с этим skill:

```env
PLAUD_TOKEN=bearer eyJ...
PLAUD_API_DOMAIN=https://api-euc1.plaud.ai
```

## Основные команды

```bash
python3 plaud_client.py list
python3 plaud_client.py list --json
python3 plaud_client.py tags
python3 plaud_client.py details <file_id>
python3 plaud_client.py metadata <file_id>
python3 plaud_client.py route-context <file_id>
```

## Что делать вместо старого flow

Старый наивный flow:

- взять `details`
- читать `.data.trans_result`
- читать `.data.ai_content`

Новый правильный flow:

1. `python3 plaud_client.py list`
2. `python3 plaud_client.py tags`
3. `python3 plaud_client.py metadata <file_id>`
4. `python3 plaud_client.py route-context <file_id>`
5. передать это в основной `Plaud2Obsidian` / OpenClaw brain-mode

## Связь с Plaud2Obsidian

Основная боевая цепочка остаётся такой:

- `scripts/fetch_plaud.py` — fetch raw JSON
- `scripts/process_plaud.py` — build ingest plan
- `scripts/write_wiki.py` — write to `vault/`
- `scripts/openclaw_router.py` — brain/execution interface для OpenClaw

Этот skill нужен только как вспомогательный слой для Plaud-specific metadata.
