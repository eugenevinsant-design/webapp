# ECG Meta Narrator

Интеллектуальная платформа для визуализации, разметки и анализа электрокардиографических (ЭКГ) сигналов.

## 🚀 Основные возможности

- **Анализ ЭКГ:** Загрузка 12-канальных сигналов через wfdb и генерация клинической аннотации (ML-факты → LLM).
- **Чат-интерфейс:** Взаимодействие с нейросетью через текстовые запросы (команды `\choose_pkg`).
- **Оценка и перегенерация:** Оценка ответа модели (0-10) и перегенерация нового варианта.
- **Трёхшаговый вход:** токен доступа к платформе → регистрация (логин → личный токен) → вход по паре логин + токен.
- **История:** Действия пользователя (анализ, перегенерация, оценка) сохраняются в БД **только после оценки** — асинхронным писателем с батчингом (без потерь при нагрузке).

## 🛠 Технологический стек

- **Backend:** Python 3.11, FastAPI, SQLAlchemy (async), Alembic.
- **База данных:** PostgreSQL 15 (Docker) или SQLite (локальный запуск без Docker, файл `dev.db`).
- **LLM:** любой OpenAI-совместимый API — локальный vLLM (GPU) или hosted (OpenRouter, Groq, Gemini).
- **Frontend:** Vanilla JS, HTML5, CSS3 (без фреймворков).
- **Инфраструктура:** Docker, Docker Compose, GitHub Actions (CI/CD).
- **Работа с ЭКГ:** Библиотека wfdb (PhysioNet).

## 📦 Быстрый старт

### Вариант A — Docker с локальной LLM (нужна NVIDIA GPU)

1. Клонируйте репозиторий.
2. Скопируйте `.env.example` в `.env` (`DATABASE_URL` оставьте закомментированным — compose сам подставит postgres).
3. Задайте `PLATFORM_ACCESS_TOKEN` в `.env` (ваш «пропуск» на сайт).
4. Запустите контейнеры (сервис vLLM включается профилем):
   `docker compose --profile vllm up -d --build`
5. Откройте в браузере: `http://localhost:8000`

> Первый запуск vLLM скачает модель (~15 ГБ) — это займёт время.
> vLLM доступен с хоста на порту 8001 (только для отладки; backend ходит к нему по внутренней сети).

### Вариант B — без GPU (hosted LLM API, например OpenRouter)

1. Клонируйте репозиторий, скопируйте `.env.example` в `.env`.
2. В `.env` укажите hosted API (ключ без карты, например OpenRouter):
   ```
   LLM_BASE_URL=https://openrouter.ai/api/v1
   LLM_MODEL=nvidia/nemotron-3-ultra-550b-a55b:free
   LLM_API_KEY=sk-or-...
   ```
3. Поднимите контейнеры (vLLM не поднимется — он за профилем):
   `docker compose up -d --build`
4. Откройте `http://localhost:8000`

### Вариант C — совсем без Docker (локальная разработка)

1. `python -m venv .venv && .venv\Scripts\activate` (Windows) + `pip install -r requirements.txt`
2. В `.env` раскомментируйте `DATABASE_URL=sqlite+aiosqlite:///./dev.db` и задайте hosted LLM (как в варианте B).
3. `.venv\Scripts\python.exe -m uvicorn app.main:app` → `http://localhost:8000`

## 🔐 Вход на платформу (3 шага)

1. **Токен платформы** — введите значение `PLATFORM_ACCESS_TOKEN` из `.env` (токены хранятся в таблице `platform_tokens`, можно добавлять/отзывать).
2. **Регистрация** — придумайте логин, получите **личный токен** (показывается один раз — сохраните!).
3. **Вход** — логин + личный токен (проверяется пара, чужой токен не подойдёт).

## ⚙️ Где настраивается API модели

Цепочка конфигурации LLM:
```
.env (LLM_BASE_URL / LLM_MODEL / LLM_API_KEY)
  → app/config.py (Settings)
  → app/core/ecgllm_bridge.py (setup_llm)
  → ecgllm/llm/pipeline.py (process_text — OpenAI-совместимый вызов)
```
В Docker переменные пробрасываются блоком `environment:` в `docker-compose.yml`.

## 🧪 Тестирование

- В Docker: `docker compose exec backend pytest tests/ -v`
- Локально: `.venv\Scripts\python.exe -m pytest tests/ -v`

## 📄 Документация

- Архитектура: `app/README_ARCHITECTURE.md`
- Интеграция: `README_INTEGRATION.md`
- GPU/LLM: `README_GPU.md`
