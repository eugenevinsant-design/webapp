"""
Асинхронный писатель в БД (очередь + батч + ретраи).

Зачем (ProductVesrsion0.3):
- Запись в prompt_states происходит ТОЛЬКО после оценки пользователя.
- Эндпоинт /grade не должен ждать БД: он кладёт слепок состояния
  (snapshot) в очередь и сразу отвечает UI.
- Фоновый worker забирает накопившиеся слепки ПАКЕТОМ (batch drain) и
  пишет их одной транзакцией — при параллельной нагрузке (например,
  когда LLM/vLLM обрабатывает общий батч инференса и оценки прилетают
  пачкой) ни одна запись не теряется и не блокирует запросы.
- Ретраи с backoff: временная ошибка БД не роняет запись. После
  исчерпания попыток слепок попадает в dead_letters (лог + память),
  чтобы его можно было разобрать вручную.

Жизненный цикл:
- start() — в lifespan приложения (main.py).
- stop() — дожидается опустошения очереди (drain) и гасит worker.
- wait_idle() — для тестов: дождаться, пока очередь обработается.

Инъекция session_factory: по умолчанию app.database.AsyncSessionLocal;
тесты подменяют на свою фабрику (in-memory SQLite).
"""

import asyncio
import logging
from typing import Any, Callable, Dict, List, Optional

from sqlalchemy import select

logger = logging.getLogger(__name__)

# Сколько попыток записи и пауза между ними (секунды, экспоненциально)
MAX_ATTEMPTS = 3
RETRY_BASE_DELAY = 0.2

# Максимум слепков в одном батч-коммите (защита от гигантских транзакций)
MAX_BATCH = 100


class DBWriter:
    """Очередь асинхронной записи слепков PromptState в БД."""

    def __init__(self) -> None:
        # Очередь создаётся ЛЕНИВО в start(): asyncio.Queue при первом
        # использовании привязывается к текущему event loop. Если создать
        # её в __init__ (на импорте), а тесты/приложение поднимут ДРУГОЙ
        # loop — worker зависнет на queue.get(). Поэтому: новый start() =
        # новая очередь в текущем loop.
        self._queue: "asyncio.Queue[Dict[str, Any]]" = asyncio.Queue()
        self._task: Optional[asyncio.Task] = None
        # Инъектируемая фабрика сессий (None -> AsyncSessionLocal из database)
        self.session_factory: Optional[Callable] = None
        # «Мёртвые письма»: слепки, которые не удалось записать после ретраев
        self.dead_letters: List[Dict[str, Any]] = []

    # ---------- жизненный цикл ----------

    async def start(self) -> None:
        """Запустить фонового worker (вызывается из lifespan).

        Очередь пересоздаётся в ТЕКУЩЕМ event loop — иначе при смене
        loop (например, между тестами) worker повиснет на queue.get().
        """
        if self._task is not None and not self._task.done():
            return
        self._queue = asyncio.Queue()
        self._task = asyncio.create_task(self._worker(), name="db-writer")
        logger.info("DBWriter запущен")

    async def stop(self, timeout: float = 10.0) -> None:
        """Остановить worker: сначала дождаться drain очереди, потом отменить."""
        if self._task is None:
            return
        try:
            await asyncio.wait_for(self._queue.join(), timeout=timeout)
        except asyncio.TimeoutError:
            logger.error("DBWriter: очередь не опустела за %.1f c — часть записей потеряна", timeout)
        self._task.cancel()
        try:
            await self._task
        except (asyncio.CancelledError, Exception):
            pass
        self._task = None
        logger.info("DBWriter остановлен")

    # ---------- API для сервисов ----------

    def enqueue(self, snapshot: Dict[str, Any]) -> None:
        """Положить слепок состояния в очередь (неблокирующе)."""
        self._queue.put_nowait(snapshot)
        logger.debug(
            "DBWriter: слепок в очереди (session_id=%s, grade=%s), размер=%d",
            snapshot.get("session_id"), snapshot.get("grade"), self._queue.qsize(),
        )

    async def wait_idle(self) -> None:
        """Дождаться обработки всех слепков в очереди (для тестов)."""
        await self._queue.join()

    @property
    def pending(self) -> int:
        """Сколько слепков ещё ждёт записи."""
        return self._queue.qsize()

    # ---------- worker ----------

    def _get_session_factory(self):
        if self.session_factory is not None:
            return self.session_factory
        # Ленивый импорт: не тянуть engine при импорте модуля (тесты!)
        from app.database import AsyncSessionLocal
        return AsyncSessionLocal

    async def _worker(self) -> None:
        """Фоновый цикл: забрать один слепок + досыпать очередь в батч."""
        while True:
            first = await self._queue.get()
            batch: List[Dict[str, Any]] = [first]
            # Drain: забираем всё, что успело накопиться (до MAX_BATCH)
            while len(batch) < MAX_BATCH:
                try:
                    batch.append(self._queue.get_nowait())
                except asyncio.QueueEmpty:
                    break
            try:
                await self._write_batch_with_retry(batch)
            finally:
                for _ in batch:
                    self._queue.task_done()

    async def _write_batch_with_retry(self, batch: List[Dict[str, Any]]) -> None:
        """Записать батч слепков одной транзакцией с ретраями."""
        last_exc: Optional[Exception] = None
        for attempt in range(1, MAX_ATTEMPTS + 1):
            try:
                await self._write_batch(batch)
                if len(batch) > 1:
                    logger.info("DBWriter: батч из %d слепков записан", len(batch))
                return
            except Exception as exc:  # noqa: BLE001 — фиксируем любую ошибку БД
                last_exc = exc
                delay = RETRY_BASE_DELAY * (2 ** (attempt - 1))
                logger.warning(
                    "DBWriter: попытка %d/%d не удалась (%s), пауза %.2f c",
                    attempt, MAX_ATTEMPTS, exc, delay,
                )
                await asyncio.sleep(delay)
        logger.error("DBWriter: батч НЕ записан после %d попыток: %s", MAX_ATTEMPTS, last_exc)
        self.dead_letters.extend(batch)

    async def _write_batch(self, batch: List[Dict[str, Any]]) -> None:
        """Upsert слепков в prompt_states одной транзакцией."""
        from app.models_db import PromptState

        factory = self._get_session_factory()
        async with factory() as db:
            for snap in batch:
                result = await db.execute(
                    select(PromptState).where(PromptState.session_id == snap["session_id"])
                )
                row = result.scalar_one_or_none()
                if row is None:
                    row = PromptState(session_id=snap["session_id"])
                    db.add(row)
                row.user_id = snap.get("user_id")
                row.question = snap.get("question")
                row.current_raw_pkg_path = snap.get("pkg_path")
                row.fs = snap.get("fs")
                row.description = snap.get("description")
                row.context = snap.get("context")
                row.grade = snap.get("grade")
            await db.commit()
        logger.info(
            "💾 PromptState записан(ы) в БД: %s",
            [(s["session_id"], s.get("grade")) for s in batch],
        )


# Глобальный синглтон (как ecg_loader): один worker на приложение
db_writer = DBWriter()
