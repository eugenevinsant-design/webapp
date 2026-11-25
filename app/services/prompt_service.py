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

    # Создаем новую сессию для конкретного пользователя.
    # PromptState НЕ создаём: по правилу ProductVesrsion0.3 запись в
    # prompt_states появится только после оценки пользователя (через
    # db_writer). Сессию коммитим сразу — это «информация о сессии» из ТЗ
    # и FK-родитель для будущей строки prompt_states.
    new_session = Session(user_id=user_id)
    db.add(new_session)
    await db.commit()
    await db.refresh(new_session)

    logger.info(f"✅ Создана новая сессия {new_session.id} для пользователя {user_id}")
    return new_session


async def get_prompt_state(db: AsyncSession, session_id: int) -> Optional[PromptState]:
    """Загрузить PromptState для сессии (None, если пользователь ещё
    ничего не оценивал — запись появляется только после оценки)."""
    result = await db.execute(select(PromptState).where(PromptState.session_id == session_id))
    return result.scalar_one_or_none()


async def get_user_history(db: AsyncSession, user_id: int, limit: int = 50) -> List[Dict[str, Any]]:
    """Вернуть историю сессий пользователя (последние сверху).

    Каждая запись: session_id, pkg, question, grade, updated_at, excerpt.
    Источник правды — PromptState в БД (а не in-memory кэш).
    """
    result = await db.execute(
        select(Session, PromptState)
        .outerjoin(PromptState, PromptState.session_id == Session.id)
        .where(Session.user_id == user_id)
        .order_by(Session.updated_at.desc())
        .limit(limit)
    )

    history: List[Dict[str, Any]] = []
    for session, state in result.all():
        context = (state.context or "") if state else ""
        excerpt = context.strip().splitlines()[0][:120] if context.strip() else ""
        history.append({
            "session_id": session.id,
            "pkg": state.current_raw_pkg_path if state else None,
            "question": state.question if state else None,
            "description": state.description if state else None,
            "grade": state.grade if state else None,
            "updated_at": session.updated_at.isoformat() if session.updated_at else None,
            "excerpt": excerpt,
        })
    return history


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
