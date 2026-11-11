"""
ChatService: оркестрация режимов 1-3 из ТЗ.

Режимы:
1. \choose_pkg <pkg> + текст: обновить raw/fs/question, сгенерировать ответ.
2. \choose_pkg <pkg> (без текста): обновить выбор пакета, вернуть уведомление.
3. Обычный текст: ответ модели по current_raw_pkg.

Режим 4 (оценка + перегенерация) — в grade_service.py.
"""

import logging
from typing import Optional

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.ecg_loader import ecg_loader
from app.infrastructure import nn_pipeline
from app.schemas.chat import ChatResponse, AvailablePackage
from app.services.resolver_service import parse_command
from app.services import prompt_service

logger = logging.getLogger(__name__)


async def handle_chat(db: AsyncSession, user_id: int, text: str, session_id: Optional[int] = None) -> ChatResponse:
    """
    Обработать сообщение пользователя (Режимы 1-3).

    Args:
        db: сессия БД.
        text: текст от пользователя (может содержать \choose_pkg).
        session_id: ID сессии (или None для создания новой).

    Returns:
        ChatResponse: ответ для UI.
    """
    # 1. Получаем или создаем сессию и PromptState
    session = await prompt_service.get_or_create_session(db, user_id, session_id)
    state = await prompt_service.get_prompt_state(db, session.id)
    if not state:
        # Если по какой-то причине PromptState не создался, создаем
        from app.models_db import PromptState
        state = PromptState(session_id=session.id)
        db.add(state)
        await db.flush()

    # 2. Парсим команду
    parsed = parse_command(text)

    # 3. Обработка команды \choose_pkg (Режимы 1-2)
    if parsed.command == "choose_pkg":
        return await _handle_choose_pkg(db, session.id, state, parsed, text)

    # 4. Обработка обычного текста (Режим 3)
    if parsed.clean_text:
        return await _handle_question(db, session.id, state, parsed.clean_text)

    # 5. Пустой текст
    return ChatResponse(
        context="Пожалуйста, введите вопрос или команду \\choose_pkg <pkg>.",
        can_grade=False,
        can_regenerate=False,
    )


async def _handle_choose_pkg(db: AsyncSession, session_id: int, state, parsed, original_text: str) -> ChatResponse:
    """
    Обработка режимов 1 и 2 (выбор пакета).

    Атомарность: если пакет не найден, prompt НЕ меняется.
    """
    pkg_name = parsed.argument

    # 1. Проверяем, существует ли пакет
    packages = ecg_loader.scan_signals()
    pkg_exists = any(p["name"] == pkg_name or str(p["id"]) == pkg_name for p in packages)

    if not pkg_exists:
        # Атомарность: возвращаем список, не трогая state
        logger.warning(f"Пакет {pkg_name} не найден")
        available = prompt_service.available_packages_to_schema(packages)
        return ChatResponse(
            context=f"Пакет '{pkg_name}' не найден. Доступные пакеты:",
            available_packages=available,
            can_grade=False,
            can_regenerate=False,
            message=f"Пакет '{pkg_name}' не найден",
        )

    # 2. Загружаем raw и fs через wfdb
    raw, fs = ecg_loader.load_raw_signal(pkg_name)
    if raw is None:
        # Ошибка загрузки — атомарность
        available = prompt_service.available_packages_to_schema(packages)
        return ChatResponse(
            context=f"Ошибка загрузки пакета '{pkg_name}'.",
            available_packages=available,
            can_grade=False,
            can_regenerate=False,
            message=f"Ошибка загрузки пакета '{pkg_name}'",
        )

    # 3. Обновляем PromptState (атомарно, после успешной валидации)
    state.current_raw_pkg_path = pkg_name
    state.fs = fs
    state.question = parsed.clean_text if parsed.clean_text else None

    # 4. Если есть текст (Режим 1) — генерируем ответ
    if parsed.clean_text:
        prompt_dict = prompt_service.to_prompt_dict(state, raw=raw)
        try:
            context = await nn_pipeline.generate_response(prompt_dict)
            state.context = context
            state.grade = None  # сброс оценки
            await prompt_service.save_prompt_state(db, state)
            return ChatResponse(
                context=context,
                response_id=state.id,
                session_id=session_id,
                grade=None,
                can_grade=True,  # можно оценить
                can_regenerate=False,  # сначала оценка
                current_pkg=pkg_name,
                message=f"Пакет '{pkg_name}' выбран. Ответ сгенерирован.",
            )
        except Exception as e:
            logger.error(f"Ошибка генерации: {e}")
            return ChatResponse(
                context=f"Ошибка генерации ответа: {e}",
                can_grade=False,
                can_regenerate=False,
                message="Ошибка генерации",
            )
    else:
        # Режим 2: только выбор пакета (БЕЗ записи в БД, только flush)
        await db.flush()  # фиксируем в сессии, но не commit
        return ChatResponse(
            context=f"Пакет '{pkg_name}' выбран. Задайте вопрос по этому сигналу.",
            session_id=session_id,
            current_pkg=pkg_name,
            can_grade=False,
            can_regenerate=False,
            message=f"Пакет '{pkg_name}' выбран",
        )


async def _handle_question(db: AsyncSession, session_id: int, state, question: str) -> ChatResponse:
    """
    Обработка режима 3 (обычный вопрос по current_raw_pkg).
    """
    if not state.current_raw_pkg_path:
        return ChatResponse(
            context="Сначала выберите пакет через \\choose_pkg <pkg>.",
            can_grade=False,
            can_regenerate=False,
        )

    # 1. Загружаем raw для текущего пакета
    raw, fs = ecg_loader.load_raw_signal(state.current_raw_pkg_path)
    if raw is None:
        available = prompt_service.available_packages_to_schema(ecg_loader.scan_signals())
        return ChatResponse(
            context="Не удалось загрузить текущий пакет. Возможно, он был удален.",
            available_packages=available,
            can_grade=False,
            can_regenerate=False,
        )

    # 2. Обновляем question и сохраняем
    state.question = question
    state.fs = fs
    prompt_dict = prompt_service.to_prompt_dict(state, raw=raw)

    try:
        context = await nn_pipeline.generate_response(prompt_dict)
        state.context = context
        state.grade = None
        await prompt_service.save_prompt_state(db, state)
        return ChatResponse(
            context=context,
            response_id=state.id,
            session_id=session_id,
            grade=None,
            can_grade=True,
            can_regenerate=False,
            current_pkg=state.current_raw_pkg_path,
            message="Ответ сгенерирован.",
        )
    except Exception as e:
        logger.error(f"Ошибка генерации: {e}")
        return ChatResponse(
            context=f"Ошибка генерации ответа: {e}",
            can_grade=False,
            can_regenerate=False,
        )
