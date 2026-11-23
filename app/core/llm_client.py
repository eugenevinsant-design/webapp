"""
Единая точка выхода к LLM. Два выхода (контракт заморожен):

    generate_annotation_text(annotation_json: dict) -> str   # фаза A
    generate_chat_text(question: str, annotation_json=None, context=None) -> str  # фаза B

LLM обслуживается vLLM (OpenAI-совместимый /v1/chat/completions) на GPU-сервере.
При LLM_FALLBACK_ON_ERROR=false (по умолчанию) любая ошибка LLM
превращается в LLMError -> роут отдаёт HTTP 503. PromptState при этом
не сохраняется (атомарность фазы A).
"""

import logging
from typing import Any, Dict, Optional

import httpx

from app.config import settings

logger = logging.getLogger(__name__)


class LLMError(Exception):
    """Ошибка вызова LLM (пробрасывается при FALLBACK_ON_ERROR=false)."""


async def _chat_completion(messages: list, temperature: float = 0.3) -> str:
    """Вызвать vLLM /v1/chat/completions и вернуть текст ответа."""
    url = f"{settings.LLM_BASE_URL.rstrip('/')}/chat/completions"
    headers = {"Content-Type": "application/json"}
    if settings.LLM_API_KEY:
        headers["Authorization"] = f"Bearer {settings.LLM_API_KEY}"
    payload = {
        "model": settings.LLM_MODEL,
        "messages": messages,
        "temperature": temperature,
    }
    try:
        async with httpx.AsyncClient(timeout=settings.LLM_TIMEOUT) as client:
            r = await client.post(url, json=payload, headers=headers)
        if r.status_code != 200:
            raise LLMError(f"LLM HTTP {r.status_code}: {r.text[:200]}")
        data = r.json()
        return data["choices"][0]["message"]["content"]
    except LLMError:
        raise
    except Exception as e:
        raise LLMError(f"Ошибка LLM ({url}): {e}") from e


# ---------------------------------------------------------------- фаза A

def _fallback_annotation(annotation_json: Dict[str, Any]) -> str:
    """Fallback-отчет фазы A из РЕАЛЬНЫХ метрик (без фантазий)."""
    st = annotation_json.get("statistics") or {}
    anomalies = annotation_json.get("anomalies") or []
    parts = ["## Аннотация ЭКГ", ""]
    hr = st.get("hr_bpm")
    if hr is None:
        parts.append("Качество сигнала недостаточно для анализа ритма: R-пики не выделены достоверно.")
    else:
        if hr < 60:
            rhythm = "брадикардия"
        elif hr > 100:
            rhythm = "тахикардия"
        else:
            rhythm = "нормокардия"
        parts.append(f"Частота сердечных сокращений **{hr} уд/мин** — {rhythm}.")
        if st.get("sdnn_ms") is not None:
            parts.append(f"Вариабельность ритма: SDNN {st['sdnn_ms']} мс, RMSSD {st.get('rmssd_ms')} мс.")
    if anomalies:
        parts.append("")
        parts.append(f"**Выявленные особенности ({len(anomalies)}):**")
        for a in anomalies:
            parts.append(f"- {a['type']} ({a['severity']}): {a['description']}")
    else:
        parts.append("")
        parts.append("Значимых отклонений ритма по доступным метрикам не выявлено.")
    parts.append("")
    parts.append("Задайте вопросы по этой аннотации — отвечу без повторного анализа сигнала.")
    return "\n".join(parts)


async def generate_annotation_text(annotation_json: Dict[str, Any]) -> str:
    """Фаза A: связный текст аннотации по структурированным данным ML."""
    prompt = (
        "Ты — ассистент-кардиолог. Составь краткую связную аннотацию ЭКГ "
        "в Markdown строго по приведенным данным. НЕ выдумывай числа.\n\n"
        f"Данные аннотации:\n{annotation_json}"
    )
    try:
        return await _chat_completion([{"role": "user", "content": prompt}], temperature=0.3)
    except LLMError as e:
        if not settings.LLM_FALLBACK_ON_ERROR:
            raise
        logger.warning(f"LLM недоступна ({e}), использую fallback")
        return _fallback_annotation(annotation_json)


# ---------------------------------------------------------------- фаза B

def _fallback_chat(question: str, context: str) -> str:
    """Fallback-ответ фазы B: ответы ТОЛЬКО по тексту аннотации."""
    q = (question or "").lower()
    if "частот" in q or "чсс" in q or "пульс" in q:
        import re
        m = re.search(r"(\d+[.,]?\d*)\s*(?:уд/мин|bpm)", context)
        if m:
            return f"По аннотации этого сигнала ЧСС {m.group(1).replace(',', '.')} уд/мин. Уточните, что интересует подробнее."
    if "аномал" in q or "отклонен" in q or "патолог" in q:
        if "не выявлено" in context or "не обнаружено" in context:
            return "В аннотации значимых отклонений ритма не отмечено. Вопросы по другим аспектам сигнала?"
    if "вариабельн" in q or "rr" in q.lower() or "sdnn" in q.lower() or "rmssd" in q.lower():
        if "SDNN" in context or "RMSSD" in context:
            for line in context.splitlines():
                if "SDNN" in line or "RMSSD" in line:
                    return f"По аннотации: {line.strip('- *').strip()}"
    return (
        "Аннотация по этому сигналу уже построена выше. "
        "Уточните, какой именно ее раздел разобрать подробнее — "
        "частоту ритма, вариабельность или найденные особенности."
    )


async def generate_chat_text(
    question: str,
    annotation_json: Optional[Dict[str, Any]] = None,
    context: Optional[str] = None,
) -> str:
    """
    Фаза B: разговор по готовой аннотации. ML не вызывается.

    Args:
        question: вопрос пользователя.
        annotation_json: структурированная аннотация (если доступна).
        context: предыдущий ответ (аннотация или прошлый ответ чата).
    """
    system = (
        "Ты — ассистент по анализу ЭКГ. Отвечай ТОЛЬКО на основе "
        "данной аннотации. Не выдумывай данные и не делай медицинских "
        "диагнозов. Если данных не хватает — так и скажи."
    )
    user = f"Аннотация:\n{annotation_json or context or ''}\n\nВопрос: {question}"
    messages = [
        {"role": "system", "content": system},
        {"role": "user", "content": user},
    ]
    try:
        return await _chat_completion(messages, temperature=0.3)
    except LLMError as e:
        if not settings.LLM_FALLBACK_ON_ERROR:
            raise
        logger.warning(f"LLM недоступна ({e}), использую fallback")
        return _fallback_chat(question, context or "")
