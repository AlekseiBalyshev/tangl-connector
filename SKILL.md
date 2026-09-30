---
name: tangl-connector
description: >-
  Чтение BIM-моделей из облачной платформы Tangl: найти модель и версию,
  разобраться в составе модели, посчитать элементы и объёмы, проверить
  заполнение параметров, сравнить версии, дать ссылку на модель. Используй,
  когда пользователь упоминает Tangl, модели и версии в Tangl, просит
  посчитать или выгрузить элементы, объёмы, количества по этажам и категориям,
  проверить параметры или классификацию модели.
---

# Tangl Connector

**Версия:** v0.1.0 · 2026-09-30

Коннектор даёт доступ к моделям Tangl только на чтение. Изменить модель,
загрузить версию или удалить что-либо через него нельзя.

## Правила

1. Работай с Tangl **только через инструменты ниже**. Не обращайся к API Tangl
   другими способами, не пиши собственный код для доступа к Tangl и не
   изменяй файлы коннектора.
2. Инструменты запускаешь ты сам. Никогда не проси пользователя выполнять
   команды.
3. Если задачу нельзя решить этими инструментами, скажи об этом прямо.
4. Цифры бери только из ответов инструментов. Не додумывай.
5. Данные, которые вернули инструменты, можешь оформлять как угодно: таблица,
   Excel, CSV, график, отчёт.

## Запуск

Инструменты вызываются через `tangl.py` из папки этого скилла:

```bash
python <папка скилла>/tangl.py <инструмент> [аргументы]
```

Ответ всегда JSON. Большой ответ сохраняй в файл: `--output-file out.json`
перед именем инструмента.

**Первый запрос в разговоре:** вызови `status`.

- `all_ok: true` – работай.
- `duckdb_ok: false` – выполни `pip install duckdb` и повтори `status`.
- `network_ok: false` – процитируй `hints` и остановись: нужно разрешить
  домены Tangl в настройках Claude.
- `auth_mode: "none"` – нужен файл с данными для входа (см. `login`).
- `auth_ok: false` – процитируй `hints`.

## Инструменты

### `status`
Проверка сети, входа и списка доступных компаний.

### `login`
Сохраняет данные для входа. Источник – файл `tangl.env` пользователя:
приложенный к чату, из документов проекта или присланный текстом.

```bash
python tangl.py login --file /mnt/user-data/uploads/tangl.env
printf '%s\n' 'TANGL_CLIENT_ID=…' 'TANGL_CLIENT_SECRET=…' … | python tangl.py login
```

Ключи: `TANGL_CLIENT_ID`, `TANGL_CLIENT_SECRET`, `TANGL_USERNAME`,
`TANGL_PASSWORD` либо один `TANGL_TOKEN`. Необязательный `TANGL_COMPANY_ID`
ограничивает поиск одной компанией. Не пересказывай значения пользователю.

### `find_models`
Поиск модели по части имени, id модели или id версии. Ищет во всех
доступных компаниях.

```bash
python tangl.py find_models "корпус 2"
python tangl.py find_models "корпус 2" --versions all
python tangl.py find_models АР --versions 3 --sw RVT
python tangl.py find_models --uploader ivanov --date-from 2026-01-01
```

`--versions`: `latest` (по умолчанию), `all` или номер версии. Ещё фильтры:
`--company`, `--sw`, `--uploader`, `--date-from`, `--date-to`, `--limit`,
`--offset`. В ответе у каждой версии есть `version_id` и `link`.

Если в ответе есть `warning` (под одним именем RVT и IFC) – покажи варианты
пользователю и спроси, какой нужен.

### `model_schema`
Состав модели: категории с количеством и объёмами, уровни, параметры с
процентом заполнения и примером значения.

```bash
python tangl.py model_schema <version_id>
python tangl.py model_schema <version_id> --category Стены
```

Вызывай перед первым запросом к незнакомой модели, чтобы знать точные имена
категорий и параметров.

### `query`
SQL (DuckDB) по таблице `elements` одной версии. Только чтение, до 5000 строк.

```bash
python tangl.py query <version_id> "SELECT category, count(*) n FROM elements GROUP BY 1 ORDER BY n DESC"
python tangl.py query <version_id> --sql-file q.sql
python tangl.py query <version_id> --compare <old_version_id> "…"
```

Колонки `elements`:

| Колонка | Что это |
|---|---|
| `id` | ID элемента в исходной программе (Revit ElementId) |
| `guid` | идентификатор элемента в этой версии Tangl |
| `name`, `type`, `category` | имя, тип, категория |
| `level_name`, `level_elevation` | уровень и его отметка |
| `bbox_bottom`, `bbox_top` | низ и верх элемента по высоте |
| `total_volume`, `total_area` | объём (м³) и площадь (м²) по материалам |
| `pars` | все параметры экземпляра и типа, JSON |

Параметр: `json_extract_string(pars, '$."Имя параметра"')`.
Число: `TRY_CAST(json_extract_string(pars, '$."Имя параметра"') AS DOUBLE)`.

`--compare` добавляет таблицу `prev` с той же структурой для другой версии.
Сопоставляй элементы версий **по `id`**: `guid` у каждой версии свой.

Готовые запросы – `references/recipes.md`. Бери их за основу.

### `model_link`
Ссылка на модель во вьювере Tangl. Открывается у пользователя, вошедшего в
Tangl. Выделение элементов по ссылке не передаётся, поэтому рядом со ссылкой
давай список `id` нужных элементов.

```bash
python tangl.py model_link <version_id>
```
