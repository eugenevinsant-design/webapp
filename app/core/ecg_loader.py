# app/core/ecg_loader.py
"""
Загрузчик сигналов: WFDB (.hea/.mat) + CSV/TXT (загруженные через UI).
Объединяет оба источника в один список с сквозной нумерацией id.
"""

from __future__ import annotations

import glob
import logging
import os
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional

import wfdb

logger = logging.getLogger(__name__)


class ECGLoader:
    def __init__(
        self,
        signals_dir: str = "./data/signals",
        uploads_dir: str = "./data/uploads",
    ):
        self.signals_dir = signals_dir
        self.uploads_dir = uploads_dir

        os.makedirs(signals_dir, exist_ok=True)
        os.makedirs(uploads_dir, exist_ok=True)

        logger.info(
            f"📂 Загрузчик ЭКГ инициализирован: "
            f"signals={signals_dir}, uploads={uploads_dir}"
        )

        self._cache: List[Dict[str, Any]] = []
        self._last_scan: Optional[datetime] = None

    # ==========================================================
    # СКАНИРОВАНИЕ
    # ==========================================================

    def scan_signals(self, force: bool = False) -> List[Dict[str, Any]]:
        """Сканирует signals/ (WFDB) и uploads/ (CSV/TXT),
        объединяет в один список со сквозным id."""
        if not force and self._cache and self._last_scan:
            return self._cache

        wfdb_signals = self._scan_wfdb()
        csv_signals = self._scan_uploads()

        all_signals: List[Dict[str, Any]] = []
        next_id = 1

        for sig in wfdb_signals:
            sig["id"] = next_id
            sig.setdefault("source_type", "wfdb")
            sig.setdefault("channels", None)
            sig.setdefault("sig_len", None)
            sig.setdefault("upload_id", None)
            all_signals.append(sig)
            next_id += 1

        for sig in csv_signals:
            sig["id"] = next_id
            sig.setdefault("source_type", "csv")
            all_signals.append(sig)
            next_id += 1

        self._cache = all_signals
        self._last_scan = datetime.now()

        logger.info(
            f"📊 Всего сигналов: {len(all_signals)} "
            f"(WFDB: {len(wfdb_signals)}, CSV/TXT: {len(csv_signals)})"
        )
        return all_signals

    def _scan_wfdb(self) -> List[Dict[str, Any]]:
        """Сканирует .hea/.mat в data/signals/."""
        signals: List[Dict[str, Any]] = []

        if not os.path.exists(self.signals_dir):
            return signals

        hea_files = sorted(glob.glob(os.path.join(self.signals_dir, "*.hea")))
        logger.info(f"🔍 Найдено .hea: {len(hea_files)}")

        for hea_path in hea_files:
            try:
                file_name = os.path.basename(hea_path)
                base_name = os.path.splitext(file_name)[0]
                mat_path = os.path.join(self.signals_dir, f"{base_name}.mat")

                if not os.path.exists(mat_path):
                    logger.warning(f"⚠️ Нет .mat для {base_name}, пропускаем")
                    continue

                fs = n_sig = duration = sig_len = None
                try:
                    record = wfdb.rdrecord(os.path.join(self.signals_dir, base_name))
                    fs = record.fs
                    n_sig = record.n_sig
                    sig_len = int(record.sig_len)
                    duration = sig_len / fs if fs else None
                except Exception as e:
                    logger.warning(f"⚠️ Ошибка чтения {base_name}: {e}")

                file_size = os.path.getsize(hea_path) + os.path.getsize(mat_path)

                signals.append({
                    "name": base_name,
                    "file_name": file_name,
                    "file_path": hea_path,
                    "mat_file": mat_path,
                    "fs": fs,
                    "n_sig": n_sig,
                    "sig_len": sig_len,
                    "duration": duration,
                    "size_kb": round(file_size / 1024, 1),
                    "signal_type": "ecg",
                    "source_type": "wfdb",
                    "channels": None,
                    "upload_id": None,
                })

                logger.info(f"✅ WFDB: {file_name} (fs={fs}Hz)")

            except Exception as e:
                logger.error(f"❌ Ошибка {hea_path}: {e}")

        return signals

    def _scan_uploads(self) -> List[Dict[str, Any]]:
        """Сканирует .csv/.txt в data/uploads/."""
        from app.core.csv_loader import csv_loader, CSVParsingError

        signals: List[Dict[str, Any]] = []
        uploads_path = Path(self.uploads_dir)

        if not uploads_path.exists():
            return signals

        for path in sorted(uploads_path.glob("*")):
            if path.name.startswith("."):
                continue
            ext = path.suffix.lower()
            if ext not in {".csv", ".txt"}:
                continue

            try:
                sig = csv_loader.load(path, fs=None, name=None)
                meta = sig.to_dict(signal_id=0)

                upload_id = (
                    path.stem.split("_", 1)[0]
                    if "_" in path.stem
                    else path.stem
                )
                meta["upload_id"] = upload_id
                meta["source_type"] = sig.source_type

                signals.append(meta)
                logger.info(f"✅ CSV/TXT: {path.name}")

            except CSVParsingError as e:
                logger.warning(f"⚠️ Ошибка парсинга {path.name}: {e}")
            except Exception as e:
                logger.warning(f"⚠️ Не удалось прочитать {path.name}: {e}")

        return signals

    # ==========================================================
    # ЧТЕНИЕ ДАННЫХ
    # ==========================================================

    def get_signal(self, signal_id: int) -> Optional[Dict[str, Any]]:
        """Вернуть метаданные сигнала по id."""
        for sig in self.scan_signals():
            if sig["id"] == signal_id:
                return sig
        return None

    def get_signal_data(
        self, signal_id: int, max_points: int = 1000
    ) -> Optional[Dict[str, Any]]:
        """Вернуть данные сигнала для графика."""
        signal = self.get_signal(signal_id)
        if not signal:
            return None

        source_type = signal.get("source_type", "wfdb")

        if source_type in ("csv", "txt"):
            return self._get_csv_data(signal, max_points)
        return self._get_wfdb_data(signal, max_points)

    def _get_wfdb_data(
        self, signal: Dict[str, Any], max_points: int
    ) -> Optional[Dict[str, Any]]:
        try:
            base_name = signal["name"]
            record = wfdb.rdrecord(os.path.join(self.signals_dir, base_name))

            data = (
                record.p_signal[:, 0].tolist()
                if record.p_signal is not None
                else []
            )
            total_points = len(data)

            if total_points > max_points:
                step = total_points // max_points
                data = data[::step][:max_points]

            return {
                "signal_id": signal["id"],
                "name": signal["name"],
                "source_type": "wfdb",
                "fs": record.fs,
                "data": data,
                "total_points": total_points,
                "channels": None,
            }
        except Exception as e:
            logger.error(f"Ошибка чтения WFDB: {e}")
            return None

    def _get_csv_data(
        self, signal: Dict[str, Any], max_points: int
    ) -> Optional[Dict[str, Any]]:
        try:
            from app.core.csv_loader import csv_loader

            path = Path(signal["file_path"])
            if not path.exists():
                logger.error(f"Файл не найден: {path}")
                return None

            sig = csv_loader.load(
                path, fs=signal.get("fs"), name=signal.get("name")
            )
            data_arr = sig.data

            first_channel = data_arr[:, 0].tolist()
            total_points = len(first_channel)

            if total_points > max_points:
                step = total_points // max_points
                first_channel = first_channel[::step][:max_points]

            return {
                "signal_id": signal["id"],
                "name": signal["name"],
                "source_type": signal.get("source_type", "csv"),
                "fs": sig.fs,
                "data": first_channel,
                "total_points": total_points,
                "channels": sig.channels,
            }
        except Exception as e:
            logger.error(f"Ошибка чтения CSV: {e}")
            return None


# Глобальный экземпляр
ecg_loader = ECGLoader()
