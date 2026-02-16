# tg2tiktok-poster

Сервис для автопостинга контента из Telegram в TikTok на несколько аккаунтов.

Поддерживает:
- Telegram intake: `webhook` и `polling`.
- Telegram типы: видео, фото, альбомы (`media_group`).
- TikTok режимы: `draft inbox upload` и `direct publish`.
- Фото/альбомы: попытка photo API (опционально), иначе надёжный fallback через `ffmpeg` в видео-слайдшоу.
- Идемпотентность доставок (без дублей на один аккаунт).

## Стек
- Python 3.11+
- FastAPI + Uvicorn
- httpx
- pydantic + pydantic-settings + python-dotenv
- SQLite + SQLAlchemy
- asyncio.Queue background worker
- ffmpeg для фото/альбом -> видео

## Структура проекта
```text
tg2tiktok-poster/
  app/
    __init__.py
    main.py
    config.py
    db.py
    models.py
    telegram/
      __init__.py
      parser.py
      client.py
      polling.py
      aggregator.py
    tiktok/
      __init__.py
      oauth.py
      client.py
      video_posting.py
      photo_posting.py
      publisher.py
    media/
      __init__.py
      ffmpeg.py
      captions.py
    queue/
      __init__.py
      worker.py
      tasks.py
    utils/
      __init__.py
      logging.py
      rate_limit.py
  tests/
    test_tg_parser.py
    test_media_group_aggregator.py
  requirements.txt
  Dockerfile
  docker-compose.yml
  README.md
  .env.example
```

## Быстрый старт (локально)
1. Установите Python 3.11+.
2. Установите ffmpeg локально.
3. Создайте `.env` из шаблона:
```bash
cp .env.example .env
```
4. Заполните `.env` (Telegram + TikTok ключи).
5. Установите зависимости:
```bash
pip install -r requirements.txt
```
6. Запустите API:
```bash
uvicorn app.main:app --reload
```
7. Альтернатива polling-режим:
```bash
python -m app.telegram.polling
```

## Запуск через Docker
```bash
docker compose up --build
```
`ffmpeg` уже установлен в контейнере (см. `Dockerfile`).

## Переменные окружения
См. `.env.example`. Обязательные минимум:
- `APP_BASE_URL`
- `TG_BOT_TOKEN`
- `TG_WEBHOOK_SECRET`
- `USE_TG_WEBHOOK`
- `TIKTOK_CLIENT_KEY`
- `TIKTOK_CLIENT_SECRET`
- `TIKTOK_REDIRECT_URI`
- `POSTING_MODE`
- `FALLBACK_TO_DRAFT`
- `APPEND_HASHTAGS`
- `CAPTION_TEMPLATE`
- `STORAGE_DB_PATH`
- `MEDIA_GROUP_FLUSH_SECONDS`
- `SLIDE_SECONDS`
- `SLIDESHOW_FPS`
- `ENABLE_PHOTO_API`
- `RATE_LIMIT_PER_MINUTE`

## Telegram настройка
1. Создайте бота через `@BotFather`.
2. Возьмите токен и сохраните в `TG_BOT_TOKEN`.
3. Добавьте бота в нужный канал/чат и дайте права администратора.
4. Выберите режим intake:

`Webhook`:
- Включите `USE_TG_WEBHOOK=true`.
- Используйте endpoint:
  - `POST /tg/webhook/{TG_WEBHOOK_SECRET}`
- Пример URL:
  - `https://your-domain.com/tg/webhook/<secret>`

`Polling`:
- Установите `USE_TG_WEBHOOK=false`.
- Запускайте отдельный runner:
  - `python -m app.telegram.polling`

## TikTok настройка (Developer App + OAuth)
1. Создайте приложение в TikTok Developer.
2. Возьмите `client_key` и `client_secret`.
3. Настройте `redirect_uri` в TikTok и `.env`:
   - `TIKTOK_REDIRECT_URI=http://localhost:8000/tiktok/auth/callback`
4. Для подключения аккаунта используйте:
   - `GET /tiktok/auth/start?account_label=acc1&mode=draft`
   - `GET /tiktok/auth/start?account_label=acc2&mode=direct`
5. После callback аккаунт сохранится в SQLite.
6. Проверить подключённые аккаунты:
   - `GET /admin/tiktok/accounts`

### Multi-account routing
- По умолчанию каждый TG-пост отправляется во **все** TikTok-аккаунты.
- Опционально можно ограничить маршрутизацию через:
  - `TG_TO_TIKTOK_MAPPING_JSON={"-100123":["acc1","acc2"]}`

## Как это работает
1. `webhook/polling` получает update от Telegram.
2. Для `media_group` сообщения буферизуются в SQLite (`media_group_buffer`).
3. Через `MEDIA_GROUP_FLUSH_SECONDS` альбом собирается в один `ContentItem`.
4. В очередь ставится задача обработки.
5. Worker скачивает медиа из Telegram.
6. На каждый TikTok аккаунт создаётся delivery с проверкой идемпотентности:
   - уникально по `source_key + account_label`.
7. Публикация:
   - Видео -> видео пайплайн (`draft/direct`).
   - Фото/альбом:
     - Если `ENABLE_PHOTO_API=true`, сначала пробуется photo API.
     - При недоступности endpoint/permission делается fallback:
       `ffmpeg` -> `mp4` -> upload как видео.

## Важные ограничения TikTok
- `direct publish` может быть недоступен для токена/скоупа/программы доступа.
- В этом случае логируется ошибка и при `FALLBACK_TO_DRAFT=true` выполняется fallback в draft upload.
- Токены в логах не печатаются.

## ffmpeg установка локально
- Ubuntu/Debian:
  - `sudo apt-get update && sudo apt-get install -y ffmpeg`
- macOS (Homebrew):
  - `brew install ffmpeg`
- Windows (choco):
  - `choco install ffmpeg`

## Тестовый сценарий
1. Запустите сервис (`uvicorn app.main:app --reload`).
2. Пройдите OAuth минимум для 2 аккаунтов:
   - `/tiktok/auth/start?account_label=acc1&mode=draft`
   - `/tiktok/auth/start?account_label=acc2&mode=direct`
3. Отправьте в Telegram видео.
4. Отправьте одно фото.
5. Отправьте альбом из нескольких фото (одним постом / media_group).
6. Проверьте результат:
   - photo post / carousel (если `ENABLE_PHOTO_API=true` и API/скоуп доступен),
   - иначе видео-слайдшоу.

## Команды разработки
```bash
# API
uvicorn app.main:app --reload

# Telegram polling runner
python -m app.telegram.polling

# Тесты
pytest -q
```

## Приёмочный чеклист
- [ ] OAuth сохраняет аккаунт
- [ ] Webhook/polling принимает updates
- [ ] Альбомы Telegram агрегируются (`media_group`)
- [ ] Видео: draft upload работает
- [ ] Фото 1 шт: конвертация в mp4 и загрузка работает
- [ ] Альбом фото: конвертация в slideshow mp4 и загрузка работает
- [ ] Если `ENABLE_PHOTO_API=true` и endpoint доступен — фото/карусель постится без конвертации (иначе fallback)
- [ ] Direct publish пробуется и при ошибке делает fallback (если включено)
- [ ] Идемпотентность не допускает дублей
- [ ] Токены не светятся в логах

## Безопасность
- Не храните реальные ключи в репозитории.
- Используйте только `.env`/секрет-хранилище.
