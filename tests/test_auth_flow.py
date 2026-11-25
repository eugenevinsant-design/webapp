"""
Тесты трёхшагового входа на платформу (ProductVesrsion0.3).

1. Токен доступа к платформе (platform_tokens в БД) — «пропуск» на сайт.
2. Регистрация (логин + токен платформы) -> личный api_token.
3. Вход по паре логин + личный токен.

Все данные проверяются в БД (users, platform_tokens).
"""

import pytest
from httpx import AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models_db import User, PlatformToken
from tests.conftest import TEST_PLATFORM_TOKEN


@pytest.mark.asyncio
async def test_platform_access_ok(anon_client: AsyncClient):
    """Валидный токен платформы -> 200 ok."""
    resp = await anon_client.post(
        "/api/auth/platform-access", json={"platform_token": TEST_PLATFORM_TOKEN}
    )
    assert resp.status_code == 200
    assert resp.json()["ok"] is True


@pytest.mark.asyncio
async def test_platform_access_wrong_token_403(anon_client: AsyncClient):
    """Неверный токен платформы -> 403."""
    resp = await anon_client.post(
        "/api/auth/platform-access", json={"platform_token": "wrong-token"}
    )
    assert resp.status_code == 403


@pytest.mark.asyncio
async def test_register_requires_platform_token(anon_client: AsyncClient):
    """Регистрация без валидного токена платформы -> 403."""
    resp = await anon_client.post(
        "/api/auth/register",
        json={"username": "newuser1", "platform_token": "wrong-token"},
    )
    assert resp.status_code == 403


@pytest.mark.asyncio
async def test_register_stores_user_in_db(anon_client: AsyncClient, db_session: AsyncSession):
    """Регистрация создаёт пользователя с личным токеном в таблице users."""
    resp = await anon_client.post(
        "/api/auth/register",
        json={"username": "newuser2", "platform_token": TEST_PLATFORM_TOKEN},
    )
    assert resp.status_code == 200, resp.text
    data = resp.json()
    assert data["api_token"], "личный токен должен быть выдан"

    row = await db_session.execute(select(User).where(User.username == "newuser2"))
    user = row.scalar_one_or_none()
    assert user is not None, "пользователь должен быть сохранён в БД"
    assert user.api_token == data["api_token"]


@pytest.mark.asyncio
async def test_login_username_and_token(anon_client: AsyncClient):
    """Вход: верная пара логин+токен -> 200; чужой токен/логин -> 401."""
    reg = await anon_client.post(
        "/api/auth/register",
        json={"username": "loginuser", "platform_token": TEST_PLATFORM_TOKEN},
    )
    token = reg.json()["api_token"]

    # Верная пара -> вход
    ok = await anon_client.post(
        "/api/auth/login", json={"username": "loginuser", "token": token}
    )
    assert ok.status_code == 200
    assert ok.json()["username"] == "loginuser"

    # Чужой токен к этому логину -> 401
    bad_token = await anon_client.post(
        "/api/auth/login", json={"username": "loginuser", "token": "deadbeef"}
    )
    assert bad_token.status_code == 401

    # Верный токен, но другой логин -> 401 (токен привязан к логину)
    bad_name = await anon_client.post(
        "/api/auth/login", json={"username": "someoneelse", "token": token}
    )
    assert bad_name.status_code == 401


@pytest.mark.asyncio
async def test_platform_token_stored_in_db(db_session: AsyncSession):
    """Токен платформы лежит в таблице platform_tokens (не только в .env)."""
    row = await db_session.execute(
        select(PlatformToken).where(PlatformToken.token == TEST_PLATFORM_TOKEN)
    )
    pt = row.scalar_one_or_none()
    assert pt is not None
    assert pt.is_active == 1
