# Интеграция ECG Analyzer в основной репозиторий

Этот документ описывает, как подключить сервис ECG Analyzer (FastAPI + PostgreSQL) к основному репозиторию и встроить UI.

## 1. Быстрый старт (локальная разработка)

1. Скопируйте `.env.example` в `.env` и отредактируйте под свои нужды.
2. Поднимите контейнеры: `docker compose up -d --build`.
3. Проверьте: `curl http://localhost:8000/health` -> `{"status":"healthy"}`.
4. Swagger: откройте `http://localhost:8000/docs`.

## 2. Использование образа из GHCR (для прода)

Образ автоматически собирается и публикуется в `ghcr.io/asdergh/ecgmetanarrator` при пуше в `main` (GitHub Actions).

В docker-compose.yml основного репозитория укажите:
- image: ghcr.io/asdergh/ecgmetanarrator:latest
- environment: DATABASE_URL, SIGNALS_DIR, ALLOWED_ORIGINS
- ports: 8000:8000
- volumes: ./data/signals:/app/data/signals

Если образ приватный, авторизуйтесь в registry через docker login ghcr.io.

## 3. API-контракты (для UI)

### 3.1. Список пакетов
GET /api/ecg/ -> массив объектов (id, name, fs, n_sig, duration).

### 3.2. Чат (режимы 1-3)
POST /api/chat/ с телом { text: string, session_id: number|null }.
Ответ: context (текст аннотации), response_id (id ответа), grade, can_grade (bool), can_regenerate (bool), current_pkg, available_packages (если пакет не найден).

### 3.3. Оценка (режим 4, шаг 1)
POST /api/chat/grade?session_id=N с телом { response_id: number, grade: 0-10 }.
Ответ: can_grade=false, can_regenerate=true (порядок из ТЗ).

### 3.4. Перегенерация (режим 4, шаг 2)
POST /api/chat/regenerate?session_id=N с телом { response_id: number }.
Ответ: новый context, grade=null, can_grade=true, can_regenerate=false.

## 4. Встраивание UI (кнопки и подсветка)

### 4.1. Кнопки оценки
Показывайте кнопки 0-10, если can_grade=true. При нажатии отправляйте POST /api/chat/grade.

### 4.2. Кнопка Перегенерировать
Показывайте, если can_regenerate=true. При нажатии отправляйте POST /api/chat/regenerate.

### 4.3. Подсветка при наведении (CSS)

.grade-btn { transition: background 0.2s, opacity 0.2s; }
.grade-btn:hover { background: #e0e0e0; opacity: 0.8; }

.regen-btn { transition: background 0.2s; }
.regen-btn:hover { background: #e6f0fa; }

### 4.4. Логика отображения
- Если available_packages не null — покажите список пакетов (пакет не найден).
- Если can_grade — покажите кнопки оценки.
- Если can_regenerate — покажите кнопку перегенерации.

## 5. Замена заглушки на реальную нейросеть

1. Откройте app/infrastructure/nn_pipeline.py.
2. Замените тело функции generate_response(prompt: dict) на вызов вашей модели.
3. НЕ меняйте контракт: вход — prompt-словарь (question, raw, fs), выход — строка (context).
4. Остальной код (сервисы, API, БД) уже настроен под этот контракт.

## 6. Структура проекта

app/main.py — FastAPI, lifespan, CORS.
app/config.py — настройки через .env.
app/database.py — async PostgreSQL, пул соединений.
app/models_db.py — SQLAlchemy-модели (User, Session, PromptState).
app/schemas/ — Pydantic-контракты.
app/api/routes/ecg.py — существующие роуты (сигналы).
app/api/routes/chat.py — новые роуты (чат, оценка, перегенерация).
app/services/ — chat_service, grade_service, prompt_service, resolver_service.
app/core/ecg_loader.py — загрузка сигналов через wfdb.
app/infrastructure/nn_pipeline.py — заглушка нейросети.

