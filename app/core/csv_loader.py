# app/core/csv_loader.py
"""
CSV/TXT лоадер для ЭКГ-сигналов.

Поддерживаемые форматы (автоопределение):
  1. PhysioNet-CSV:  time,ch1,ch2,...   (первая колонка — время в секундах)
  2. 1 колонка:      value
  3. 2 колонки:      time,value   ИЛИ   value,value
  4. N колонок:      time,ch1,ch2,...,chN
  5. TXT:            числа, разделённые пробелами/запятыми/переносами

Возвращает dict, совместимый с ecg_loader.
"""

from __future__ import annotations

import csv
import logging
import os
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Iterable, List, Optional

import numpy as np

logger = logging.getLogger(__name__)

# ============================================================
# КОНСТАНТЫ
# ============================================================

DEFAULT_FS = 500.0                 # Гц — стандарт для ЭКГ
MAX_FILE_SIZE_MB = 300             # лимит загрузки (Render Free = 512 МБ RAM)
MAX_FILE_SIZE_BYTES = MAX_FILE_SIZE_MB * 1024 * 1024
MAX_CHANNELS = 32                  # защита от «мусорных» CSV
MAX_PREVIEW_POINTS = 100_000       # сколько точек отдавать на фронт
ALLOWED_EXTENSIONS = {".csv", ".txt"}
COMMENT_PREFIXES = ("#", "//", "%")


# ============================================================
# ИСКЛЮЧЕНИЯ
# ============================================================

class CSVParsingError(Exception):
    """Ошибка парсинга CSV/TXT."""


class CSVTooLargeError(CSVParsingError):
    """Файл больше допустимого."""


class CSVFormatError(CSVParsingError):
    """Не удалось определить формат."""


# ============================================================
# ДАТАКЛАСС РЕЗУЛЬТАТА
# ============================================================

@dataclass
class CSVSignal:
    name: str
    file_name: str
    file_path: str
    source_type: str
    fs: float
    n_sig: int
    sig_len: int
    duration: float
    channels: List[str]
    data: np.ndarray

    def to_dict(self, signal_id: int) -> dict:
        size_bytes = os.path.getsize(self.file_path) if os.path.exists(self.file_path) else 0
        return {
            "id": signal_id,
            "name": self.name,
            "file_name": self.file_name,
            "file_path": self.file_path,
            "source_type": self.source_type,
            "mat_file": None,
            "fs": self.fs,
            "n_sig": self.n_sig,
            "sig_len": self.sig_len,
            "duration": round(self.duration, 3),
            "size_kb": round(size_bytes / 1024, 1),
            "channels": self.channels,
            "signal_type": "ecg",
            "uploaded_at": datetime.now().isoformat(),
        }


# ============================================================
# ОСНОВНОЙ КЛАСС
# ============================================================

