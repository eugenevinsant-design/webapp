# app/core/loader_registry.py
"""
Реестр лоадеров сигналов.

Позволяет по расширению файла выбрать подходящий лоадер.
Новые лоадеры регистрируются через `register_loader(...)` — без правок
существующего кода (плагин-архитектура).
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Callable, Dict, List, Optional

logger = logging.getLogger(__name__)


class LoaderRegistry:
    """Реестр лоадеров сигналов по расширению файла."""

    def __init__(self) -> None:
        # ext -> (name, callable)
        self._loaders: Dict[str, tuple[str, Callable]] = {}

    # ---------- регистрация ----------

    def register(
        self,
        extensions: List[str],
        loader_name: str,
        loader_callable: Callable,
    ) -> None:
        """Зарегистрировать лоадер для набора расширений.

        Args:
            extensions: список расширений (с точкой), например ['.csv', '.txt']
            loader_name: человекочитаемое имя лоадера
            loader_callable: функция-загрузчик (path, **kwargs) -> dict
        """
        for ext in extensions:
            key = ext.lower() if ext.startswith(".") else f".{ext.lower()}"
            if key in self._loaders:
                logger.warning(
                    f"⚠️ Лоадер для {key} перезаписан: "
                    f"{self._loaders[key][0]} → {loader_name}"
                )
            self._loaders[key] = (loader_name, loader_callable)
            logger.info(f"📌 Зарегистрирован лоадер {loader_name} для {key}")

    # ---------- выбор лоадера ----------

    def get_loader(self, path: str | Path) -> Optional[tuple[str, Callable]]:
        """Вернуть (name, callable) лоадер для файла или None."""
        ext = Path(path).suffix.lower()
        if not ext:
            return None
        return self._loaders.get(ext)

    def is_supported(self, path: str | Path) -> bool:
        return self.get_loader(path) is not None

    def supported_extensions(self) -> List[str]:
        return sorted(self._loaders.keys())

    def list_loaders(self) -> List[Dict[str, str]]:
        """Список лоадеров: [{name, extensions: 'csv,txt'}, ...]"""
        grouped: Dict[str, List[str]] = {}
        for ext, (name, _) in self._loaders.items():
            grouped.setdefault(name, []).append(ext)
        return [
            {"name": name, "extensions": ", ".join(sorted(exts))}
            for name, exts in grouped.items()
        ]


# ============================================================
# ГЛОБАЛЬНЫЙ ЭКЗЕМПЛЯР
# ============================================================

loader_registry = LoaderRegistry()


# ============================================================
# АВТОРЕГИСТРАЦИЯ СТАНДАРТНЫХ ЛОАДЕРОВ
# ============================================================

def _register_defaults() -> None:
    """Регистрирует встроенные лоадеры при импорте модуля."""
    # WFDB (.hea/.mat) — основной формат PhysioNet
    from app.core.ecg_loader import ecg_loader

    def _wfdb_load(path, fs=None, name=None, **kwargs):
        """Обёртка над ecg_loader для регистрации в реестре."""
        # ecg_loader умеет читать по имени записи, но не по прямому пути.
        # Ищем сигнал по базовому имени в сканированной папке.
        from pathlib import Path as _P
        base = _P(path).stem
        signals = ecg_loader.scan_signals(force=True)
        for sig in signals:
            if sig["name"] == base:
                return sig
        raise FileNotFoundError(f"WFDB-запись '{base}' не найдена")

    loader_registry.register(
        extensions=[".hea", ".mat", ".dat"],
        loader_name="wfdb",
        loader_callable=_wfdb_load,
    )

    # CSV/TXT — наш новый лоадер
    from app.core.csv_loader import csv_loader

    def _csv_load(path, fs=None, name=None, **kwargs):
        """Обёртка над csv_loader.load() для регистрации в реестре."""
        sig = csv_loader.load(path, fs=fs, name=name)
        return sig.to_dict(signal_id=0)  # id присвоим позже

    loader_registry.register(
        extensions=[".csv", ".txt"],
        loader_name="csv",
        loader_callable=_csv_load,
    )


_register_defaults()
