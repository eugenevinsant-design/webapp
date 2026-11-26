"""
Загрузчик ЭКГ-сигналов (.hea + .mat).

WFDB-совместимый формат: текстовый заголовок .hea + матрица 'val' в .mat.

Основной путь — wfdb.rdrecord (каноническая библиотека для WFDB-записей).
Если wfdb не установлен (например, serverless-деплой на Vercel, где лимит
250 МБ на функцию не вмещает wfdb+pandas+matplotlib), используется fallback:
scipy.io.loadmat + минимальный парсер .hea — численно идентичен wfdb
(p_signal = (val - baseline) / adc_gain, проверено np.allclose в тестах).

Формат первой строки .hea:
    <name> <n_sig> <fs> <sig_len> ...
Формат строки канала:
    <file> <format> <adc_gain>[(<baseline>)]/<units> <adc_res> <adc_zero> ...
Пример: JS00002.mat 16+24 1000/mV 16 0 -10 12346 0 I
        -> adc_gain=1000, adc_zero=0 -> p_signal = (val - 0) / 1000
"""

import os
import glob
import logging
from datetime import datetime
from typing import List, Dict, Any, Tuple

import numpy as np

logger = logging.getLogger(__name__)

try:
    import wfdb  # канонический путь (Docker/сервер)
    _HAS_WFDB = True
    logger.info("📦 ecg_loader: используется wfdb")
except ImportError:  # serverless (Vercel): wfdb не влезает в лимит 250 МБ
    _HAS_WFDB = False
    logger.info("📦 ecg_loader: wfdb не найден, fallback на scipy.io.loadmat")


def _parse_hea(hea_path: str) -> Tuple[float, int, int, List[Dict[str, Any]]]:
    """Разобрать WFDB-заголовок: (fs, n_sig, sig_len, per-channel gain/baseline)."""
    with open(hea_path, "r", encoding="utf-8", errors="ignore") as f:
        lines = [
            ln.strip() for ln in f
            if ln.strip() and not ln.lstrip().startswith("#")
        ]
    if not lines:
        raise ValueError(f"Пустой .hea: {hea_path}")

    first = lines[0].split()
    n_sig = int(first[1])
    fs = float(first[2].split("/")[0])
    sig_len = int(first[3].split("/")[0])

    channels = []
    for ln in lines[1:1 + n_sig]:
        parts = ln.split()
        gain_field = parts[2] if len(parts) > 2 else "1"
        baseline = None
        if "(" in gain_field:  # формат gain(baseline)/units
            gain_field, rest = gain_field.split("(", 1)
            baseline = float(rest.split(")")[0])
        gain = float(gain_field.split("/")[0])
        adc_zero = float(parts[4]) if len(parts) > 4 else 0.0
        channels.append({
            "gain": gain,
            "baseline": baseline if baseline is not None else adc_zero,
        })
    return fs, n_sig, sig_len, channels


def _read_record_scipy(signals_dir: str, base_name: str):
    """Fallback без wfdb: scipy.io.loadmat + ручной разбор gain/baseline."""
    from scipy.io import loadmat

    hea_path = os.path.join(signals_dir, f"{base_name}.hea")
    mat_path = os.path.join(signals_dir, f"{base_name}.mat")
    fs, n_sig, sig_len, channels = _parse_hea(hea_path)

    val = loadmat(mat_path)["val"].astype(np.float64)  # [C, N] в АЦП-единицах
    gain = np.array([c["gain"] for c in channels], dtype=np.float64)[:, None]
    baseline = np.array([c["baseline"] for c in channels], dtype=np.float64)[:, None]
    p_signal = (val - baseline) / gain  # [C, N] в физических единицах (мВ)
    return p_signal.T, fs, n_sig, sig_len  # [N, C], как у wfdb


def read_record(signals_dir: str, base_name: str):
    """Прочитать запись: (p_signal [N, C] float64, fs, n_sig, sig_len).

    Основной путь — wfdb.rdrecord; если wfdb не установлен (serverless),
    используется scipy-fallback с тем же контрактом возврата.
    """
    if _HAS_WFDB:
        rec = wfdb.rdrecord(os.path.join(signals_dir, base_name))
        p_signal = np.asarray(rec.p_signal, dtype=np.float64)  # [N, C]
        return p_signal, float(rec.fs), int(rec.n_sig), int(rec.sig_len)
    return _read_record_scipy(signals_dir, base_name)