class CSVLoader:
    """Загрузчик CSV/TXT сигналов."""

    def __init__(self, uploads_dir: str = "./data/uploads"):
        self.uploads_dir = Path(uploads_dir)
        self.uploads_dir.mkdir(parents=True, exist_ok=True)
        logger.info(f"📂 CSVLoader инициализирован: {self.uploads_dir}")

    # ---------- публичный API ----------

    def load(
        self,
        file_path: str | Path,
        fs: Optional[float] = None,
        name: Optional[str] = None,
        delimiter: Optional[str] = None,
    ) -> CSVSignal:
        path = Path(file_path)
        if not path.exists():
            raise CSVParsingError(f"Файл не найден: {path}")

        ext = path.suffix.lower()
        if ext not in ALLOWED_EXTENSIONS:
            raise CSVFormatError(
                f"Неподдерживаемое расширение: {ext}. "
                f"Допустимо: {', '.join(ALLOWED_EXTENSIONS)}"
            )

        size_bytes = path.stat().st_size
        if size_bytes > MAX_FILE_SIZE_BYTES:
            raise CSVTooLargeError(
                f"Файл {size_bytes / 1024 / 1024:.1f} МБ превышает лимит "
                f"{MAX_FILE_SIZE_MB} МБ"
            )
        if size_bytes == 0:
            raise CSVParsingError("Файл пустой")

        actual_fs = float(fs) if fs and fs > 0 else DEFAULT_FS
        signal_name = name or path.stem
        source_type = "csv" if ext == ".csv" else "txt"

        try:
            channels, data, detected_fs = self._parse_file(
                path, delimiter=delimiter, user_fs=fs
            )
        except CSVParsingError:
            raise
        except Exception as e:
            raise CSVParsingError(f"Ошибка парсинга {path.name}: {e}") from e

        if not fs and detected_fs:
            actual_fs = detected_fs

        sig_len, n_sig = data.shape
        duration = sig_len / actual_fs if actual_fs > 0 else 0.0

        logger.info(
            f"✅ Загружен {path.name}: {n_sig} кан., "
            f"{sig_len} точек, fs={actual_fs} Гц"
        )

        return CSVSignal(
            name=signal_name,
            file_name=path.name,
            file_path=str(path),
            source_type=source_type,
            fs=actual_fs,
            n_sig=n_sig,
            sig_len=sig_len,
            duration=duration,
            channels=channels,
            data=data,
        )

    # ---------- парсинг ----------

    def _parse_file(
        self,
        path: Path,
        delimiter: Optional[str],
        user_fs: Optional[float],
    ) -> tuple[List[str], np.ndarray, Optional[float]]:
        ext = path.suffix.lower()
        if ext == ".txt":
            return self._parse_txt(path)

        last_error: Optional[Exception] = None
        for encoding in ("utf-8-sig", "utf-8", "latin-1", "cp1251"):
            try:
                with path.open("r", encoding=encoding, newline="") as f:
                    sample = f.read(64 * 1024)
                    f.seek(0)
                    if not sample.strip():
                        raise CSVParsingError("Файл пустой")
                    dialect = self._sniff_dialect(sample, delimiter)
                    reader = csv.reader(f, dialect)
                    return self._consume_rows(reader, user_fs)
            except UnicodeDecodeError as e:
                last_error = e
                continue

        raise CSVParsingError(
            f"Не удалось определить кодировку {path.name}: {last_error}"
        )

    def _parse_txt(self, path: Path) -> tuple[List[str], np.ndarray, Optional[float]]:
        last_error: Optional[Exception] = None
        for encoding in ("utf-8-sig", "utf-8", "latin-1", "cp1251"):
            try:
                with path.open("r", encoding=encoding) as f:
                    rows: List[List[float]] = []
                    channels: Optional[List[str]] = None

                    for raw_line in f:
                        line = raw_line.strip()
                        if not line or line.startswith(COMMENT_PREFIXES):
                            continue

                        if channels is None and self._line_has_alpha(line):
                            channels = [
                                c.strip() or f"ch{i+1}"
                                for i, c in enumerate(self._split_txt_line(line))
                            ]
                            continue

                        values = self._split_txt_line(line)
                        nums = self._to_floats(values, skip_invalid=True)
                        if nums:
                            rows.append(nums)

                    if not rows:
                        raise CSVParsingError("В TXT не найдено ни одного числа")

                    data = self._rows_to_array(rows)

                if channels is None:
                    channels = [f"ch{i+1}" for i in range(data.shape[1])]
                elif len(channels) != data.shape[1]:
                    logger.warning(
                        f"Каналов в заголовке {len(channels)}, "
                        f"в данных {data.shape[1]} — использую имена по порядку"
                    )
                    channels = [f"ch{i+1}" for i in range(data.shape[1])]

                detected_fs = self._detect_fs_from_time(data, channels)
                data, channels = self._strip_time_column(data, channels, detected_fs)
                return channels, data, detected_fs

            except UnicodeDecodeError as e:
                last_error = e
                continue

        raise CSVParsingError(f"Не удалось прочитать TXT: {last_error}")

    # ---------- вспомогательные ----------

    @staticmethod
    def _sniff_dialect(sample: str, user_delimiter: Optional[str]) -> csv.Dialect:
        if user_delimiter:
            class _D(csv.excel):
                delimiter = user_delimiter
            return _D
        try:
            return csv.Sniffer().sniff(sample, delimiters=",;\t|")
        except csv.Error:
            class _D(csv.excel):
                delimiter = ","
            return _D

    def _consume_rows(
        self,
        reader: Iterable[List[str]],
        user_fs: Optional[float],
    ) -> tuple[List[str], np.ndarray, Optional[float]]:
        channels: Optional[List[str]] = None
        rows: List[List[float]] = []

        for raw_row in reader:
            if not raw_row:
                continue
            row = [c.strip() for c in raw_row]
            if not any(row):
                continue
            if row[0].startswith(COMMENT_PREFIXES):
                continue

            if channels is None and self._line_has_alpha_row(row):
                channels = [c or f"ch{i+1}" for i, c in enumerate(row)]
                continue

            nums = self._to_floats(row, skip_invalid=True)
            if not nums:
                continue
            rows.append(nums)

        if not rows:
            raise CSVParsingError("В файле нет числовых данных")

        data = self._rows_to_array(rows)

        if channels is None:
            channels = [f"ch{i+1}" for i in range(data.shape[1])]
        elif len(channels) != data.shape[1]:
            logger.warning(
                f"Каналов в заголовке {len(channels)}, "
                f"в данных {data.shape[1]} — использую имена по порядку"
            )
            channels = [f"ch{i+1}" for i in range(data.shape[1])]

        detected_fs = self._detect_fs_from_time(data, channels)
        data, channels = self._strip_time_column(data, channels, detected_fs)
        return channels, data, detected_fs

    @staticmethod
    def _line_has_alpha(line: str) -> bool:
        return any(c.isalpha() for c in line)

    @staticmethod
    def _line_has_alpha_row(row: List[str]) -> bool:
        return any(any(c.isalpha() for c in cell) for cell in row)

    @staticmethod
    def _split_txt_line(line: str) -> List[str]:
        for sep in ("\t", ";", "|", ","):
            line = line.replace(sep, " ")
        return [c for c in line.split(" ") if c]

    @staticmethod
    def _to_floats(cells: Iterable[str], skip_invalid: bool = True) -> List[float]:
        out: List[float] = []
        for c in cells:
            c = c.strip().replace(",", ".") if "," in c and "." not in c else c.strip()
            if not c:
                continue
            try:
                out.append(float(c))
            except ValueError:
                if not skip_invalid:
                    raise
                continue
        return out

    @staticmethod
    def _rows_to_array(rows: List[List[float]]) -> np.ndarray:
        min_len = min(len(r) for r in rows)
        if min_len == 0:
            raise CSVParsingError("Строки без чисел")
        arr = np.array([r[:min_len] for r in rows], dtype=np.float32)
        if arr.ndim != 2 or arr.shape[0] < 2:
            raise CSVParsingError("Недостаточно данных для сигнала")
        if arr.shape[1] > MAX_CHANNELS:
            raise CSVParsingError(
                f"Слишком много каналов: {arr.shape[1]} > {MAX_CHANNELS}"
            )
        return arr

    @staticmethod
    def _detect_fs_from_time(
        data: np.ndarray, channels: List[str]
    ) -> Optional[float]:
        if data.shape[1] < 2:
            return None
        first_col = data[:, 0]
        if not np.all(np.diff(first_col) > 0):
            return None
        dt = float(np.mean(np.diff(first_col)))
        if dt <= 0:
            return None
        if 1e-4 <= dt <= 1.0:
            fs = round(1.0 / dt, 3)
            logger.info(f"⏱ fs из колонки времени: {fs} Гц")
            return fs
        return None

    @staticmethod
    def _strip_time_column(
        data: np.ndarray,
        channels: List[str],
        detected_fs: Optional[float],
    ) -> tuple[np.ndarray, List[str]]:
        if detected_fs is None:
            return data, channels
        return data[:, 1:], channels[1:]


# ============================================================
# ГЛОБАЛЬНЫЙ ЭКЗЕМПЛЯР
# ============================================================

csv_loader = CSVLoader()
