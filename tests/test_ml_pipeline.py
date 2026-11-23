"""
Тесты реального ML-пути (без моков).

Цель: ловить регрессии, которые не видны при замоканном ML:
1. Ориентация сигнала: wfdb отдаёт [N, C], пайплайн ждёт [C, N].
2. Детерминированный анализатор возвращает валидные метрики на реальном ритме.
3. ecg_loader.load_raw_signal отдаёт [C, N] (регресс-тест на баг с транспонированием).
4. ml_adapter не падает и возвращает полный контракт выхода.

Эти тесты НЕ требуют GPU, LLM и сети — только numpy/scipy/wfdb.
"""

import os

import numpy as np
import pytest

from app.core import signal_analyzer
from app.core import ml_adapter
from app.core.ml_input import build_ml_input


SIGNALS_DIR = "./data/signals"


def _synthetic_ecg(n_samples: int = 5000, fs: float = 500.0, hr_bpm: float = 60.0):
    """Сгенерировать синтетический 1-канальный ЭКГ с заданной ЧСС.

    Возвращает [1, N] float32. R-пики — узкие гауссовы импульсы.
    """
    t = np.arange(n_samples) / fs
    rr = 60.0 / hr_bpm
    x = np.zeros(n_samples, dtype=np.float64)
    beat = 0.0
    while beat < t[-1]:
        idx = int(beat * fs)
        if 0 <= idx < n_samples:
            # гауссов R-пик шириной ~10 мс
            width = max(1.0, 0.01 * fs)
            lo = max(0, idx - int(3 * width))
            hi = min(n_samples, idx + int(3 * width))
            tt = np.arange(lo, hi)
            x[lo:hi] += 1.0 * np.exp(-((tt - idx) ** 2) / (2 * width ** 2))
        beat += rr
    # небольшой дрейф базовой линии + шум
    x += 0.05 * np.sin(2 * np.pi * 0.3 * t)
    x += 0.01 * np.random.RandomState(42).randn(n_samples)
    return x[None, :].astype(np.float32)


# --------------------------------------------------------------- ориентация

def test_signal_analyzer_accepts_c_by_n():
    """[C, N] — целевой контракт пайплайна. Анализ должен пройти."""
    raw = _synthetic_ecg(hr_bpm=60.0)
    assert raw.shape == (1, 5000)
    result = signal_analyzer.analyze_signal(raw, 500.0)
    assert result["model"] == "deterministic"
    assert result["statistics"]["hr_bpm"] is not None
    assert 50 <= result["statistics"]["hr_bpm"] <= 70


def test_signal_analyzer_transposed_input_does_not_crash():
    """Если случайно подать [N, C] (1 канал), анализ не должен падать.

    Регресс-тест на исторический баг: wfdb отдаёт [N, C], а фильтр падал
    на коротком векторе (12 отсчётов вместо 5000).
    """
    raw_cn = _synthetic_ecg(hr_bpm=60.0)          # [1, 5000]
    raw_nc = raw_cn.T                              # [5000, 1]
    # build_ml_input нормализует форму; убеждаемся, что не бросает
    inp = build_ml_input(raw_nc, 500.0)
    assert inp["signal"].ndim == 2
    # Сам анализатор на транспонированном 1-канальном входе также не падает
    result = signal_analyzer.analyze_signal(raw_nc, 500.0)
    assert "statistics" in result


def test_ecg_loader_returns_c_by_n(monkeypatch):
    """load_raw_signal обязан отдавать [C, N], даже если wfdb даёт [N, C]."""
    from app.core.ecg_loader import ECGLoader

    class FakeRecord:
        p_signal = np.zeros((5000, 12), dtype=np.float32)  # как wfdb: [N, C]
        fs = 500.0

    loader = ECGLoader(signals_dir=SIGNALS_DIR)
    monkeypatch.setattr("wfdb.rdrecord", lambda *a, **k: FakeRecord())

    raw, fs = loader.load_raw_signal("whatever")
    assert fs == 500.0
    assert raw.shape == (12, 5000), f"ожидалось [C, N]=(12,5000), получено {raw.shape}"


# --------------------------------------------------------------- контракт ML

def test_ml_adapter_full_contract():
    """analyze_signal возвращает полный замороженный контракт выхода."""
    raw = _synthetic_ecg(hr_bpm=60.0)
    out = ml_adapter.analyze_signal(raw, 500.0)

    for key in ("model", "statistics", "anomalies", "annotation_json", "annotation_md"):
        assert key in out, f"нет ключа {key} в контракте"

    st = out["statistics"]
    for key in ("hr_bpm", "rr_mean_ms", "sdnn_ms", "rmssd_ms", "rr_count",
                "n_leads", "n_samples", "duration_s", "fs"):
        assert key in st, f"нет метрики {key} в statistics"

    assert st["n_leads"] == 1
    assert st["n_samples"] == 5000
    assert st["duration_s"] == pytest.approx(10.0, abs=0.01)
    assert isinstance(out["annotation_md"], str) and out["annotation_md"].strip()


def test_ml_adapter_detects_tachycardia():
    """Высокая ЧСС -> флаг tachycardia."""
    raw = _synthetic_ecg(hr_bpm=130.0)
    out = ml_adapter.analyze_signal(raw, 500.0)
    types = {a["type"] for a in out["anomalies"]}
    assert "tachycardia" in types, f"ожидали tachycardia, получили {types}"


def test_ml_adapter_detects_bradycardia():
    """Низкая ЧСС -> флаг bradycardia."""
    raw = _synthetic_ecg(hr_bpm=40.0)
    out = ml_adapter.analyze_signal(raw, 500.0)
    types = {a["type"] for a in out["anomalies"]}
    assert "bradycardia" in types, f"ожидали bradycardia, получили {types}"


def test_ml_adapter_low_quality_on_flat_signal():
    """Плоский сигнал -> low_quality, без выдуманного ЧСС."""
    raw = np.zeros((1, 5000), dtype=np.float32)
    out = ml_adapter.analyze_signal(raw, 500.0)
    assert out["statistics"]["hr_bpm"] is None
    types = {a["type"] for a in out["anomalies"]}
    assert "low_quality" in types


# --------------------------------------------------------------- реальные файлы

@pytest.mark.skipif(
    not os.path.isdir(SIGNALS_DIR) or not any(f.endswith(".hea") for f in os.listdir(SIGNALS_DIR)),
    reason="нет реальных сигналов в data/signals",
)
@pytest.mark.asyncio
async def test_real_signal_end_to_end_ml():
    """Реальный .hea/.mat -> load_raw_signal -> analyze_signal -> валидные метрики."""
    from app.core.ecg_loader import ecg_loader

    packages = [p for p in ecg_loader.scan_signals(force=True) if p.get("fs")]
    assert packages, "в data/signals не найдено валидных записей (.hea + .mat)"

    pkg = packages[0]["name"]
    raw, fs = ecg_loader.load_raw_signal(pkg)
    assert raw is not None and fs is not None
    assert raw.ndim == 2
    assert raw.shape[0] <= raw.shape[1], f"ожидалась [C, N], получено {raw.shape}"

    out = ml_adapter.analyze_signal(raw, fs)
    assert out["model"] == "deterministic"
    assert out["statistics"]["n_leads"] == raw.shape[0]
    # главное: анализ не упал и вернул Markdown-аннотацию
    assert out["annotation_md"]
