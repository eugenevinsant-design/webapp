"""
ChatService: оркестрация режимов 1-3 из ТЗ.

Режимы:
1. \choose_pkg <pkg> + текст: обновить raw/fs/question, сгенерировать ответ.
2. \choose_pkg <pkg> (без текста): обновить выбор пакета, вернуть уведомление.
3. Обычный текст: ответ модели по current_raw_pkg.

Режим 4 (оценка + перегенерация) — в grade_service.py.

ProductVesrsion0.3: состояние живёт в pending_store (память), в БД
(prompt_states) здесь НИЧЕГО не пишется — запись произойдёт только
после оценки пользователя (grade_service -> db_writer).
"""

import logging
from typing import Optional

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.ecg_loader import ecg_loader
from app.core.llm_client import LLMError
from app.infrastructure import nn_pipeline
from app.schemas.chat import ChatResponse
from app.services.resolver_service import parse_command
from app.services import prompt_service
from app.services.pending_store import pending_store, to_prompt_dict, PendingState

logger = logging.getLogger(__name__)


async def handle_chat(db: AsyncSession, user_id: int, text: str, session_id: Optional[int] = None) -> ChatResponse:
    """
    Обработать сообщение пользователя (Режимы 1-3).

    Args:
        db: сессия БД (только для sessions и гидрации pending-состояния).
        user_id: ID авторизованного пользователя.
        text: текст от пользователя (может содержать \choose_pkg).
        session_id: ID сессии (или None для создания новой).

    Returns:
        ChatResponse: ответ для UI.
    """
    # 1. Получаем или создаем сессию (строка sessions — это «информация
    #    о сессии», она не является данными анализа и создаётся сразу)
    session = await prompt_service.get_or_create_session(db, user_id, session_id)

    # 2. Состояние prompt — из памяти (или гидрация из БД после рестарта).
    #    Лок на сессию: параллельные запросы одного пользователя не
    #    перемешают question/context.
    lock = await pending_store.get_lock(session.id)
    async with lock:
        state = await pending_store.get(db, user_id, session.id)

        # 3. Парсим команду
        parsed = parse_command(text)

        # 4. Обработка команды \choose_pkg (Режимы 1-2)
        if parsed.command == "choose_pkg":
            return await _handle_choose_pkg(session.id, state, parsed)

        # 5. Обработка обычного текста (Режим 3)
        if parsed.clean_text:
            return await _handle_question(session.id, state, parsed.clean_text)

    # 6. Пустой текст
    return ChatResponse(
        context="Пожалуйста, введите вопрос или команду \\choose_pkg <pkg>.",
        can_grade=False,
        can_regenerate=False,
    )


async def _handle_choose_pkg(session_id: int, state: PendingState, parsed) -> ChatResponse:
    """
    Обработка режимов 1 и 2 (выбор пакета).

    Атомарность: если пакет не найден, состояние НЕ меняется.
    """
    pkg_name = parsed.argument

    # 1. Проверяем, существует ли пакет
    packages = ecg_loader.scan_signals()
    pkg_exists = any(p["name"] == pkg_name or str(p["id"]) == pkg_name for p in packages)

    if not pkg_exists:
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
        available = prompt_service.available_packages_to_schema(packages)
        return ChatResponse(
            context=f"Ошибка загрузки пакета '{pkg_name}'.",
            available_packages=available,
            can_grade=False,
            can_regenerate=False,
            message=f"Ошибка загрузки пакета '{pkg_name}'",
        )

    # 3. Обновляем состояние в памяти (атомарно, после успешной валидации)
    state.pkg_path = pkg_name
    state.fs = fs
    state.question = parsed.clean_text if parsed.clean_text else None
    state.touch()

    # 4. Если есть текст (Режим 1) — генерируем ответ
    if parsed.clean_text:
        prompt_dict = to_prompt_dict(state, raw=raw)
        try:
            result = await nn_pipeline.generate_response_full(prompt_dict)
            state.context = result["text"]
            if result.get("description"):
                # ML-«факты» о сигнале (заполняется в фазе A один раз)
                state.description = result["description"]
            state.grade = None      # сброс оценки — ждём новую
            state.version += 1      # response_id для привязки оценки
            state.touch()
            return ChatResponse(
                context=state.context,
                response_id=state.version,
                session_id=session_id,
                grade=None,
                can_grade=True,  # можно оценить
                can_regenerate=False,  # сначала оценка
                current_pkg=pkg_name,
                message=f"Пакет '{pkg_name}' выбран. Ответ сгенерирован.",
            )
        except LLMError:
            # LLM недоступна: НЕ подменяем ответ заглушкой -> HTTP 503 в роуте
            raise
        except Exception as e:
            logger.error(f"Ошибка генерации: {e}")
            return ChatResponse(
                context=f"Ошибка генерации ответа: {e}",
                can_grade=False,
                can_regenerate=False,
                message="Ошибка генерации",
            )
    else:
        # Режим 2: только выбор пакета (в память, БД не трогаем)
        return ChatResponse(
            context=f"Пакет '{pkg_name}' выбран. Задайте вопрос по этому сигналу.",
            session_id=session_id,
            current_pkg=pkg_name,
            can_grade=False,
            can_regenerate=False,
            message=f"Пакет '{pkg_name}' выбран",
        )


async def _handle_question(session_id: int, state: PendingState, question: str) -> ChatResponse:
    """
    Обработка режима 3 (обычный вопрос по выбранному пакету).
    """
    if not state.pkg_path:
        return ChatResponse(
            context="Сначала выберите пакет через \\choose_pkg <pkg>.",
            can_grade=False,
            can_regenerate=False,
        )

    # Вопрос обновляем ДО сборки prompt_dict — иначе в модель уходит
    # предыдущий вопрос (или пустая строка), и LLM не видит сообщение.
    state.question = question

    # Фазовая логика: если аннотация уже построена (context есть),
    # ML НЕ вызываем — работаем по аннотации (raw=None, фаза B).
    if state.context:
        raw = None
        prompt_dict = to_prompt_dict(state, raw=raw)
    else:
        # Фаза A: первая аннотация — единственный вызов ML
        raw, fs = ecg_loader.load_raw_signal(state.pkg_path)
        if raw is None:
            available = prompt_service.available_packages_to_schema(ecg_loader.scan_signals())
            return ChatResponse(
                context="Не удалось загрузить текущий пакет. Возможно, он был удален.",
                available_packages=available,
                can_grade=False,
                can_regenerate=False,
            )
        state.fs = fs
        prompt_dict = to_prompt_dict(state, raw=raw)

    try:
        result = await nn_pipeline.generate_response_full(prompt_dict)
        state.context = result["text"]
        if result.get("description"):
            state.description = result["description"]
        state.grade = None
        state.version += 1
        state.touch()
        return ChatResponse(
            context=state.context,
            response_id=state.version,
            session_id=session_id,
            grade=None,
            can_grade=True,
            can_regenerate=False,
            current_pkg=state.pkg_path,
            message="Ответ сгенерирован.",
        )
    except LLMError:
        # LLM недоступна: НЕ подменяем ответ заглушкой -> HTTP 503 в роуте
        raise
    except Exception as e:
        logger.error(f"Ошибка генерации: {e}")
        return ChatResponse(
            context=f"Ошибка генерации ответа: {e}",
            can_grade=False,
            can_regenerate=False,
        )