class ECGLoader:
    def __init__(self, signals_dir="./data/signals"):
        self.signals_dir = signals_dir
        os.makedirs(signals_dir, exist_ok=True)
        logger.info(f"📂 Загрузчик ЭКГ инициализирован: {signals_dir}")
        self._cache = []
        self._last_scan = None

    def scan_signals(self, force: bool = False) -> List[Dict[str, Any]]:
        """Сканирование папки с .hea + .mat файлами"""

        if not force and self._cache and self._last_scan:
            return self._cache

        signals = []

        if not os.path.exists(self.signals_dir):
            logger.warning(f"⚠️ Папка {self.signals_dir} не существует")
            return []

        hea_files = glob.glob(os.path.join(self.signals_dir, "*.hea"))
        logger.info(f"🔍 Найдено .hea файлов: {len(hea_files)}")

        for idx, hea_path in enumerate(hea_files, 1):
            try:
                file_name = os.path.basename(hea_path)
                base_name = os.path.splitext(file_name)[0]

                # Ищем .mat файл вместо .dat
                mat_path = os.path.join(self.signals_dir, f"{base_name}.mat")

                if not os.path.exists(mat_path):
                    logger.warning(f"⚠️ Нет .mat для {base_name}, пропускаем")
                    continue

                # Метаданные читаем только из заголовка — быстро, без
                # загрузки всей матрицы сигнала
                try:
                    fs, n_sig, sig_len, _ = _parse_hea(hea_path)
                    duration = sig_len / fs if fs else None
                except Exception as e:
                    logger.warning(f"⚠️ Ошибка чтения {base_name}: {e}")
                    fs = None
                    n_sig = None
                    duration = None

                file_size = os.path.getsize(hea_path) + os.path.getsize(mat_path)

                signals.append({
                    "id": idx,
                    "name": base_name,
                    "file_name": file_name,
                    "file_path": hea_path,
                    "mat_file": mat_path,
                    "fs": fs,
                    "n_sig": n_sig,
                    "duration": duration,
                    "size_kb": round(file_size / 1024, 1),
                    "signal_type": "ecg"
                })

                logger.info(f"✅ Загружен: {file_name} (fs={fs}Hz)")

            except Exception as e:
                logger.error(f"❌ Ошибка загрузки {hea_path}: {e}")

        self._cache = signals
        self._last_scan = datetime.now()

        logger.info(f"📊 Всего загружено: {len(signals)} сигналов")
        return signals

    def get_signal_data(self, signal_id: int, max_points: int = 1000):
        """Получить данные сигнала для отображения"""
        signals = self.scan_signals()
        signal = None
        for s in signals:
            if s["id"] == signal_id:
                signal = s
                break

        if not signal:
            return None

        try:
            base_name = signal["name"]
            p_signal, fs, _, _ = read_record(self.signals_dir, base_name)

            data = p_signal[:, 0].tolist() if p_signal is not None else []

            if len(data) > max_points:
                step = len(data) // max_points
                data = data[::step][:max_points]

            return {
                "signal_id": signal_id,
                "name": signal["name"],
                "fs": fs,
                "data": data,
                "total_points": len(p_signal) if p_signal is not None else 0
            }
        except Exception as e:
            logger.error(f"Ошибка чтения данных: {e}")
            return None

    def load_raw_signal(self, pkg_name: str) -> tuple:
        """
        Загрузить полный 12-канальный сигнал.

        Используется для передачи в NN-пайплайн (требование ТЗ:
        "12-канальная временная запись").

        НЕ путать с get_signal_data (он отдает 1 канал для графика).

        Args:
            pkg_name: имя пакета (например, "patient_001").

        Returns:
            tuple: (raw, fs), где raw — np.ndarray (все каналы), fs — float.
                   Если файл не найден или ошибка — (None, None).
        """
        try:
            p_signal, fs, _, _ = read_record(self.signals_dir, pkg_name)
            if p_signal is None:
                logger.warning(f"⚠️ Нет p_signal для {pkg_name}")
                return None, None
            raw = p_signal  # [N_samples, n_sig]
            # Контракт пайплайна — [C, N]. Файл отдаёт [N, C], поэтому
            # приводим к [C, N] здесь, на границе загрузки (единая точка).
            if raw.ndim == 2:
                raw = raw.T
            logger.info(f"📥 Загружен raw: {pkg_name} (shape={raw.shape}, fs={fs})")
            return raw, fs
        except Exception as e:
            logger.error(f"❌ Ошибка загрузки raw для {pkg_name}: {e}")
            return None, None


# Глобальный экземпляр
ecg_loader = ECGLoader()
