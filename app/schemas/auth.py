"""
Pydantic-схемы для аутентификации.
"""

from pydantic import BaseModel, Field


class RegisterRequest(BaseModel):
    """Запрос на регистрацию (ник)."""
    username: str = Field(..., min_length=3, max_length=50, description="Ник пользователя")


class RegisterResponse(BaseModel):
    """Ответ на регистрацию (токен показывается один раз)."""
    user_id: int
    username: str
    api_token: str = Field(..., description="Сохраните токен — он нужен для входа")


class UserResponse(BaseModel):
    """Информация о пользователе (для проверки токена)."""
    user_id: int
    username: str
