from pydantic import BaseModel
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
    dat_file: Optional[str] = None
    fs: Optional[float] = None
    n_sig: Optional[int] = None
    duration: Optional[float] = None
    size_kb: Optional[float] = None
    signal_type: SignalType = SignalType.ECG

class AnalysisRequest(BaseModel):
    signal_id: int
    params: Dict[str, Any] = {}

class AnalysisResult(BaseModel):
    id: str
    signal_id: int
    status: SignalStatus
    report_markdown: Optional[str] = None
    anomalies: List[Dict[str, Any]] = []
    statistics: Dict[str, Any] = {}
    created_at: datetime = datetime.now()
    processing_time: Optional[float] = None
