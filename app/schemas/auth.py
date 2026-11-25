"""
Pydantic-схемы для аутентификации.

Поток входа на платформу (ProductVesrsion0.3):
1. POST /api/auth/platform-access — токен доступа к платформе (из БД
   platform_tokens) — «пропуск» на сайт.
2. POST /api/auth/register — логин + токен платформы -> личный api_token.
3. POST /api/auth/login — логин + личный токен -> вход.
"""

from pydantic import BaseModel, Field


class PlatformAccessRequest(BaseModel):
    """Проверка токена доступа к платформе (шаг 1)."""
    platform_token: str = Field(..., min_length=1, description="Токен доступа к платформе")


class PlatformAccessResponse(BaseModel):
    """Результат проверки токена платформы."""
    ok: bool = True


class RegisterRequest(BaseModel):
    """Регистрация (шаг 2): логин + токен платформы."""
    username: str = Field(..., min_length=3, max_length=50, description="Логин пользователя")
    platform_token: str = Field(..., min_length=1, description="Токен доступа к платформе")


class RegisterResponse(BaseModel):
    """Ответ на регистрацию (личный токен показывается один раз)."""
    user_id: int
    username: str
    api_token: str = Field(..., description="Сохраните токен — он нужен для входа")


class LoginRequest(BaseModel):
    """Вход (шаг 3): логин + личный токен."""
    username: str = Field(..., min_length=1, description="Логин пользователя")
    token: str = Field(..., min_length=1, description="Личный токен из регистрации")


class UserResponse(BaseModel):
    """Информация о пользователе (для проверки токена)."""
    user_id: int
    username: str
