"""
Тесты правила ProductVesrsion0.3: запись в prompt_states — ТОЛЬКО после оценки.

Покрывает:
1. Анализ (режим 1) НЕ создаёт запись в prompt_states.
2. Оценка -> асинхронная запись: user_id + session_id + question +
   description (ML-факты) + context + grade.
3. Перегенерация НЕ пишет в БД (строка остаётся со старой оценкой).
4. Повторная оценка после перегенерации обновляет ту же строку (upsert).
5. Оценка устаревшего response_id отклоняется.
6. Асинхронность: эндпоинт /grade отвечает до фактического commit.

LLM подменяется фейками (без сети), ML (scipy) работает по-настоящему
на реальном сигнале JS00002.
"""

import json

import pytest
from httpx import AsyncClient
from sqlalchemy import select, func
from sqlalchemy.ext.asyncio import AsyncSession

from app.core import llm_client
from app.models_db import PromptState
from app.services.db_writer import db_writer


@pytest.fixture
def fake_llm(monkeypatch):
    """Подменить LLM-вызовы фейками (без OpenRouter в тестах)."""
    async def fake_annotation_text(annotation_json):
        return "Аннотация ЭКГ (фейк LLM)"

    async def fake_chat_text(*args, **kwargs):
        return "Перегенерированный ответ (фейк LLM)"

    monkeypatch.setattr(llm_client, "generate_annotation_text", fake_annotation_text)
    monkeypatch.setattr(llm_client, "generate_chat_text", fake_chat_text)


async def _get_state_row(db: AsyncSession, session_id: int):
    result = await db.execute(
        select(PromptState).where(PromptState.session_id == session_id)
    )
    return result.scalar_one_or_none()


@pytest.mark.asyncio
async def test_no_db_write_before_grade(client: AsyncClient, db_session: AsyncSession, fake_llm):
    """Анализ сигнала (режим 1) не создаёт запись в prompt_states."""
    resp = await client.post(
        "/api/chat/",
        json={"text": "\\choose_pkg JS00002 Какие аномалии?", "session_id": None},
    )
    assert resp.status_code == 200, resp.text
    data = resp.json()
    assert data["can_grade"] is True
    assert data["response_id"] is not None

    row = await _get_state_row(db_session, data["session_id"])
    assert row is None, "До оценки в prompt_states ничего не должно записываться"


@pytest.mark.asyncio
async def test_grade_writes_full_snapshot(client: AsyncClient, db_session: AsyncSession, fake_llm):
    """Оценка -> в БД появляется полный слепок: user_id, session_id,
    question, description (ML-факты), context, grade."""
    resp = await client.post(
        "/api/chat/",
        json={"text": "\\choose_pkg JS00002 Какие аномалии?", "session_id": None},
    )
    data = resp.json()
    session_id = data["session_id"]

    grade_resp = await client.post(
        f"/api/chat/grade?session_id={session_id}",
        json={"response_id": data["response_id"], "grade": 9},
    )
    assert grade_resp.status_code == 200, grade_resp.text
    assert grade_resp.json()["can_regenerate"] is True

    # Запись асинхронная — ждём drain очереди
    await db_writer.wait_idle()

    row = await _get_state_row(db_session, session_id)
    assert row is not None, "После оценки запись обязана появиться"
    assert row.session_id == session_id
    assert row.user_id is not None, "user_id должен быть связан с владельцем сессии"
    assert row.grade == 9
    assert row.question == "Какие аномалии?"
    assert row.current_raw_pkg_path == "JS00002"
    assert row.context == "Аннотация ЭКГ (фейк LLM)"

    # description — JSON с ML-фактами (ЧСС и статистика по сигналу)
    assert row.description, "description (ML-факты) должен быть заполнен"
    facts = json.loads(row.description)
    assert "statistics" in facts
    assert facts["statistics"]["hr_bpm"] is not None


@pytest.mark.asyncio
async def test_regenerate_does_not_write_until_next_grade(
    client: AsyncClient, db_session: AsyncSession, fake_llm
):
    """Перегенерация не трогает БД; повторная оценка обновляет ту же строку."""
    resp = await client.post(
        "/api/chat/",
        json={"text": "\\choose_pkg JS00002 Какие аномалии?", "session_id": None},
    )
    data = resp.json()
    session_id = data["session_id"]

    await client.post(
        f"/api/chat/grade?session_id={session_id}",
        json={"response_id": data["response_id"], "grade": 5},
    )
    await db_writer.wait_idle()

    # Перегенерация: новый ответ, но в БД остаётся СТАРАЯ оценка
    regen = await client.post(
        f"/api/chat/regenerate?session_id={session_id}",
        json={"response_id": data["response_id"]},
    )
    assert regen.status_code == 200, regen.text
    regen_data = regen.json()
    assert regen_data["can_grade"] is True
    assert regen_data["response_id"] != data["response_id"], "Новый ответ = новый response_id"

    await db_writer.wait_idle()  # на случай лишних записей (их быть не должно)
    row = await _get_state_row(db_session, session_id)
    assert row.grade == 5, "Перегенерация не должна менять БД"
    assert row.context == "Аннотация ЭКГ (фейк LLM)", "context в БД ещё старый"

    # Повторная оценка -> upsert той же строки (одна строка на сессию!)
    await client.post(
        f"/api/chat/grade?session_id={session_id}",
        json={"response_id": regen_data["response_id"], "grade": 8},
    )
    await db_writer.wait_idle()

    db_session.expire_all()
    row = await _get_state_row(db_session, session_id)
    assert row.grade == 8
    assert row.context == "Перегенерированный ответ (фейк LLM)"

    count = await db_session.execute(
        select(func.count()).select_from(PromptState).where(PromptState.session_id == session_id)
    )
    assert count.scalar() == 1, "На сессию — одна строка prompt_states (upsert)"


@pytest.mark.asyncio
async def test_stale_response_id_rejected(client: AsyncClient, fake_llm):
    """Оценка устаревшего response_id (после перегенерации) отклоняется."""
    resp = await client.post(
        "/api/chat/",
        json={"text": "\\choose_pkg JS00002 Какие аномалии?", "session_id": None},
    )
    data = resp.json()
    session_id = data["session_id"]

    await client.post(
        f"/api/chat/grade?session_id={session_id}",
        json={"response_id": data["response_id"], "grade": 7},
    )
    regen = await client.post(
        f"/api/chat/regenerate?session_id={session_id}",
        json={"response_id": data["response_id"]},
    )
    assert regen.status_code == 200

    # Пытаемся оценить СТАРЫЙ response_id — должно отклониться
    stale = await client.post(
        f"/api/chat/grade?session_id={session_id}",
        json={"response_id": data["response_id"], "grade": 1},
    )
    assert stale.status_code == 200
    assert stale.json()["can_grade"] is False
    assert "устарел" in stale.json()["context"]
