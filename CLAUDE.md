# Tangl Connector – контекст для разработки

Публичный репозиторий. Навык для claude.ai, только чтение моделей Tangl
(platform), без Value и Control. Без MCP-сервера.

## Устройство

- `tangl.py` – точка входа, `python tangl.py <инструмент>`.
- `tangl_connector/config.py` – данные для входа: окружение → `~/.tangl-connector/credentials.env` → `.env`/`tangl.env` → файлы в `/mnt/user-data/uploads`.
- `tangl_connector/client.py` – вход (token / password / client_credentials), `ReadOnlySession`: наружу только GET, кроме `/connect/token`.
- `tangl_connector/meta.py` – tangl-meta → плоская таблица `elements` (RefIdx раскрываются) → parquet-кэш в `~/.tangl-connector/cache`.
- `tangl_connector/tools.py` – инструменты. DuckDB без доступа к файлам (`enable_external_access=false`).

## Факты API

- `storageType=tangl-meta` обязателен; большие модели – `/stream` (сырой LZMA).
- В JSON бывает хвостовая запятая `,]`.
- `guid` элемента свой у каждой версии – версии сравнивать по `id` (Revit ElementId).
- Компании пользователя: `GET auth.tangl.cloud/api/app/company`.

## Правила

- Никаких реальных названий объектов, компаний, людей, адресов, id в коде, тестах, документах и истории. Перед релизом `build_release.py` проверяет стоп-слова из `.stopwords` (файл не в git).
- SKILL.md: коротко, ИИ работает только через инструменты коннектора.
- Тире в текстах – только `–`.
- Версия – `build_release.py --version X.Y.Z --date YYYY-MM-DD`; номер продолжает последний релиз на `main`. Папка `releases/vX.Y.Z_YYYY-MM-DD/` пополняется только на `main` после мержа.
- Работа в ветке считается законченной после PR в `main`.
