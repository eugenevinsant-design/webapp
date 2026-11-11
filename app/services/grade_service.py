"""
GradeService: оценка и перегенерация (Режим 4 из ТЗ).

ТЗ требует строгий порядок:
1. Сначала оценка (0-10).
2. Затем предложение перегенерировать.

Единственные поля, которые меняются: grade и context.
"""

import logging
from typing import Optional

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.ecg_loader import ecg_loader
from app.infrastructure import nn_pipeline
from app.schemas.chat import ChatResponse
from app.services import prompt_service

logger = logging.getLogger(__name__)


async def set_grade(db: AsyncSession, session_id: int, response_id: int, grade: int) -> ChatResponse:
    """
    Выставить оценку (0-10) и предложить перегенерацию.

    Меняется только поле grade.
    После оценки can_regenerate становится True (порядок из ТЗ).
    """
    state = await prompt_service.get_prompt_state(db, session_id)
    if not state or state.id != response_id:
        return ChatResponse(
            context="Ответ не найден или не принадлежит этой сессии.",
            can_grade=False,
            can_regenerate=False,
        )

    # ТЗ: сначала оценка
    state.grade = grade
    await prompt_service.save_prompt_state(db, state)

    return ChatResponse(
        context=state.context or "",
        response_id=state.id,
        session_id=session_id,
        grade=grade,
        can_grade=False,      # оценка уже поставлена
        can_regenerate=True,  # теперь можно перегенерировать
        current_pkg=state.current_raw_pkg_path,
        message=f"Оценка {grade}/10 сохранена. Можно перегенерировать ответ.",
    )


async def regenerate_response(db: AsyncSession, session_id: int, response_id: int) -> ChatResponse:
    """
    Перегенерировать ответ (Режим 4).

    Меняется только поле context (grade сбрасывается в None).
    question и raw не меняются (по ТЗ).
    """
    state = await prompt_service.get_prompt_state(db, session_id)
    if not state or state.id != response_id:
        return ChatResponse(
            context="Ответ не найден или не принадлежит этой сессии.",
            can_grade=False,
            can_regenerate=False,
        )

    if not state.current_raw_pkg_path:
        return ChatResponse(
            context="Пакет не выбран. Нельзя перегенерировать.",
            can_grade=False,
            can_regenerate=False,
        )

    # Загружаем raw (для NN)
    raw, fs = ecg_loader.load_raw_signal(state.current_raw_pkg_path)
    if raw is None:
        return ChatResponse(
            context="Ошибка загрузки сигнала для перегенерации.",
            can_grade=False,
            can_regenerate=False,
        )

    # Перегенерация: question и raw не меняются
    prompt_dict = prompt_service.to_prompt_dict(state, raw=raw)
    try:
        new_context = await nn_pipeline.generate_response(prompt_dict)
        state.context = new_context
        state.grade = None  # сброс оценки
        await prompt_service.save_prompt_state(db, state)

        return ChatResponse(
            context=new_context,
            response_id=state.id,
            session_id=session_id,
            grade=None,
            can_grade=True,       # можно оценить заново
            can_regenerate=False, # сначала оценка
            current_pkg=state.current_raw_pkg_path,
            message="Ответ перегенерирован. Оцените новый ответ.",
        )
    except Exception as e:
        logger.error(f"Ошибка перегенерации: {e}")
        return ChatResponse(
            context=f"Ошибка перегенерации: {e}",
            can_grade=False,
            can_regenerate=False,
        )
