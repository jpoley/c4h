"""
Agent task configuration models.
Path: c4h_services/src/intent/impl/prefect/models.py
"""

from typing import Dict, Any, Optional, Type
from pydantic import BaseModel, Field

class AgentTaskConfig(BaseModel):
    """Configuration for agent task execution"""
    agent_class: Any  # Can be a class or a string class path for dynamic loading
    config: Dict[str, Any] = Field(default_factory=dict)
    task_name: Optional[str] = None
    requires_approval: bool = Field(default=False)
    max_retries: int = Field(default=3)
    retry_delay_seconds: int = Field(default=30)

    class Config:
        arbitrary_types_allowed = True  # Allow any class type