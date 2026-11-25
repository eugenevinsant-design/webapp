"""
Мост между webapp и нашим LLM-модулем (ecgllm).

WaveDescriptorInferencePiepeline создаётся один раз (singleton) и
конфигурируется через setup_llm(...) атрибутами API-модели из settings:

    LLM_BASE_URL / LLM_MODEL / LLM_API_KEY  ->  setup_llm(url, name, api_key)

Используется ТОЛЬКО process_text (chat): и фаза A (аннотация), и фаза B
(вопрос по аннотации) — это текстовые запросы к core LLM.
process_wave / process_description (narrator + features mixer) здесь не
подключаются — они требуют torch-стек и веса backbone'ов.

Активируется настройкой LLM_VIA_MODULE=true (см. app/config.py).
При false llm_client работает напрямую через httpx, как раньше.
"""

import asyncio
import logging
from typing import Any, Dict, List, Optional

from app.config import settings

logger = logging.getLogger(__name__)

_pipeline = None


def get_pipeline():
    """Ленивый singleton WaveDescriptorInferencePiepeline (text-only режим)."""
    global _pipeline
    if _pipeline is None:
        from ecgllm.llm.pipeline import (
            WaveDescriptorInferencePiepeline,
            GenerationParams,
        )

        # repo_id не передаём: features mixer (torch/timm) не нужен,
        # работаем только с process_text
        pipe = WaveDescriptorInferencePiepeline()
        pipe.setup_llm(
            url=settings.LLM_BASE_URL,
            name=settings.LLM_MODEL,
            mode="core",
            api_key=settings.LLM_API_KEY or None,
            gen_cfg=GenerationParams(
                temperature=0.3,
                max_new_tokens=settings.LLM_MAX_TOKENS,
            ),
        )
        logger.info(
            "ecgllm pipeline: core LLM настроен через setup_llm "
            "(url=%s, model=%s)",
            settings.LLM_BASE_URL,
            settings.LLM_MODEL,
        )
        _pipeline = pipe
    return _pipeline


def _messages_to_text(messages: List[Dict[str, Any]]) -> str:
    """Свести chat-messages в один текст для process_text.

    Системная инструкция webapp (если есть) добавляется в начало текста —
    своя системная роль ("general-core" из roles.json) подставляется
    самим pipeline.process_text.
    """
    system_parts = [str(m.get("content", "")) for m in messages
                    if m.get("role") == "system" and m.get("content")]
    user_parts = [str(m.get("content", "")) for m in messages
                  if m.get("role") != "system" and m.get("content")]
    text = "\n\n".join(user_parts)
    if system_parts:
        text = "\n".join(system_parts) + "\n\n" + text
    return text


async def chat_completion(messages: List[Dict[str, Any]],
                          temperature: float = 0.3) -> str:
    """Асинхронная обёртка над pipeline.process_text.

    Синхронный OpenAI-клиент модуля вызывается в отдельном потоке,
    чтобы не блокировать event loop FastAPI.
    """
    from ecgllm.llm.pipeline import WaveDescriptionPrompt, GenerationParams

    pipe = get_pipeline()
    pipe.set_llm_generation_cfg(
        "core",
        GenerationParams(temperature=temperature,
                         max_new_tokens=settings.LLM_MAX_TOKENS),
    )
    prompt = WaveDescriptionPrompt(text=_messages_to_text(messages))
    prompt = await asyncio.wait_for(
        asyncio.to_thread(pipe.process_text, prompt=prompt),
        timeout=settings.LLM_TIMEOUT,
    )
    return prompt.text_response or ""


def llm_status() -> Dict[str, Any]:
    """Статус интеграции для фронтенда (GET /api/chat/llm-status)."""
    configured = False
    if settings.LLM_VIA_MODULE:
        try:
            get_pipeline()  # setup_llm не ходит в сеть — безопасно при опросе
            configured = True
        except Exception as e:
            logger.warning("llm_status: pipeline не настроен: %s", e)
    return {
        "via_module": bool(settings.LLM_VIA_MODULE),
        "configured": configured,
        "mode": "core",
        "url": settings.LLM_BASE_URL,
        "model": settings.LLM_MODEL,
        "api_key_set": bool(settings.LLM_API_KEY),
        "max_tokens": settings.LLM_MAX_TOKENS,
    }
