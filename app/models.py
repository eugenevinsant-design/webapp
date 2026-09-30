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


class SourceType(str, Enum):
    WFDB = "wfdb"
    CSV = "csv"
    TXT = "txt"


class ECGSignal(BaseModel):
    id: int
    name: str
    file_name: str
    file_path: str

    source_type: SourceType = SourceType.WFDB
    mat_file: Optional[str] = None
    upload_id: Optional[str] = None

    fs: Optional[float] = None
    n_sig: Optional[int] = None
    sig_len: Optional[int] = None
    duration: Optional[float] = None
    size_kb: Optional[float] = None
    channels: Optional[List[str]] = None

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
