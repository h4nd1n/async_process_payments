# Асинхронный сервис процессинга платежей

Микросервис на **FastAPI**, **SQLAlchemy 2** (async), **PostgreSQL**, **RabbitMQ** (**FastStream**): приём платежей, публикация событий через **Outbox**, обработка в одном consumer’е с эмуляцией шлюза и **webhook** с повторными попытками, **DLQ** после исчерпания попыток обработки.

## Стек

- FastAPI, Pydantic v2
- SQLAlchemy 2.0 + asyncpg
- Alembic (async)
- FastStream (Rabbit/aio-pika)
- httpx (webhook)
- Docker Compose: PostgreSQL 16, RabbitMQ 3.13 (веб-интерфейс management)

## Запуск

Требуется Docker (Docker Compose v2).

```bash
docker compose up --build
```

- HTTP API: `http://localhost:8000`
- Документация OpenAPI: `http://localhost:8000/docs`
- RabbitMQ Management: `http://localhost:15672` (guest / guest)

Миграции выполняются при старте сервиса `api`. Сервисы `api` и `consumer` стартуют только после **healthy** PostgreSQL и RabbitMQ (`depends_on` + healthcheck); `consumer` — после `api`, чтобы таблицы уже существовали.

## Переменные окружения

| Переменная | Описание | По умолчанию |
|------------|----------|--------------|
| `DATABASE_URL` | DSN async SQLAlchemy (`postgresql+asyncpg://...`) | см. `.env.example` |
| `RABBITMQ_URL` | AMQP URL | `amqp://guest:guest@localhost:5672/` |
| `API_KEY` | Статический ключ для заголовка `X-API-Key` | `dev-secret-api-key-change-me` |
| `OUTBOX_POLL_INTERVAL_SEC` | Пауза relay при пустом outbox | `0.75` |
| `WEBHOOK_MAX_ATTEMPTS` | Попыток доставки webhook | `3` |
| `WEBHOOK_BACKOFF_BASE_SEC` | База экспоненциальной задержки webhook (сек) | `1.0` |
| `CONSUMER_MAX_PROCESS_RETRIES` | Попыток обработки сообщения до DLQ | `3` |

## Тесты

### Зависимости и интерпретатор

```bash
python -m pip install -r requirements-dev.txt
```

Запускайте **`python -m pytest`**, чтобы использовался тот же Python, что и у `pip` (в Windows голая команда **`pytest`** часто берёт другой интерпретатор → `ModuleNotFoundError`).

### Быстрые тесты (без Docker)

Юнит-тесты: схемы, повторы/DLQ на моках, webhook через **respx**. RabbitMQ/PostgreSQL не нужны.

```bash
python -m pytest tests/test_payment_schemas.py tests/test_consumer_retry.py
```

### Полный прогон с testcontainers

Интеграционные тесты сами поднимают **PostgreSQL** и **RabbitMQ** в Docker (модуль **testcontainers**), выполняют `alembic upgrade head`, поднимают приложение с реальным **`lifespan`** (**asgi-lifespan** + **httpx**).

**Условия:**

1. Запущен **Docker Desktop** (или иной демон, с которым работает Docker API).
2. Установлены dev-зависимости, в том числе **pika** и **asgi-lifespan** (уже перечислены в `requirements-dev.txt`).

**Команды:**

```bash
# всё: юнит + интеграция (интеграция без Docker будет пропущена)
python -m pytest

# только интеграция (те же контейнеры)
python -m pytest tests/test_integration_api.py -m integration
```

Если Docker недоступен, тесты из `test_integration_api.py` получат статус **skipped**, остальные пройдут.

Если интеграционные тесты пропускаются с текстом **`No module named 'pika'`**, для **RabbitMqContainer** не установлена зависимость: выполните заново **`python -m pip install -r requirements-dev.txt`** (там есть `pika`) или явно **`python -m pip install "pika>=1.3.0"`**.

**Windows (надёжно из корня проекта):**

```powershell
.\.venv\Scripts\python.exe -m pip install -r requirements-dev.txt
.\.venv\Scripts\python.exe -m pytest -v
```

## API

Все запросы требуют заголовок **`X-API-Key`** (совпадает с `API_KEY`).

### Создание платежа

- Метод: `POST /api/v1/payments`
- Обязательные заголовки: `Idempotency-Key`, `X-API-Key`
- Тело (JSON): `amount`, `currency` (`RUB` | `USD` | `EUR`), `description`, `metadata` (объект), `webhook_url`
- Ответ: **202 Accepted**, поля `payment_id`, `status`, `created_at`

Повтор того же `Idempotency-Key` возвращает тот же платеж (без второй записи в outbox).

### Получение платежа

- `GET /api/v1/payments/{payment_id}`

## Примеры `curl`

В примерах используется ключ по умолчанию из `docker-compose.yml`. В продакшене задайте свой `API_KEY`.

Создание:

```bash
curl -s -X POST "http://localhost:8000/api/v1/payments" \
  -H "Content-Type: application/json" \
  -H "X-API-Key: dev-secret-api-key-change-me" \
  -H "Idempotency-Key: demo-001" \
  -d "{\"amount\": \"99.90\", \"currency\": \"RUB\", \"description\": \"Тест\", \"metadata\": {\"order_id\": \"1\"}, \"webhook_url\": \"https://webhook.site/your-id\"}"
```

Получение:

```bash
curl -s "http://localhost:8000/api/v1/payments/PAYMENT_UUID" \
  -H "X-API-Key: dev-secret-api-key-change-me"
```

## Поведение пайплайна

1. **Создание платежа**: в одной транзакции сохраняются строка `payments` (статус `pending`) и событие в **`outbox`**.
2. **Outbox relay** (фоновый цикл в процессе **api**): читает неопубликованные записи (`FOR UPDATE SKIP LOCKED`), публикует JSON в очередь **`payments.new`**, проставляет **`published_at`**. Сбой публикации откатывает транзакцию — событие останется для повторной отправки.
3. **Consumer**: читает `payments.new`, при **идемпотентности** пропускает уже обработанные (`status != pending`). Эмуляция шлюза: пауза 2–5 с, **90%** `succeeded`, **10%** `failed`. Обновляет БД и шлёт **POST** на `webhook_url` с экспоненциальными повторами (см. env).
4. **Повтор обработки / DLQ**: при исключении во время обработки сообщение переиздаётся в `payments.new` с заголовком `x-retry-count`. После **3** неудач тело уходит в очередь **`payments.new.dlq`**; отдельный subscriber только логирует такие сообщения.

## Очереди RabbitMQ

| Очередь | Назначение |
|---------|------------|
| `payments.new` | Новые платежи к обработке |
| `payments.new.dlq` | Сообщения после исчерпания попыток обработки |
