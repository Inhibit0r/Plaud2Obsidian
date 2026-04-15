# Plaud Auxiliary Skill

Адаптированная версия `plaud-unofficial` для `Plaud2Obsidian`.

## Зачем она нужна

Этот слой используется не как основной ingest engine, а как:

- Plaud metadata helper
- источник `filetag` / folder metadata
- вспомогательный CLI для OpenClaw
- reference layer для routing decisions

Основной pipeline находится в `scripts/`.

## Что изменено относительно upstream идеи

- client использует текущий fetch layer проекта, а не отдельную устаревшую реализацию
- убрана зависимость от жёсткого `region -> api domain`
- используется `PLAUD_API_DOMAIN` из `.env`
- убрана ставка на то, что transcript всегда лежит прямо в `.data.trans_result`
- добавлены команды `metadata` и `route-context`
- skill ориентирован на `vault/` routing, а не на flat transcript dump

## Команды

```bash
python3 plaud_client.py list
python3 plaud_client.py tags
python3 plaud_client.py details <file_id>
python3 plaud_client.py metadata <file_id>
python3 plaud_client.py route-context <file_id>
```

## Рекомендуемое использование с OpenClaw

Если OpenClaw нужен как reasoning layer:

1. получить metadata по записи
2. получить routing context
3. сопоставить `Plaud tags -> vault folders`
4. передать запись в `scripts/openclaw_router.py ingest-context`
5. построить plan
6. применить plan через `apply-plan`

## Переменные окружения

```env
PLAUD_TOKEN=bearer eyJ...
PLAUD_API_DOMAIN=https://api-euc1.plaud.ai
```
