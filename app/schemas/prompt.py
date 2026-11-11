"""
Pydantic-схемы для контракта prompt.

Этот модуль описывает:
- PromptStateSchema: состояние prompt в БД (без raw, с current_raw_pkg_path).
- PromptResponseSchema: ответ бэкенда с контекстом модели.

Соответствует ТЗ:
prompt = {
    "question": str,
    "raw": np.ndarray,  # в БД хранится как current_raw_pkg_path
    "fs": float,
    "grade": int,
    "context": str,
}
"""

from pydantic import BaseModel, Field
from typing import Optional
from datetime import datetime


class PromptStateSchema(BaseModel):
    """
    Состояние prompt в БД (отображение PromptState).

    Поле raw (ndarray) заменено на current_raw_pkg_path (путь к файлу),
    так как ndarray нельзя сохранить в реляционную БД (требование ТЗ).
    """
    id: int
    session_id: int
    question: Optional[str] = None
    current_raw_pkg_path: Optional[str] = None  # вместо raw
    fs: Optional[float] = None
    grade: Optional[int] = Field(default=None, ge=0, le=10)
    context: Optional[str] = None
    updated_at: datetime

    model_config = {"from_attributes": True}


class PromptResponseSchema(BaseModel):
    """
    Ответ бэкенда на запрос к модели (для UI).

    Содержит:
    - context: сгенерированный текст аннотации.
    - grade: оценка (если выставлена).
    - response_id: идентификатор ответа (для привязки оценки).
    """
    context: str
    grade: Optional[int] = None
    response_id: Optional[int] = None
