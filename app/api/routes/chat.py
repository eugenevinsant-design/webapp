"""
HTTP-роуты для чата (Режимы 1-4).

Эндпоинты:
- POST /api/chat: основной обработчик (Режимы 1-3).
- POST /api/chat/grade: оценка (Режим 4, первый шаг).
- POST /api/chat/regenerate: перегенерация (Режим 4, второй шаг).
"""

import logging
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.schemas.chat import ChatRequest, ChatResponse, GradeRequest, RegenerateRequest
from app.services import chat_service, grade_service, prompt_service
from app.api.deps import get_current_user
from app.models_db import User

logger = logging.getLogger(__name__)
router = APIRouter()


@router.post("/", response_model=ChatResponse)
async def chat_endpoint(
    request: ChatRequest,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> ChatResponse:
    """
    Основной обработчик чата (Режимы 1-3).

    Примеры текста:
    - "\\choose_pkg patient_001 Какие аномалии?" (Режим 1)
    - "\\choose_pkg patient_001" (Режим 2)
    - "Какие аномалии?" (Режим 3)
    """
    try:
        return await chat_service.handle_chat(db, current_user.id, request.text, request.session_id)
    except Exception as e:
        logger.error(f"Ошибка в chat_endpoint: {e}")
        raise HTTPException(status_code=500, detail=f"Внутренняя ошибка: {e}")


@router.post("/grade", response_model=ChatResponse)
async def grade_endpoint(
    request: GradeRequest,
    session_id: int,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> ChatResponse:
    """
    Выставить оценку (0-10) для ответа (Режим 4).

    session_id передается как query-параметр (?session_id=1).
    """
    try:
        return await grade_service.set_grade(db, session_id, request.response_id, request.grade)
    except Exception as e:
        logger.error(f"Ошибка в grade_endpoint: {e}")
        raise HTTPException(status_code=500, detail=f"Внутренняя ошибка: {e}")


@router.post("/regenerate", response_model=ChatResponse)
async def regenerate_endpoint(
    request: RegenerateRequest,
    session_id: int,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> ChatResponse:
    """
    Перегенерировать ответ (Режим 4).

    session_id передается как query-параметр (?session_id=1).
    """
    try:
        return await grade_service.regenerate_response(db, session_id, request.response_id)
    except Exception as e:
        logger.error(f"Ошибка в regenerate_endpoint: {e}")
        raise HTTPException(status_code=500, detail=f"Внутренняя ошибка: {e}")
