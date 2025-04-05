"""
Core type definitions for agent system.
Path: c4h_agents/agents/types.py
"""

from typing import Dict, Any, Optional, List, Literal, Union
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
class LLMMessages:
    """Complete message set for LLM interactions"""
    system: str                       # System prompt/persona
    user: str                        # User message content
    formatted_request: str = ""      # Optional formatted request (only if different from user)
    raw_context: Dict[str, Any] = field(default_factory=dict)      # Original input context
    timestamp: datetime = field(default_factory=datetime.utcnow)

    def __post_init__(self):
        """Prevent duplicate storage of content"""
        if self.formatted_request and self.formatted_request == self.user:
            self.formatted_request = ""  # Clear if identical to user message

    def to_dict(self) -> Dict[str, Any]:
        """Convert messages to dictionary for logging"""
        result = {
            "system": self.system,
            "user": self.user,
            "timestamp": self.timestamp.isoformat()
        }
        # Only include formatted_request if it contains unique content
        if self.formatted_request and self.formatted_request != self.user:
            result["formatted_request"] = self.formatted_request
        return result

@dataclass
class AgentResponse:
    """Standard response format for all agent operations"""
    success: bool
    data: Dict[str, Any]
    error: Optional[str] = None
    messages: Optional[LLMMessages] = None      # Complete messages including system prompt
    raw_output: Optional[Dict[str, Any]] = None # Complete output from LLM
    metrics: Optional[Dict[str, Any]] = None    # Performance metrics
    timestamp: datetime = field(default_factory=datetime.utcnow)

"""
Quick fix for AgentMetrics to add dict access while keeping dataclass structure.
Path: c4h_agents/agents/types.py
"""

@dataclass 
class AgentMetrics:
    """Standard metrics tracking for agent operations"""
    total_requests: int = 0
    successful_requests: int = 0
    failed_requests: int = 0
    total_duration: float = 0.0
    continuation_attempts: int = 0
    last_error: Optional[str] = None
    start_time: str = field(default_factory=lambda: datetime.utcnow().isoformat())
    project: Optional[str] = None

    def __getitem__(self, key: str) -> Any:
        """Support dictionary-style access to attributes"""
        return getattr(self, key)
        
    def __setitem__(self, key: str, value: Any) -> None:
        """Support dictionary-style setting of attributes"""
        setattr(self, key, value)

    def to_dict(self) -> Dict[str, Any]:
        """Convert metrics to plain dictionary for serialization"""
        return {
            "total_requests": self.total_requests,
            "successful_requests": self.successful_requests,
            "failed_requests": self.failed_requests,
            "total_duration": self.total_duration,
            "continuation_attempts": self.continuation_attempts,
            "last_error": self.last_error,
            "start_time": self.start_time,
            "project": self.project
        }

@dataclass 
class ProjectPaths:
    """Standard paths used across agent operations"""
    root: Path              # Project root directory
    workspace: Path         # Working files location  
    source: Path           # Source code directory
    output: Path           # Output directory
    config: Path           # Configuration location
    backup: Optional[Path] = None  # Optional backup directory

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