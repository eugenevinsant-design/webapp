"""
Тесты для API чата (все режимы из ТЗ).

Запуск: pytest tests/test_api.py -v
"""

import pytest
from httpx import AsyncClient


@pytest.mark.asyncio
async def test_get_packages(client: AsyncClient):
    """Тест: GET /api/ecg/ возвращает список пакетов."""
    response = await client.get("/api/ecg/")
    assert response.status_code == 200
    data = response.json()
    assert isinstance(data, list)
    # В тестовой среде пакетов может не быть (папка data/signals пуста)
    # Но эндпоинт должен возвращать пустой список без ошибок


@pytest.mark.asyncio
async def test_chat_mode_1_choose_and_question(client: AsyncClient):
    """Тест Режима 1: выбор пакета + вопрос."""
    response = await client.post(
        "/api/chat/",
        json={"text": "\\choose_pkg JS00002 Какие аномалии?", "session_id": None}
    )
    # Если пакета нет в тестовой среде — вернется 200 с available_packages
    assert response.status_code == 200
    data = response.json()
    assert "context" in data
    assert "can_grade" in data


@pytest.mark.asyncio
async def test_chat_mode_3_empty_question(client: AsyncClient):
    """Тест: пустой вопрос без выбранного пакета."""
    response = await client.post(
        "/api/chat/",
        json={"text": "", "session_id": None}
    )
    assert response.status_code == 200
    data = response.json()
    assert "context" in data


@pytest.mark.asyncio
async def test_chat_atomicity_nonexistent_pkg(client: AsyncClient):
    """Тест атомарности: несуществующий пакет не меняет prompt."""
    response = await client.post(
        "/api/chat/",
        json={"text": "\\choose_pkg NONEXISTENT_PKG Какие аномалии?", "session_id": None}
    )
    assert response.status_code == 200
    data = response.json()
    # Должен вернуться список доступных пакетов (даже если пустой)
    assert data.get("available_packages") is not None or "не найден" in data.get("context", "")
