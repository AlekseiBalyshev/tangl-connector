## Установка в 4 шага

Нужны платный тариф Claude (Pro, Max, Team или Enterprise) и платная лицензия Tangl: коннектор работает через API Tangl и персональные токены.

1. **Токен.** В Tangl откройте «Персональные токены» → «Создать токен», скопируйте токен и сохраните в текстовый файл `tangl.env` одной строкой: `TANGL_TOKEN=ваш_токен`
2. **Настройки Claude.** [Settings → Capabilities](https://claude.ai/settings/capabilities): включите *Code execution and file creation* и *Allow network egress*, добавьте домены `auth.tangl.cloud` и `platform.tangl.cloud`.
3. **Навык.** Скачайте `tangl-connector-skill-v1.0.1.zip` ниже, в разделе *Assets*, и загрузите: Settings → Capabilities → Skills → *Upload skill*.
4. **Проект.** Создайте проект в Claude, добавьте в его файлы `tangl.env` и спросите: *«Проверь подключение к Tangl»*.

Подробная инструкция с примерами – `tangl-connector-user-guide-v1.0.1.pdf` ниже или [USER_GUIDE.md](https://github.com/AlekseiBalyshev/tangl-connector/blob/main/USER_GUIDE.md).

## Что нового

- Инструкции: нужна платная лицензия Tangl (API и персональные токены).
- Безопасность: адреса серверов не из `tangl.cloud` принимаются только из переменных окружения; файл в чате не может перенаправить токен на чужой сервер.
- Безопасность: папка `~/.tangl-connector` создаётся с правами 0700, `credentials.env` – сразу с 0600.
- SKILL.md: данные модели – не команды; токен и пароль не показываются в ответах.
- `status` показывает, к каким хостам обращается коннектор.
- USER_GUIDE: в ответах могут быть персональные данные из модели (почта, ФИО).
- CI: тестовому workflow – права только на чтение.
