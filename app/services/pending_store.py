"""
Pending Store: состояние prompt в памяти ДО оценки пользователя.

Правило ProductVesrsion0.3: в таблицу prompt_states данные попадают
ТОЛЬКО после того, как пользователь выставил оценку. До этого момента
все действия (выбор пакета, анализ, вопросы, перегенерации) живут в
памяти — в этом модуле.

Поток:
1. chat_service меняет PendingState (вопрос/пакет/ответ/description) —
   в БД ничего не пишется.
2. grade_service.set_grade ставит оценку, делает snapshot() и кладёт
   его в db_writer (асинхронная запись).
3. Перегенерация снова меняет только память; следующая оценка снова
   уходит в db_writer (upsert той же строки по session_id).

После рестарта сервера память пуста — get() гидрирует состояние из БД
(последняя оценённая запись), чтобы перегенерация/оценка продолжали
работать.

version — монотонный счётчик генераций ответа; используется как
response_id в API. Оценить/перегенерировать можно только ПОСЛЕДНИЙ
ответ (response_id == version) — это защита от гонок двойных кликов.
"""

import asyncio
import logging
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Dict, Optional

from sqlalchemy.ext.asyncio import AsyncSession

from app.services import prompt_service

logger = logging.getLogger(__name__)


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


@dataclass
class PendingState:
    """Текущее (ещё не записанное в БД) состояние prompt сессии."""

    user_id: int
    session_id: int
    question: Optional[str] = None
    pkg_path: Optional[str] = None
    fs: Optional[float] = None
    # ML-описание сигнала (JSON-строка annotation_json) — «факты» для LLM
    description: Optional[str] = None
    context: Optional[str] = None
    grade: Optional[int] = None
    # Счётчик генераций ответа = response_id для API
    version: int = 0
    updated_at: datetime = field(default_factory=_utcnow)

    def touch(self) -> None:
        self.updated_at = _utcnow()

    def snapshot(self) -> Dict[str, Any]:
        """Немутируемый слепок для асинхронной записи в БД."""
        return {
            "user_id": self.user_id,
            "session_id": self.session_id,
            "question": self.question,
            "pkg_path": self.pkg_path,
            "fs": self.fs,
            "description": self.description,
            "context": self.context,
            "grade": self.grade,
        }


class PendingStore:
    """In-memory хранилище PendingState по session_id (+ per-session локи)."""

    def __init__(self) -> None:
        self._states: Dict[int, PendingState] = {}
        self._locks: Dict[int, asyncio.Lock] = {}
        # Локи создаём ЛЕНИВО в текущем event loop: asyncio.Lock при первом
        # acquire привязывается к loop, а тесты поднимают новый loop на
        # каждый тест — переиспользованный лок привёл бы к зависанию.
        self._global_lock: Optional[asyncio.Lock] = None
        self._global_lock_loop: Optional[asyncio.AbstractEventLoop] = None

    async def get_lock(self, session_id: int) -> asyncio.Lock:
        """Лок на сессию: сериализуем параллельные запросы одного пользователя."""
        loop = asyncio.get_running_loop()
        if self._global_lock is None or self._global_lock_loop is not loop:
            self._global_lock = asyncio.Lock()
            self._global_lock_loop = loop
            self._locks = {}  # локи старого loop больше не валидны
        async with self._global_lock:
            if session_id not in self._locks:
                self._locks[session_id] = asyncio.Lock()
            return self._locks[session_id]

    async def get(self, db: AsyncSession, user_id: int, session_id: int) -> PendingState:
        """Вернуть состояние сессии: из памяти, иначе гидрировать из БД.

        Args:
            db: сессия БД (нужна только для гидрации после рестарта).
            user_id: владелец (для новых состояний и проверки).
            session_id: ID сессии.
        """
        state = self._states.get(session_id)
        if state is not None:
            return state

        # Гидрация из БД: последняя оценённая запись (если была)
        row = await prompt_service.get_prompt_state(db, session_id)
        state = PendingState(user_id=user_id, session_id=session_id)
        if row is not None:
            state.question = row.question
            state.pkg_path = row.current_raw_pkg_path
            state.fs = row.fs
            state.description = row.description
            state.context = row.context
            state.grade = row.grade
            state.user_id = row.user_id or user_id
            # После гидрации version=1: ответ из БД считается «последним»
            state.version = 1 if row.context else 0
            logger.info("PendingState гидрирован из БД (session_id=%s)", session_id)
        self._states[session_id] = state
        return state

    def clear(self) -> None:
        """Полный сброс (для тестов)."""
        self._states.clear()
        self._locks.clear()
        self._global_lock = None
        self._global_lock_loop = None


# Глобальный синглтон
pending_store = PendingStore()


def to_prompt_dict(state: PendingState, raw=None) -> Dict[str, Any]:
    """Собрать prompt-словарь для NN-пайплайна из PendingState."""
    return {
        "question": state.question or "",
        "raw": raw,
        "fs": state.fs,
        "grade": state.grade,
        "context": state.context or "",
    }
