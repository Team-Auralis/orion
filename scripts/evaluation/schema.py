from enum import Enum
from dataclasses import dataclass, field, asdict
from typing import Optional, Dict, Any, List
import json
from datetime import datetime, timezone

class BenchmarkState(str, Enum):
    NOT_RUN = "NOT_RUN"
    RUNNING = "RUNNING"
    COMPLETED = "COMPLETED"
    FAILED = "FAILED"
    INVALID = "INVALID"
    EXTERNAL_REFERENCE = "EXTERNAL_REFERENCE"

class BenchmarkType(str, Enum):
    BASELINE_EVAL = "BASELINE_EVAL"
    TARGET_MODEL_EVAL = "TARGET_MODEL_EVAL"
    ACI_EVAL = "ACI_EVAL"
    STRUCTURED_OUTPUT_EVAL = "STRUCTURED_OUTPUT_EVAL"
    LATENCY_EVAL = "LATENCY_EVAL"

@dataclass
class BenchmarkRecord:
    benchmark_id: str
    benchmark_type: str
    model_identity: str
    runtime: str
    quantization: str
    status: BenchmarkState
    timestamp: str
    is_external_reference: bool
    model_checksum: Optional[str] = None
    prompt_template: str = ""
    system_prompt: str = ""
    temperature: float = 0.0
    sampling: str = "greedy"
    seed: int = 42
    tool_configuration: Dict[str, Any] = field(default_factory=dict)
    dataset_version: str = "v1.0"
    test_set: str = ""
    hardware: Dict[str, Any] = field(default_factory=dict)
    software_versions: Dict[str, Any] = field(default_factory=dict)
    raw_output_location: str = ""
    score: Optional[float] = None
    failure_count: int = 0
    metrics: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        d = asdict(self)
        d["status"] = self.status.value if isinstance(self.status, BenchmarkState) else self.status
        return d
