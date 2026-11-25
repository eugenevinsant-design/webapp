"""
SQLAlchemy-модели для хранения состояния сервиса-аннотатора ЭКГ.

Этот модуль определяет структуру таблиц БД, которая позволяет сохранять
состояние prompt между запросами пользователя (требование ТЗ: "Перед каждым
новым запросом пользователя prompt должен сохраняться в БД").

ВАЖНО: Вместо поля raw (numpy.ndarray) мы храним current_raw_pkg_path —
путь к файлу внутри локального хранилища. Это позволяет в любой момент
восстановить raw через wfdb, но при этом не пытаться сохранить бинарный
массив в реляционную БД.
"""

from sqlalchemy import Column, Integer, String, Float, Text, DateTime, ForeignKey
from sqlalchemy.orm import relationship
from datetime import datetime, timezone


def _utcnow() -> datetime:
    """Timezone-aware UTC-время (datetime.utcnow deprecated с Python 3.12)."""
    return datetime.now(timezone.utc)

# Импортируем Base из database.py, чтобы init_db() (create_all) увидел эти модели.
# Это техническое условие для выполнения требования ТЗ:
# "prompt должен сохраняться в БД" -> таблицы должны быть созданы.
from app.database import Base


class User(Base):
    """
    Таблица пользователей.

    ТЗ требует: "В БД должна быть информация о пользователе, сессии".
    Пока что мы не делаем полноценную аутентификацию, но структура
    готова для ее добавления (username, created_at).
    """
    __tablename__ = "users"

    id = Column(Integer, primary_key=True, autoincrement=True)
    username = Column(String(100), unique=True, nullable=False, index=True)
    api_token = Column(String(255), unique=True, nullable=True, index=True)  # Токен для входа
    created_at = Column(DateTime(timezone=True), default=_utcnow, nullable=False)

    # Связь один-ко-многим: у пользователя может быть несколько сессий
    sessions = relationship("Session", back_populates="user", cascade="all, delete-orphan")

    def __repr__(self):
        return f"<User(id={self.id}, username='{self.username}')>"


class Session(Base):
    """
    Таблица сессий пользователя.

    Каждая сессия — это отдельный диалог (например, отдельная вкладка в UI).
    ТЗ требует изоляцию состояния для каждой сессии конкретного пользователя
    (см. раздел про ContextVar в README_ARCHITECTURE.md).

    В одной сессии хранится один текущий prompt (см. PromptState ниже).
    """
    __tablename__ = "sessions"

    id = Column(Integer, primary_key=True, autoincrement=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False, index=True)
    created_at = Column(DateTime(timezone=True), default=_utcnow, nullable=False)
    updated_at = Column(DateTime(timezone=True), default=_utcnow, onupdate=_utcnow, nullable=False)

    # Связь с пользователем
    user = relationship("User", back_populates="sessions")
    # Связь с состоянием prompt (один-к-одному, так как в сессии один текущий prompt)
    prompt_state = relationship("PromptState", back_populates="session", uselist=False, cascade="all, delete-orphan")

    def __repr__(self):
        return f"<Session(id={self.id}, user_id={self.user_id})>"


class PromptState(Base):
    """
    Таблица состояния prompt для конкретной сессии.

    Поля соответствуют контракту prompt из ТЗ:
    - question: текст вопроса пользователя
    - current_raw_pkg_path: путь к файлу ЭКГ (вместо raw, так как ndarray
      нельзя сохранить в реляционную БД)
    - fs: частота дискретизации из header wfdb (None в режиме 2)
    - description: ML-описание сигнала (JSON с метриками: ЧСС, RR, аномалии) —
      «данные ML», на основе которых LLM строит ответ
    - grade: оценка ответа модели (0-10, None пока не выставлена)
    - context: сгенерированный моделью ответ

    ВАЖНО (ProductVesrsion0.3): запись в эту таблицу происходит ТОЛЬКО
    после того, как пользователь выставил оценку (режим 4). До оценки
    состояние живёт в памяти (app/services/pending_store.py). Запись
    выполняет асинхронный писатель (app/services/db_writer.py), поэтому
    строка всегда содержит слепок на момент оценки: user_id + session_id +
    question + description + context + grade.
    """
    __tablename__ = "prompt_states"

    id = Column(Integer, primary_key=True, autoincrement=True)
    session_id = Column(Integer, ForeignKey("sessions.id"), nullable=False, unique=True, index=True)

    # Владелец сессии — денормализация для быстрых выборок «все действия
    # пользователя» без JOIN по sessions (user_id + session_id = пара индексов)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=True, index=True)

    # Текст вопроса пользователя (режимы 1, 3)
    question = Column(Text, nullable=True)

    # Путь к файлу ЭКГ внутри локального хранилища (вместо raw)
    # Обновляется при \choose_pkg (режимы 1, 2)
    current_raw_pkg_path = Column(String(500), nullable=True)

    # Частота дискретизации из header wfdb (None в режиме 2)
    fs = Column(Float, nullable=True)

    # ML-описание сигнала: JSON-строка с annotation_json из ml_adapter
    # (statistics: ЧСС/RR/SDNN/RMSSD + anomalies). Это «факты», которые
    # передаются в LLM. Заполняется в фазе A, дальше не меняется.
    description = Column(Text, nullable=True)

    # Оценка ответа модели (0-10), выставляется пользователем в режиме 4
    # None означает, что оценка еще не выставлена
    grade = Column(Integer, nullable=True)

    # Сгенерированный моделью ответ (режимы 3, 4)
    context = Column(Text, nullable=True)

    # Время последнего обновления состояния
    updated_at = Column(DateTime(timezone=True), default=_utcnow, onupdate=_utcnow, nullable=False)

    # Связь с сессией
    session = relationship("Session", back_populates="prompt_state")

    def __repr__(self):
        return f"<PromptState(session_id={self.session_id}, question='{self.question[:30] if self.question else None}')>"
