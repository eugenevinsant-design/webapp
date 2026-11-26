# Запуск ECG Meta Narrator на сервере (Docker)

Полноценная серверная версия: **FastAPI + PostgreSQL + wfdb** для чтения ЭКГ, LLM — через внешний OpenAI-совместимый API (без подгрузки весов нейросети).

Ветка для деплоя: **`server`**.

Проверено end-to-end (26.11.2026): сборка образа, регистрация, вход, анализ ЭКГ (`JS00002`) с реальным ответом LLM — всё работает.

---

## 1. Требования

- Docker Engine 24+ с Docker Compose v2 (`docker compose version`)
- 2 ГБ RAM, ~2 ГБ на диске под образы
- Доступ в интернет (вызовы LLM API)
- API-ключ OpenAI-совместимого провайдера (по умолчанию — OpenRouter)

## 2. Установка и запуск

```bash
git clone -b server https://github.com/eugenevinsant-design/webapp.git
cd webapp
cp .env.example .env   # затем отредактировать (см. раздел 3)
docker compose up -d --build
```

Поднимаются два контейнера:

| Контейнер | Образ | Порт | Назначение |
|---|---|---|---|
| `ecg_backend` | собирается из `Dockerfile` | `8000` | FastAPI-приложение |
| `ecg_postgres` | `postgres:15` | `5432` | База данных |

Первая сборка занимает 3–5 минут (pip-зависимости). При старте приложение само создаёт таблицы в БД и сидит токен платформы — миграции вручную не нужны.

Сервис доступен: `http://<адрес-сервера>:8000`

## 3. Конфигурация (.env)

Обязательные для заполнения:

| Переменная | Что указать |
|---|---|
| `LLM_BASE_URL` | `https://openrouter.ai/api/v1` (или адрес своего vLLM) |
| `LLM_MODEL` | например `nvidia/nemotron-3-ultra-550b-a55b:free` |
| `LLM_API_KEY` | ключ провайдера |
| `PLATFORM_ACCESS_TOKEN` | токен-«пропуск» на платформу (выдаётся пользователям) |
| `SECRET_KEY` | любая длинная случайная строка (для prod) |

Опционально: `POSTGRES_USER/PASSWORD/DB/PORT`, `BACKEND_PORT`, `ALLOWED_ORIGINS`, `POOL_SIZE`, `LLM_TIMEOUT` (сек), `LLM_MAX_TOKENS`, `ML_BACKEND` (`deterministic` по умолчанию).

> **Важно:** `DATABASE_URL` в `.env` не трогать — контейнер бэкенда всегда пишет в сервис `postgres` по внутренней сети (переопределено в `docker-compose.yml`).

## 4. Проверка после запуска

```bash
# 1. Контейнеры живы
docker ps                          # оба в статусе (healthy)

# 2. API отвечает
curl http://localhost:8000/health  # {"status":"healthy"}

# 3. Сигналы видны
curl http://localhost:8000/api/ecg/   # список: JS00002, JS00004

# 4. wfdb используется для чтения ЭКГ
docker exec ecg_backend python -c "from app.core import ecg_loader as L; print(L._HAS_WFDB)"
# True

# 5. LLM настроена
curl http://localhost:8000/api/chat/llm-status
# {"configured":true, "model":"...", "api_key_set":true, ...}
```

## 5. Работа пользователя с платформой

1. Открыть `http://<адрес-сервера>:8000`
2. Ввести **токен платформы** (значение `PLATFORM_ACCESS_TOKEN` из `.env`)
3. Зарегистрироваться: указать логин → система выдаст **личный токен** (сохранить!)
4. Войти по логину + личному токену
5. Выбрать ЭКГ-сигнал → задать вопрос → получить анализ (ML-факты → LLM) → оценить ответ (только после оценки данные пишутся в БД)

## 6. Своя нейросеть вместо внешнего API (опционально)

Бэкенд общается с LLM только по OpenAI-совместимому HTTP API. Чтобы подключить свою модель на GPU-сервере:

```bash
# На GPU-сервере:
docker run --gpus all -p 8000:8000 vllm/vllm-openai:latest \
  --model Qwen/Qwen2.5-7B-Instruct --api-key ВАШ_СЕКРЕТ

# В .env бэкенда:
LLM_BASE_URL=http://<IP-GPU-сервера>:8000/v1
LLM_API_KEY=ВАШ_СЕКРЕТ
LLM_MODEL=Qwen/Qwen2.5-7B-Instruct
```

Либо vLLM в том же compose (закомментированный сервис за профилем): `docker compose --profile vllm up -d`, и `LLM_BASE_URL=http://llm:8000/v1`.

## 7. Обновление версии

```bash
git pull origin server
docker compose up -d --build
```

Данные в PostgreSQL сохраняются в volume `postgres_data` — обновление кода их не трогает.

## 8. Диагностика

| Симптом | Причина / решение |
|---|---|
| `port is already allocated` | Порт 8000/5432 занят → поменять `BACKEND_PORT`/`POSTGRES_PORT` в `.env` |
| 503 «LLM-сервис недоступен» | Проверить `LLM_BASE_URL`/`LLM_API_KEY`, лимиты провайдера, интернет с сервера |
| Пустой список сигналов | Положить пары `.hea` + `.mat` в `./data/signals` (папка смонтирована в контейнер) |
| Логи бэкенда | `docker logs -f ecg_backend` |
| Пересоздать БД с нуля | `docker compose down -v` (удалит volume, **данные потеряются**) + `up -d` |

## 9. Архитектура одним взглядом

```
Браузер → FastAPI ──► PostgreSQL (пользователи, сессии, оценки)
              │
              ├─► wfdb: чтение .hea/.mat → ML-анализ (scipy, deterministic)
              │
              └─► LLM через OpenAI-совместимый API (OpenRouter / свой vLLM)
```

Облачное демо (без Docker): https://ecg-webapp-red.vercel.app — ветка `vercel-demo`, там чтение сигналов идёт через scipy-fallback (лимит serverless 250 МБ), поведение идентично.
