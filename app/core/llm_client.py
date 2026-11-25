"""
Единая точка выхода к LLM. Два выхода (контракт заморожен):

    generate_annotation_text(annotation_json: dict) -> str   # фаза A
    generate_chat_text(question: str, annotation_json=None, context=None) -> str  # фаза B

Ответы формирует ТОЛЬКО LLM — никаких fallback-заглушек:
любая ошибка LLM превращается в LLMError -> роут отдаёт HTTP 503.
PromptState при этом не сохраняется (атомарность фазы A).

Путь вызова:
    LLM_VIA_MODULE=true  -> наш модуль ecgllm
                            (WaveDescriptorInferencePiepeline.setup_llm
                             + process_text), см. app/core/ecgllm_bridge.py
    LLM_VIA_MODULE=false -> напрямую OpenAI-совместимый
                            /v1/chat/completions через httpx (как раньше)
"""

import logging
from typing import Any, Dict, Optional

import httpx

from app.config import settings

logger = logging.getLogger(__name__)


class LLMError(Exception):
    """Ошибка вызова LLM (пробрасывается в роут -> HTTP 503)."""


async def _chat_completion(messages: list, temperature: float = 0.3) -> str:
    """Вызвать LLM и вернуть текст ответа."""
    if settings.LLM_VIA_MODULE:
        from app.core import ecgllm_bridge
        try:
            return await ecgllm_bridge.chat_completion(messages, temperature)
        except LLMError:
            raise
        except Exception as e:
            raise LLMError(f"Ошибка LLM через ecgllm process_text "
                           f"({settings.LLM_BASE_URL}): {e}") from e

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

async def generate_annotation_text(annotation_json: Dict[str, Any]) -> str:
    """Фаза A: LLM строит аннотацию по РЕАЛЬНЫМ метрикам сигнала.

    Первая версия ответа — СТРОГО по медицинскому шаблону (перегенерация
    позже даст свободный вариант, см. generate_chat_text(regenerate=True)).
    """
    messages = [
        {
            "role": "system",
            "content": (
                "Ты — ассистент-кардиолог. Составь аннотацию ЭКГ в Markdown "
                "СТРОГО по шаблону ниже, используя только приведённые "
                "реальные метрики сигнала. НЕ выдумывай числа. Шаблон:\n"
                "## Аннотация ЭКГ\n"
                "### 1. Общие параметры записи — длительность, частота "
                "дискретизации, число отведений, число RR-комплексов.\n"
                "### 2. Ритм и ЧСС — значение ЧСС с оценкой нормы "
                "(60–100 уд/мин), средний RR, регулярность ритма.\n"
                "### 3. Вариабельность ритма — SDNN и RMSSD с указанием "
                "норм и интерпретацией.\n"
                "### 4. Обнаруженные аномалии — список из входных данных "
                "или «не выявлено».\n"
                "### 5. Заключение — краткий вывод и пометка, что выводы "
                "должен подтвердить врач-кардиолог."
            ),
        },
        {
            "role": "user",
            "content": f"Метрики анализа ЭКГ-сигнала:\n{annotation_json}",
        },
    ]
    return await _chat_completion(messages, temperature=0.3)


# ---------------------------------------------------------------- фаза B

async def generate_chat_text(
    question: str,
    annotation_json: Optional[Dict[str, Any]] = None,
    context: Optional[str] = None,
    regenerate: bool = False,
) -> str:
    """
    Фаза B: разговор по готовой аннотации. ML не вызывается.

    Args:
        question: вопрос пользователя.
        annotation_json: структурированная аннотация (если доступна).
        context: предыдущий ответ (аннотация или прошлый ответ чата).
        regenerate: True при перегенерации — просим НОВЫЙ вариант ответа
            (другая структура/формулировки) и повышаем температуру,
            иначе при тех же входных данных модель вернет почти тот же текст.
    """
    system = (
        "Ты — ассистент по анализу ЭКГ. Отвечай на вопрос пользователя "
        "ТОЛЬКО на основе данной аннотации. Не выдумывай данные и не делай "
        "медицинских диагнозов. Если данных не хватает — так и скажи. "
        "Не пересказывай аннотацию целиком — отвечай именно на вопрос."
    )
    if regenerate:
        # Второй вариант: свободная форма, но строго медицинская тематика
        system += (
            " Сейчас дай НОВЫЙ вариант ответа в СВОБОДНОЙ форме: живой "
            "связный текст без жёсткого шаблона и таблиц, не повторяй "
            "прежний ответ. Оставайся строго в медицинской тематике "
            "(ЭКГ, кардиология) и опирайся только на данные аннотации."
        )
    user = f"Аннотация:\n{annotation_json or context or ''}\n\nВопрос: {question}"
    messages = [
        {"role": "system", "content": system},
        {"role": "user", "content": user},
    ]
    return await _chat_completion(messages, temperature=0.8 if regenerate else 0.3)
