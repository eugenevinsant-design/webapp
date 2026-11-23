# Развертывание LLM на GPU (vLLM)

Сервис использует **vLLM** — OpenAI-совместимый inference-сервер для LLM.
Backend ходит к нему по `LLM_BASE_URL` (внутри docker-compose — `http://llm:8000/v1`).

## 1. Требования

- GPU с поддержкой CUDA (NVIDIA), драйвер + `nvidia-container-toolkit` на хосте.
- Docker + Docker Compose.
- Для gated-моделей (Llama и т.п.) — `HF_TOKEN` в `.env`.

Проверка GPU в контейнере:

```bash
docker run --rm --gpus all nvidia/cuda:12.1.0-base-ubuntu22.04 nvidia-smi
```

## 2. Выбор модели

Модель задаётся одной переменной в `.env`:

```env
LLM_MODEL=Qwen/Qwen2.5-7B-Instruct
VLLM_MODEL=${LLM_MODEL}
```

Сменили модель — поменяли `LLM_MODEL`, перезапустили `llm`-сервис. Код не трогается.

Ориентир по VRAM (fp16, без квантования):

| Модель | VRAM (веса) | Мин. GPU |
|---|---|---|
| Qwen2.5-1.5B-Instruct | ~3 GB | 8 GB |
| Qwen2.5-7B-Instruct | ~16 GB | 24 GB |
| Llama-3.1-8B-Instruct | ~16 GB | 24 GB |
| Qwen2.5-14B-Instruct | ~28 GB | 40 GB |
| Qwen2.5-32B-Instruct | ~64 GB | 80 GB |

Если VRAM впритык — используйте квант (AWQ/GPTQ/GGUF) или уменьшите
`VLLM_MAX_MODEL_LEN` (меньше KV-cache).

## 3. Запуск

1. Скопируйте `.env.example` в `.env`, задайте `LLM_MODEL` и (при необходимости) `HF_TOKEN`.
2. Поднимите стек:

```bash
docker compose up -d --build
```

3. Дождитесь загрузки модели (первый старт может занять минуты — vLLM скачивает веса):

```bash
docker compose logs -f llm
```

4. Проверьте vLLM:

```bash
curl http://localhost:8000/health
curl http://localhost:8000/v1/models
```

5. Проверьте backend:

```bash
curl http://localhost:8000/health   # backend на 8000, vLLM на 8000 внутри контейнера
```

> Порты backend и vLLM в примере оба `8000` — они в разных контейнерах,
> наружу проброшены `${BACKEND_PORT}` и `${VLLM_PORT}`. Если оба на хосте —
> задайте разные значения, например `BACKEND_PORT=8000`, `VLLM_PORT=8001`.

## 4. Как backend ходит к LLM

`llm_client.py` делает `POST ${LLM_BASE_URL}/chat/completions` с телом
OpenAI Chat Completions. Для vLLM ничего дополнительно не нужно.

- `LLM_FALLBACK_ON_ERROR=false` (по умолчанию): при недоступности LLM
  backend возвращает **HTTP 503**, `PromptState` не сохраняется.
- `LLM_FALLBACK_ON_ERROR=true`: включается fallback-генератор из реальных
  метрик (сервис остаётся работоспособным без LLM).

## 5. Смена модели

1. Поменяйте `LLM_MODEL` и `VLLM_MODEL` в `.env`.
2. `docker compose up -d llm` (пересоздаст контейнер с новой моделью).
3. Backend перезапускать не нужно — он читает `LLM_MODEL` только для поля
   `model` в запросе; vLLM принимает любую загруженную модель по `--served-model-name`.

## 6. Локальные веса (без интернета)

Положите веса в `./models/<model-name>` и задайте:

```env
VLLM_MODEL=/models/<model-name>
LLM_MODEL=<model-name>
```

vLLM прочитает локальный путь. Volume `./models:/models` уже смонтирован.

## 7. Типовые проблемы

- **OOM при старте** — уменьшите `VLLM_MAX_MODEL_LEN` или
  `VLLM_GPU_MEMORY_UTILIZATION`, возьмите квант/модель меньше.
- **`/health` не отвечает** — модель ещё грузится (`start_period: 120s`),
  смотрите `docker compose logs llm`.
- **503 от backend** — vLLM недоступен/перегружен; проверьте `llm`-сервис.
- **`nvidia-smi` не видит GPU в контейнере** — не установлен
  `nvidia-container-toolkit` на хосте.
