"""
GradeService: оценка и перегенерация (Режим 4 из ТЗ).

ТЗ требует строгий порядок:
1. Сначала оценка (0-10).
2. Затем предложение перегенерировать.

ProductVesrsion0.3 — КЛЮЧЕВОЕ ИЗМЕНЕНИЕ:
запись в БД (prompt_states) происходит ТОЛЬКО здесь, в момент оценки.
set_grade кладёт слепок состояния (user_id + session_id + question +
description + context + grade) в асинхронную очередь db_writer и сразу
отвечает UI — запрос не ждёт БД, а при пачке оценок worker запишет их
одним батчем без потерь.

Перегенерация БД не трогает: она меняет только память (pending_store).
Следующая оценка снова уйдёт в db_writer (upsert той же строки).
"""

import logging

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.llm_client import LLMError
from app.config import settings
from app.infrastructure import nn_pipeline
from app.schemas.chat import ChatResponse
from app.services.db_writer import db_writer
from app.services.pending_store import pending_store, to_prompt_dict

logger = logging.getLogger(__name__)


async def set_grade(db: AsyncSession, user_id: int, session_id: int, response_id: int, grade: int) -> ChatResponse:
    """
    Выставить оценку (0-10) -> ЕДИНСТВЕННАЯ точка записи в prompt_states.

    Порядок:
    1. Берём состояние из памяти (или гидрируем из БД после рестарта).
    2. Проверяем, что оценивается ПОСЛЕДНИЙ ответ (response_id == version)
       и что есть что оценивать (context не пуст).
    3. Ставим оценку и кладём слепок в db_writer (асинхронный upsert).
    4. Отвечаем UI сразу, не дожидаясь БД.

    После оценки can_regenerate становится True (порядок из ТЗ).
    """
    lock = await pending_store.get_lock(session_id)
    async with lock:
        state = await pending_store.get(db, user_id, session_id)

        # Привязка к пользователю: чужую сессию оценить нельзя
        if state.user_id != user_id:
            return ChatResponse(
                context="Ответ не найден или не принадлежит этому пользователю.",
                can_grade=False,
                can_regenerate=False,
            )

        # Оценивать можно только последний сгенерированный ответ
        if not state.context or response_id != state.version:
            return ChatResponse(
                context="Ответ не найден или уже устарел (была перегенерация).",
                can_grade=False,
                can_regenerate=False,
            )

        # ТЗ: сначала оценка
        state.grade = grade
        state.touch()

        # Асинхронная запись в БД: user_id + session_id + весь слепок.
        # Обычный режим: эндпоинт не ждёт commit — запись выполнит фоновый
        # worker (батч + ретраи -> ничего не теряется при пиковой нагрузке).
        # Serverless (Vercel): worker между вызовами заморожен, поэтому
        # пишем синхронно, внутри запроса (те же ретраи с backoff).
        if settings.is_serverless:
            await db_writer.write_now(state.snapshot())
        else:
            db_writer.enqueue(state.snapshot())
        logger.info(
            "Оценка %s/10 поставлена в очередь записи (user_id=%s, session_id=%s)",
            grade, user_id, session_id,
        )

        return ChatResponse(
            context=state.context or "",
            response_id=state.version,
            session_id=session_id,
            grade=grade,
            can_grade=False,      # оценка уже поставлена
            can_regenerate=True,  # теперь можно перегенерировать
            current_pkg=state.pkg_path,
            message=f"Оценка {grade}/10 сохранена. Можно перегенерировать ответ.",
        )


async def regenerate_response(db: AsyncSession, user_id: int, session_id: int, response_id: int) -> ChatResponse:
    """
    Перегенерировать ответ (Режим 4).

    Меняется только context в ПАМЯТИ (grade сбрасывается в None).
    В БД ничего не пишется — запись будет после следующей оценки.
    question и raw не меняются (по ТЗ).
    """
    lock = await pending_store.get_lock(session_id)
    async with lock:
        state = await pending_store.get(db, user_id, session_id)

        if state.user_id != user_id:
            return ChatResponse(
                context="Ответ не найден или не принадлежит этому пользователю.",
                can_grade=False,
                can_regenerate=False,
            )

        if not state.context or response_id != state.version:
            return ChatResponse(
                context="Ответ не найден или уже устарел.",
                can_grade=False,
                can_regenerate=False,
            )

        if not state.pkg_path:
            return ChatResponse(
                context="Пакет не выбран. Нельзя перегенерировать.",
                can_grade=False,
                can_regenerate=False,
            )

        # Фазовая логика: аннотация уже есть -> перегенерируем ПО АННОТАЦИИ
        # (raw=None), ML не вызывается повторно.
        prompt_dict = to_prompt_dict(state, raw=None)

        # Флаг перегенерации: модель просим дать НОВЫЙ вариант ответа
        # (другая структура/формулировки, выше температура).
        prompt_dict["regenerate"] = True
        try:
            result = await nn_pipeline.generate_response_full(prompt_dict)
            state.context = result["text"]
            # description (ML-факты) НЕ меняется — сигнал тот же
            state.grade = None      # сброс оценки
            state.version += 1      # новый response_id
            state.touch()

            return ChatResponse(
                context=state.context,
                response_id=state.version,
                session_id=session_id,
                grade=None,
                can_grade=True,       # можно оценить заново
                can_regenerate=False, # сначала оценка
                current_pkg=state.pkg_path,
                message="Ответ перегенерирован. Оцените новый ответ.",
            )
        except LLMError:
            # LLM недоступна: не подменяем ответ заглушкой -> HTTP 503 в роуте
            raise
        except Exception as e:
            logger.error(f"Ошибка перегенерации: {e}")
            return ChatResponse(
                context=f"Ошибка перегенерации: {e}",
                can_grade=False,
                can_regenerate=False,
            )
