"""
ML-вход: подготовка данных для ML-модели.

Контракт (заморожен):
    build_ml_input(raw, fs, meta=None) -> dict:
        {
            "signal": np.ndarray [C, N] float32,  # без NaN/Inf
            "fs": float,
            "n_leads": int,
            "n_samples": int,
            "duration": float,  # секунд
            "meta": dict,       # опциональные метаданные
        }

Для torch-модели:
    th.from_numpy(inp["signal"])           # [C, N]
    inp["signal"][None]                    # [1, C, N] — батч из одного
"""

import logging
from typing import Any, Dict, Optional

import numpy as np

logger = logging.getLogger(__name__)


def build_ml_input(raw, fs, meta: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    """
    Собрать и провалидировать вход для ML-модели.

    Args:
        raw: ndarray [C, N] (12 каналов) или [N] (один канал).
        fs: частота дискретизации, Гц.
        meta: произвольные метаданные (путь к файлу и т.п.).

    Returns:
        dict с ключами signal/fs/n_leads/n_samples/duration/meta.

    Raises:
        ValueError: если raw пуст, fs некорректна или NaN не чистится.
    """
    if raw is None:
        raise ValueError("raw не может быть None")
    arr = np.asarray(raw)
    if arr.ndim == 1:
        arr = arr[None, :]
    if arr.ndim != 2:
        raise ValueError(f"raw должен быть [C, N] или [N], получено shape={arr.shape}")
    if fs is None or float(fs) <= 0:
        raise ValueError(f"fs должна быть положительным числом, получено: {fs}")

    # Чистим NaN/Inf: заменяем на 0 и логируем, если их было много
    mask_bad = ~np.isfinite(arr)
    n_bad = int(mask_bad.sum())
    if n_bad:
        arr = arr.copy()
        arr[mask_bad] = 0.0
        share = n_bad / arr.size
        if share > 0.05:
            raise ValueError(f"слишком много нечисловых значений в сигнале: {share:.1%}")
        if share > 0:
            logger.warning(f"Заменено {n_bad} NaN/Inf значений ({share:.2%}) на 0")

    arr = arr.astype(np.float32)
    fs_f = float(fs)
    return {
        "signal": arr,
        "fs": fs_f,
        "n_leads": int(arr.shape[0]),
        "n_samples": int(arr.shape[1]),
        "duration": round(arr.shape[1] / fs_f, 3),
        "meta": dict(meta or {}),
    }
