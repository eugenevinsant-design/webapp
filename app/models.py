from pydantic import BaseModel, Field
from typing import Optional, List, Dict, Any
from datetime import datetime
from enum import Enum


class SignalType(str, Enum):
    ECG = "ecg"
    VIBRATION = "vibration"


class SignalStatus(str, Enum):
    PENDING = "pending"
    PROCESSING = "processing"
    COMPLETED = "completed"
    FAILED = "failed"


class ECGSignal(BaseModel):
    id: int
    name: str
    file_name: str
    file_path: str
    mat_file: Optional[str] = None          # было dat_file — синхронизировано с ecg_loader.py
    fs: Optional[float] = None
    n_sig: Optional[int] = None
    duration: Optional[float] = None
    size_kb: Optional[float] = None
    signal_type: SignalType = SignalType.ECG


class AnalysisRequest(BaseModel):
    signal_id: int
    params: Dict[str, Any] = Field(default_factory=dict)


class AnalysisResult(BaseModel):
    id: str
    signal_id: int
    status: SignalStatus
    report_markdown: Optional[str] = None
    anomalies: List[Dict[str, Any]] = Field(default_factory=list)
    statistics: Dict[str, Any] = Field(default_factory=dict)
    created_at: datetime = Field(default_factory=datetime.now)
    processing_time: Optional[float] = None