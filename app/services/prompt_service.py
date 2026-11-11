"""
Сервис для работы с состоянием prompt в БД.

Этот слой отвечает только за БД (SQLAlchemy). Он не знает про wfdb,
нейросеть или HTTP-роуты. Список пакетов передается извне (из chat_service).

Соответствует ТЗ:
- "Перед каждым новым запросом prompt сохраняется в БД".
- "Атомарность: ни одно поле не меняется, пока промт не составлен корректно".
- "Вместо raw хранится путь до файла".
"""

import logging
from typing import Optional, List, Dict, Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models_db import Session, PromptState, User
from app.schemas.chat import AvailablePackage

logger = logging.getLogger(__name__)


async def get_or_create_session(db: AsyncSession, user_id: int, session_id: Optional[int] = None) -> Session:
    """
    Найти сессию по ID или создать новую для конкретного пользователя.

    Args:
        db: сессия БД.
        user_id: ID авторизованного пользователя.
        session_id: ID существующей сессии (или None).

    Returns:
        Session: найденная или созданная сессия.
    """
    if session_id is not None:
        result = await db.execute(
            select(Session).where(Session.id == session_id, Session.user_id == user_id)
        )
        session = result.scalar_one_or_none()
        if session:
            return session
        logger.warning(f"Сессия {session_id} не найдена для пользователя {user_id}, создаем новую")

    # Создаем новую сессию для конкретного пользователя
    new_session = Session(user_id=user_id)
    db.add(new_session)
    await db.flush()  # чтобы получить session.id

    # Создаем пустой PromptState для сессии
    prompt_state = PromptState(session_id=new_session.id)
    db.add(prompt_state)
    await db.flush()

    logger.info(f"✅ Создана новая сессия {new_session.id} для пользователя {user_id}")
    return new_session


async def get_prompt_state(db: AsyncSession, session_id: int) -> Optional[PromptState]:
    """Загрузить PromptState для сессии."""
    result = await db.execute(select(PromptState).where(PromptState.session_id == session_id))
    return result.scalar_one_or_none()


async def save_prompt_state(db: AsyncSession, state: PromptState) -> None:
    """Сохранить изменения PromptState в БД (commit)."""
    db.add(state)
    await db.commit()
    await db.refresh(state)
    logger.info(f"💾 PromptState сохранен (session_id={state.session_id})")


def to_prompt_dict(state: PromptState, raw=None) -> Dict[str, Any]:
    """
    Собрать prompt-словарь для передачи в NN-пайплайн.

    Args:
        state: PromptState из БД.
        raw: ndarray (если нужно передать сигнал) или None.

    Returns:
        dict: prompt-словарь по контракту ТЗ.
    """
    return {
        "question": state.question or "",
        "raw": raw,
        "fs": state.fs,
        "grade": state.grade,
        "context": state.context or "",
    }


def available_packages_to_schema(packages: List[Dict[str, Any]]) -> List[AvailablePackage]:
    """Преобразовать список пакетов из ecg_loader в Pydantic-схему для UI."""
    return [
        AvailablePackage(
            id=p.get("id"),
            name=p.get("name"),
            fs=p.get("fs"),
            duration=p.get("duration"),
            n_sig=p.get("n_sig"),
        )
        for p in packages
    ]
