# Tangl Connector

Навык (skill) для Claude: чтение BIM-моделей из облачной платформы
[Tangl](https://tangl.cloud) обычным языком. Найти модель и версию, посчитать
элементы, объёмы и бетон по классам, проверить параметры, сравнить версии,
получить ссылку на модель.

Коннектор только читает: запросы на изменение блокируются до отправки в Tangl.

## Установка в 4 шага

Нужен платный тариф Claude (Pro, Max, Team или Enterprise) и учётная запись Tangl.

1. **Токен.** В Tangl откройте «Персональные токены» → «Создать токен»,
   скопируйте токен и сохраните в текстовый файл `tangl.env` одной строкой:
   `TANGL_TOKEN=ваш_токен`
2. **Настройки Claude.** [Settings → Capabilities](https://claude.ai/settings/capabilities):
   включите *Code execution and file creation* и *Allow network egress*,
   добавьте домены `auth.tangl.cloud` и `platform.tangl.cloud`.
3. **Навык.** Скачайте `tangl-connector-skill-vX.Y.Z.zip` со
   [страницы релиза](../../releases/latest) и загрузите его:
   Settings → Capabilities → Skills → *Upload skill*.
4. **Проект.** Создайте проект в Claude, добавьте в его файлы `tangl.env` и
   спросите: *«Проверь подключение к Tangl»*, затем *«Найди мою модель …»*.

Примеры вопросов, хранение данных и решение проблем – [USER_GUIDE.md](USER_GUIDE.md).

## Инструменты

| Инструмент | Что делает |
|---|---|
| `status` | проверка сети, входа и доступных компаний |
| `login` | сохранение данных для входа из `tangl.env` |
| `find_models` | поиск модели и версии |
| `model_schema` | категории, уровни, материалы, параметры и их заполнение |
| `query` | SQL-запросы к элементам и материалам версии, сравнение двух версий |
| `model_link` | ссылка на модель во вьювере Tangl |
| `clean` | удаление выгруженных данных с диска |

## Ограничения

- **Размер модели.** Версия модели целиком загружается в память среды
  выполнения. По замерам пик памяти – около 2 ГБ на 90 тыс. элементов,
  3,2 ГБ на 250 тыс., 5,8 ГБ на 380 тыс. Лимит памяти среды Claude не
  публикуется, поэтому коннектор не выгружает версии больше
  **200 000 элементов** и предлагает взять модель отдельного раздела.
  При локальном запуске порог задаётся переменной `TANGL_MAX_ELEMENTS`.
- **Сравнение версий** надёжно только для моделей из Revit: у IFC номера
  элементов могут меняться между выгрузками.
- Ответ одного запроса – не больше 5000 строк.

## In English

Tangl Connector is a read-only Claude skill for the [Tangl](https://tangl.cloud)
BIM platform. Ask about your models in plain language: find a model, count
elements and concrete volumes by level and strength class, check empty
parameters, compare two versions. To install, create a personal token in
Tangl and save `TANGL_TOKEN=…` to a `tangl.env` file. In Claude (paid plan),
enable code execution and network egress for `auth.tangl.cloud` and
`platform.tangl.cloud`. Upload the skill zip from the
[latest release](../../releases/latest), add `tangl.env` to a Claude project
and ask *"Check the Tangl connection"*.

## Лицензия

MIT. Python 3.10+, `requests`, `duckdb`.
