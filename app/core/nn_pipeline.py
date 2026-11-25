"""
NN Pipeline: фазовая логика.

Контракт (НЕ МЕНЯТЬ, на него завязаны chat_service и grade_service):
    generate_response(prompt: dict) -> str

Фазы:
    Фаза A (аннотация): raw задан -> ML-анализ сигнала -> аннотация.
        ML вызывается РОВНО ОДИН РАЗ на сигнал.
    Фаза B (чат): raw=None, context задан -> ответ LLM только по аннотации.

Второй контракт (для прямого построения аннотации):
    generate_annotation(prompt: dict) -> str
"""

import logging

from app.core import ml_adapter
from app.core import llm_client

logger = logging.getLogger(__name__)


async def generate_annotation(prompt: dict) -> str:
    """
    Фаза A: построить аннотацию сигнала через ML + LLM.

    Вызывается когда prompt["raw"] не None. Структуру возвращает текстом
    (Markdown), структурированные данные ML остаются внутри пакета.
    """
    raw = prompt.get("raw")
    fs = prompt.get("fs")
    if raw is None:
        raise ValueError("generate_annotation требует raw (фаза A)")

    pkg = ml_adapter.analyze_signal(raw, fs)
    logger.info(
        "Фаза A: ML=%s, ЧСС=%s, аномалий=%d",
        pkg.get("model"),
        (pkg.get("annotation_json") or {}).get("statistics", {}).get("hr_bpm"),
        len(pkg.get("anomalies") or []),
    )
    return await llm_client.generate_annotation_text(pkg["annotation_json"])


async def generate_response(prompt: dict) -> str:
    """
    Главная точка входа нейросети.

    Args:
        prompt: {question, raw, fs, grade, context}
            - question: вопрос пользователя (обязателен);
            - raw: сигнал [C, N] (фаза A) или None (фаза B);
            - fs: частота дискретизации;
            - grade: оценка (не используется при генерации);
            - context: предыдущий ответ (аннотация/чат).

    Returns:
        str: сгенерированный текст (context).

    Raises:
        ValueError: если question пуст.
    """
    question = (prompt.get("question") or "").strip()
    if not question:
        raise ValueError("Поле question не может быть пустым для генерации ответа")

    raw = prompt.get("raw")
    fs = prompt.get("fs")
    context = prompt.get("context")

    # Фаза A: есть сигнал -> ML-анализ + аннотация (ML вызывается один раз)
    if raw is not None:
        return await generate_annotation({"raw": raw, "fs": fs})

    # Фаза B: сигнала нет, но аннотация уже в контексте -> чистый чат с LLM
    if context:
        return await llm_client.generate_chat_text(
            question,
            context=context,
            regenerate=bool(prompt.get("regenerate")),
        )

    # Защитный случай: нет ни сигнала, ни аннотации — это не ответ,
    # а ошибка вызова (роуты отдадут 500; заглушек-текстов нет)
    raise ValueError("generate_response: нет ни raw (фаза A), ни context (фаза B)")
