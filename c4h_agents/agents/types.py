"""
Core type definitions for agent system.
Path: c4h_agents/agents/types.py
"""

from typing import Dict, Any, Optional, List, Literal
from enum import Enum
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path

class LogDetail(str, Enum):
    """Log detail levels for agent operations"""
    MINIMAL = "minimal"     # Only errors and critical info
    BASIC = "basic"        # Standard operation logging
    DETAILED = "detailed"  # Full operation details
    DEBUG = "debug"        # Debug level with content samples
    
    @classmethod
    def from_str(cls, level: str) -> 'LogDetail':
        """Convert string to LogDetail with safe fallback"""
        try:
            return cls(level.lower())
        except ValueError:
            return cls.BASIC

class LLMProvider(str, Enum):
    """Supported model providers"""
    ANTHROPIC = "anthropic"
    OPENAI = "openai"
    GEMINI = "gemini"

    def __str__(self) -> str:
        """Safe string conversion ensuring no interpolation issues"""
        return str(self.value)

    def serialize(self) -> str:
        """Safe serialization for metrics and logging"""
        return f"provider_{self.value}"

@dataclass
class AgentConfig:
    """Configuration requirements for agent instantiation"""
    provider: Literal['anthropic', 'openai', 'gemini']
    model: str
    temperature: float = 0
    api_base: Optional[str] = None
    context_length: Optional[int] = None
    max_retries: int = 3
    retry_delay: int = 30
    log_level: LogDetail = LogDetail.BASIC

"""
Core type definitions for agent system.
Path: c4h_agents/agents/types.py
"""


@dataclass
class AgentMetrics:
    """Standard metrics tracking for agent operations with mutable dictionary interface"""
    _data: Dict[str, Any] = field(default_factory=lambda: {
        "total_requests": 0,
        "successful_requests": 0,
        "failed_requests": 0,
        "total_duration": 0.0,
        "continuation_attempts": 0,
        "last_error": None,
        "start_time": datetime.utcnow().isoformat(),
        "project": None
    })

    def __getitem__(self, key: str) -> Any:
        return self._data[key]
        
    def __setitem__(self, key: str, value: Any) -> None:
        self._data[key] = value

    def to_dict(self) -> Dict[str, Any]:
        """Convert metrics to plain dictionary for serialization"""
        return self._data.copy()

@dataclass
class AgentResponse:
    """Standard response format for all agent operations"""
    success: bool
    data: Dict[str, Any]
    error: Optional[str] = None
    raw_input: Optional[Dict[str, Any]] = None    # Complete input including prompts
    raw_output: Optional[Dict[str, Any]] = None   # Complete output from LLM
    metrics: Optional[Dict[str, Any]] = None
    timestamp: datetime = field(default_factory=datetime.utcnow)

@dataclass 
class ProjectPaths:
    """Standard paths used across agent operations"""
    root: Path              # Project root directory
    workspace: Path         # Working files location  
    source: Path           # Source code directory
    output: Path           # Output directory
    config: Path           # Configuration location
    backup: Optional[Path] = None  # Optional backup directory