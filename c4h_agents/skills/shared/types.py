"""
Shared type definitions for semantic processing.
Path: c4h_agents/skills/shared/types.py
"""

from typing import Dict, Any, Optional, List, Callable
from pydantic import BaseModel, Field
from datetime import datetime

class ExtractConfig(BaseModel):
    """Configuration for semantic extraction"""
    instruction: str = Field(description="Pattern/prompt for extraction")
    format: str = Field(default="json", description="Expected output format")
    filters: List[Callable[[Any], bool]] = Field(default_factory=list, description="Optional result filters")
    sort_key: Optional[str] = Field(default=None, description="Optional sort key for results")
    validation: Dict[str, Any] = Field(default_factory=dict, description="Optional validation rules")

    class Config:
        arbitrary_types_allowed = True

class InterpretResult(BaseModel):
    """Result from semantic interpretation"""
    data: Any
    raw_response: str
    context: Dict[str, Any]

class ExtractionState(BaseModel):
    """Tracks extraction state across attempts"""
    items: List[Any] = Field(default_factory=list)
    position: int = Field(default=0)
    raw_response: str = Field(default="")
    error: Optional[str] = None
    content: Any = None
    config: Optional[ExtractConfig] = None

    class Config:
        arbitrary_types_allowed = True