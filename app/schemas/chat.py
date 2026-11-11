"""
Pydantic-схемы для API чата.

Эти схемы определяют контракт между UI и бэкендом:
- ChatRequest: что UI отправляет (простая строка text).
- ChatResponse: что бэкенд возвращает (context, response_id, can_grade, can_regenerate).
- GradeRequest: для выставления оценки (0-10) к конкретному ответу.
- RegenerateRequest: для перегенерации ответа.
- AvailablePackage: пакет для UI (id, name, fs).

Соответствует ТЗ:
- "Оценка через сервер" -> GradeRequest с response_id.
- "Кнопки оценки на каждый текст" -> response_id привязывает оценку к ответу.
- "Список файлов при ошибке" -> available_packages в ChatResponse.
"""

from pydantic import BaseModel, Field
from typing import Optional, List


class AvailablePackage(BaseModel):
    """Пакет ЭКГ для UI (отображается в списке выбора)."""
    id: int
    name: str
    fs: Optional[float] = None
    duration: Optional[float] = None
    n_sig: Optional[int] = None


class ChatRequest(BaseModel):
    """
    Запрос от UI.

    UI отправляет простую строку text (например, "\\choose_pkg patient_001 Какие аномалии?").
    Бэкенд парсит её через Resolve-модуль.
    """
    text: str = Field(..., description="Текст от пользователя (может содержать \\choose_pkg)")
    session_id: Optional[int] = Field(None, description="ID сессии (если None — создается новая)")


class ChatResponse(BaseModel):
    """
    Ответ бэкенда для UI.

    Содержит:
    - context: сгенерированный текст аннотации.
    - response_id: идентификатор ответа (для привязки оценки).
    - grade: текущая оценка (если выставлена).
    - can_grade: можно ли оценивать (True после генерации).
    - can_regenerate: можно ли перегенерировать.
    - current_pkg: какой пакет сейчас выбран.
    - available_packages: список пакетов (если \\choose_pkg не найден).
    - message: уведомление (например, "Пакет выбран").
    """
    context: str = Field(..., description="Сгенерированный моделью ответ")
    response_id: Optional[int] = Field(None, description="ID ответа для привязки оценки")
    session_id: Optional[int] = Field(None, description="ID сессии (для последующих запросов)")
    grade: Optional[int] = Field(None, ge=0, le=10, description="Оценка ответа (0-10)")
    can_grade: bool = Field(False, description="Можно ли оценить ответ")
    can_regenerate: bool = Field(False, description="Можно ли перегенерировать")
    current_pkg: Optional[str] = Field(None, description="Текущий выбранный пакет")
    available_packages: Optional[List[AvailablePackage]] = Field(None, description="Список пакетов (при ошибке)")
    message: Optional[str] = Field(None, description="Уведомление для пользователя")


class GradeRequest(BaseModel):
    """Запрос на выставление оценки (режим 4)."""
    response_id: int = Field(..., description="ID ответа, к которому привязывается оценка")
    grade: int = Field(..., ge=0, le=10, description="Оценка от 0 до 10")


class RegenerateRequest(BaseModel):
    """Запрос на перегенерацию ответа (режим 4)."""
    response_id: int = Field(..., description="ID ответа, который нужно перегенерировать")
