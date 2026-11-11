"""
Заглушка нейросети (NN Pipeline).

Этот модуль имитирует работу нейросети. Когда придет реальная модель,
нужно будет заменить только внутренности функции generate_response,
не трогая остальной код (сервисы, API, БД).

Контракт (ТЗ):
    Вход: prompt = {
        "question": str,       # вопрос пользователя
        "raw": np.ndarray,     # ЭКГ-сигнал (12 каналов) или None
        "fs": float,           # частота дискретизации или None
        "grade": int,          # оценка (не используется при генерации)
        "context": str,        # предыдущий ответ (не используется)
    }
    Выход: str  # сгенерированный текст (context)

Как заменить на реальную модель:
1. Установите зависимости (torch, transformers и т.д.) в requirements.txt.
2. Замените тело функции generate_response на вызов вашей модели:
   model = load_model()
   result = model.predict(prompt["raw"], prompt["question"])
   return result
3. НЕ меняйте сигнатуру функции (prompt: dict -> str) и НЕ меняйте
   контракт prompt. Остальной код (ChatService, API) уже настроен под него.
"""

import logging
import random
from typing import Optional

logger = logging.getLogger(__name__)


async def generate_response(prompt: dict) -> str:
    """
    Сгенерировать ответ модели на вопрос пользователя.

    Args:
        prompt: Словарь с полями:
            - question (str): текст вопроса пользователя.
            - raw (np.ndarray | None): ЭКГ-сигнал (12 каналов) или None (режим 2).
            - fs (float | None): частота дискретизации.
            - grade (int | None): оценка (не используется).
            - context (str | None): предыдущий ответ (не используется).

    Returns:
        str: Сгенерированный текст (context).

    Raises:
        ValueError: если question пустой.
    """
    question = prompt.get("question", "").strip()
    raw = prompt.get("raw")
    fs = prompt.get("fs")

    if not question:
        raise ValueError("Поле question не может быть пустым для генерации ответа")

    logger.info(f"🧠 [MOCK] Генерация ответа на вопрос: '{question[:50]}...'")

    # Если raw = None (режим 2: только выбор пакета), возвращаем уведомление
    if raw is None:
        return (
            "📦 Пакет выбран. Задайте вопрос по этому сигналу, "
            "чтобы получить аннотацию."
        )

    # Имитация работы нейросети (задержка + генерация текста)
    # В реальной модели здесь будет вызов model.predict(...)
    import asyncio
    await asyncio.sleep(0.5)  # имитация времени инференса

    # Формируем псевдо-ответ на основе вопроса и данных сигнала
    # (в реальной модели здесь будет настоящий анализ)
    n_channels = raw.shape[1] if hasattr(raw, "shape") and len(raw.shape) > 1 else "N/A"
    signal_length = raw.shape[0] if hasattr(raw, "shape") else "N/A"

    mock_anomalies = [
        "незначительное отклонение ST-сегмента",
        "единичный экстрасистолический комплекс",
        "умеренная тахикардия",
        "артефакт движения (низкая амплитуда)",
    ]
    anomaly = random.choice(mock_anomalies)

    response = (
        f"## 📊 Аннотация ЭКГ\n\n"
        f"**Вопрос:** {question}\n\n"
        f"**Параметры сигнала:**\n"
        f"- Каналов: {n_channels}\n"
        f"- Длина записи: {signal_length} отсчетов\n"
        f"- Частота дискретизации: {fs} Гц\n\n"
        f"**Результат анализа (заглушка):**\n"
        f"Обнаружено: {anomaly}.\n\n"
        f"*Это ответ-заглушка. Реальная модель будет выдавать здесь "
        f"клиническую аннотацию на основе 12-канального сигнала.*"
    )

    logger.info(f"🧠 [MOCK] Ответ сгенерирован (длина: {len(response)} символов)")
    return response
