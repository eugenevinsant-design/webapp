"""
Детерминированный ML-бэк для ЭКГ: работает БЕЗ весов и GPU.

Реализует тот же контракт выхода, что и будущая torch-модель
(см. ml_adapter.analyze_with_torch), чтобы приложение работало уже сейчас.

Алгоритм:
1. Полосовой фильтр Баттерворта 0.5-40 Гц (убирает базовую линию и шум).
2. Поиск R-пиков: детрендинг + порог + scipy.signal.find_peaks.
3. Метрики: ЧСС, RR-интервалы, SDNN, RMSSD.
4. Флаги аномалий: bradycardia, tachycardia, irregular_rhythm.

Все числа РЕАЛЬНЫЕ (посчитаны по сигналу), текст отчета собирает LLM.
"""

import logging
from typing import Any, Dict, List

import numpy as np
from scipy import signal as sp_signal

logger = logging.getLogger(__name__)

HR_MIN = 50.0          # bpm: ниже — bradycardia
HR_MAX = 100.0         # bpm: выше — tachycardia
IRR_RMSSD_MS = 150.0   # ms: RMSSD выше — признак нерегулярного ритма
IRR_CV = 0.15          # коэффициент вариации RR выше — нерегулярный ритм


def _select_lead(raw: np.ndarray) -> np.ndarray:
    """Выбрать канал для анализа из [C, N] (или [N, C]).

    Контракт пайплайна — [C, N], но на границах (wfdb, внешние вызовы)
    может прийти [N, C]. Определяем ось отсчётов по размеру: каналов
    обычно <= 12, отсчётов — тысячи. Возвращает 1-D массив отсчётов.
    """
    arr = np.asarray(raw, dtype=np.float64)
    if arr.ndim == 1:
        return arr
    if arr.ndim != 2:
        raise ValueError(f"ожидался [C, N] или [N], получено shape={arr.shape}")

    # Ось каналов короткая (обычно <= 16), ось отсчётов — длинная (тысячи).
    # Если короткая ось оказалась второй ([N, C]) — приводим к [C, N].
    if arr.shape[1] <= 16 < arr.shape[0]:
        arr = arr.T

    if arr.shape[0] > 1:
        variances = np.var(arr, axis=1)
        return arr[int(np.argmax(variances))]
    return arr[0]


def _bandpass(x: np.ndarray, fs: float, low: float = 0.5, high: float = 40.0) -> np.ndarray:
    """Полосовой фильтр. При слишком малой fs — только удаление среднего."""
    nyq = fs / 2.0
    if nyq <= low:
        return x - np.mean(x)
    high = min(high, nyq * 0.95)
    sos = sp_signal.butter(2, [low / nyq, high / nyq], btype="band", output="sos")
    return sp_signal.sosfiltfilt(sos, x)


def _find_r_peaks(x: np.ndarray, fs: float) -> np.ndarray:
    """Поиск R-пиков на отфильтрованном сигнале. Возвращает индексы."""
    detrended = sp_signal.detrend(x)
    std = float(np.std(detrended)) or 1.0
    peaks, _ = sp_signal.find_peaks(
        detrended,
        height=0.4 * std,
        distance=max(1, int(0.3 * fs)),
        prominence=0.3 * std,
    )
    return peaks


def _flags(hr: float, rr_ms: np.ndarray) -> List[Dict[str, Any]]:
    """Флаги аномалий по метрикам ритма."""
    anomalies: List[Dict[str, Any]] = []
    if hr < HR_MIN:
        anomalies.append({
            "type": "bradycardia",
            "severity": "high" if hr < 40 else "medium",
            "description": f"ЧСС {hr:.1f} уд/мин ниже порога {HR_MIN:.0f}",
        })
    if hr > HR_MAX:
        anomalies.append({
            "type": "tachycardia",
            "severity": "high" if hr > 130 else "medium",
            "description": f"ЧСС {hr:.1f} уд/мин выше порога {HR_MAX:.0f}",
        })
    if rr_ms.size >= 4:
        rmssd = float(np.sqrt(np.mean(np.diff(rr_ms) ** 2)))
        cv = float(np.std(rr_ms) / np.mean(rr_ms)) if np.mean(rr_ms) else 0.0
        if rmssd > IRR_RMSSD_MS or cv > IRR_CV:
            anomalies.append({
                "type": "irregular_rhythm",
                "severity": "medium",
                "description": f"Нерегулярный ритм: RMSSD={rmssd:.0f} мс, CV={cv:.2f}",
            })
    return anomalies


def analyze_signal(raw, fs: float) -> Dict[str, Any]:
    """
    Полный анализ сигнала. Возвращает statistics + anomalies.

    Контракт выхода (заморожен, совпадает с torch-моделью):
        {
            "model": "deterministic",
            "statistics": {hr_bpm, rr_mean_ms, sdnn_ms, rmssd_ms,
                           rr_count, n_leads, n_samples, duration_s, fs},
            "anomalies": [{"type", "severity", "description"}],
        }
    """
    arr = np.asarray(raw)
    fs_f = float(fs)
    lead = _select_lead(arr)
    filtered = _bandpass(lead, fs_f)
    peaks = _find_r_peaks(filtered, fs_f)

    n_peaks = int(peaks.size)
    duration_s = lead.size / fs_f

    if n_peaks < 3:
        logger.warning("Найдено менее 3 R-пиков — анализ ритма ненадежен")
        return {
            "model": "deterministic",
            "statistics": {
                "hr_bpm": None,
                "rr_mean_ms": None,
                "sdnn_ms": None,
                "rmssd_ms": None,
                "rr_count": max(0, n_peaks - 1),
                "n_leads": int(arr.shape[0]) if arr.ndim == 2 else 1,
                "n_samples": int(lead.size),
                "duration_s": round(duration_s, 3),
                "fs": fs_f,
            },
            "anomalies": [{
                "type": "low_quality",
                "severity": "medium",
                "description": f"Найдено всего {n_peaks} R-пиков на {duration_s:.1f} с — сигнал плохого качества или слишком короткий",
            }],
        }

    rr_ms = np.diff(peaks) / fs_f * 1000.0
    rr_ms = rr_ms[(rr_ms > 300) & (rr_ms < 3000)]  # отсекаем выбросы
    hr = 60000.0 / float(np.median(rr_ms)) if rr_ms.size else None
    sdnn = float(np.std(rr_ms)) if rr_ms.size else None
    rmssd = float(np.sqrt(np.mean(np.diff(rr_ms) ** 2))) if rr_ms.size >= 2 else None

    statistics = {
        "hr_bpm": round(hr, 1) if hr else None,
        "rr_mean_ms": round(float(np.mean(rr_ms)), 1) if rr_ms.size else None,
        "sdnn_ms": round(sdnn, 1) if sdnn else None,
        "rmssd_ms": round(rmssd, 1) if rmssd else None,
        "rr_count": int(rr_ms.size),
        "n_leads": int(arr.shape[0]) if arr.ndim == 2 else 1,
        "n_samples": int(lead.size),
        "duration_s": round(duration_s, 3),
        "fs": fs_f,
    }
    anomalies = _flags(hr, rr_ms) if hr else []
    return {"model": "deterministic", "statistics": statistics, "anomalies": anomalies}
