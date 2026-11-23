"""
Тесты фазовой логики: ML вызывается ровно один раз на сигнал.

Стратегия: подменяем ml_adapter.analyze_signal и llm_client.* шпионами,
чтобы не требовать GPU и не зависеть от vLLM в CI.
"""

import pytest

from app.core import ml_adapter, llm_client
from app.infrastructure import nn_pipeline


class Spy:
    """Синхронный шпион (для ml_adapter.analyze_signal)."""

    def __init__(self):
        self.calls = 0

    def __call__(self, *args, **kwargs):
        self.calls += 1
        return self._result()

    def _result(self):
        return {
            "model": "deterministic",
            "statistics": {"hr_bpm": 75.0, "rr_mean_ms": 800.0, "sdnn_ms": 10.0,
                           "rmssd_ms": 12.0, "rr_count": 10, "n_leads": 1,
                           "n_samples": 1000, "duration_s": 10.0, "fs": 100.0},
            "anomalies": [],
            "annotation_json": {
                "model": "deterministic",
                "statistics": {"hr_bpm": 75.0, "rr_mean_ms": 800.0, "sdnn_ms": 10.0,
                               "rmssd_ms": 12.0, "rr_count": 10, "n_leads": 1,
                               "n_samples": 1000, "duration_s": 10.0, "fs": 100.0},
                "anomalies": [],
            },
            "annotation_md": "## Аннотация ЭКГ\nЧСС 75.0 уд/мин",
        }


class AsyncSpy:
    """Асинхронный шпион (для llm_client.generate_*)."""

    def __init__(self):
        self.calls = 0

    async def __call__(self, *args, **kwargs):
        self.calls += 1
        return "spy-response"


@pytest.mark.asyncio
async def test_ml_called_once_per_signal(monkeypatch):
    """Три вопроса по одному сигналу -> 1 вызов ML, 4 вызова LLM (1 аннотация + 3 чата)."""
    import numpy as np

    ml_spy = Spy()
    llm_ann = AsyncSpy()
    llm_chat = AsyncSpy()

    monkeypatch.setattr(ml_adapter, "analyze_signal", ml_spy)
    monkeypatch.setattr(llm_client, "generate_annotation_text", llm_ann)
    monkeypatch.setattr(llm_client, "generate_chat_text", llm_chat)

    raw = np.zeros((1, 1000), dtype=np.float32)
    fs = 100.0

    # Фаза A: первый вопрос
    await nn_pipeline.generate_response({"question": "q1", "raw": raw, "fs": fs,
                                          "grade": None, "context": ""})
    # Фаза B: ещё три вопроса (raw=None, context задан)
    for q in ("q2", "q3", "q4"):
        await nn_pipeline.generate_response({"question": q, "raw": None, "fs": fs,
                                              "grade": None, "context": "аннотация"})

    assert ml_spy.calls == 1, f"ML должен вызываться 1 раз, а не {ml_spy.calls}"
    assert llm_ann.calls == 1
    assert llm_chat.calls == 3


@pytest.mark.asyncio
async def test_regeneration_does_not_call_ml(monkeypatch):
    """Перегенерация по готовой аннотации (raw=None) не вызывает ML."""
    ml_spy = Spy()
    llm_chat = AsyncSpy()
    monkeypatch.setattr(ml_adapter, "analyze_signal", ml_spy)
    monkeypatch.setattr(llm_client, "generate_chat_text", llm_chat)

    await nn_pipeline.generate_response({"question": "regen", "raw": None, "fs": 100.0,
                                          "grade": None, "context": "аннотация"})
    assert ml_spy.calls == 0
    assert llm_chat.calls == 1


@pytest.mark.asyncio
async def test_empty_question_raises():
    with pytest.raises(ValueError):
        await nn_pipeline.generate_response({"question": "", "raw": None, "fs": None,
                                              "grade": None, "context": ""})
