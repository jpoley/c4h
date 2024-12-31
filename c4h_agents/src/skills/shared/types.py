"""
Shared type definitions for semantic processing.
Path: src/skills/shared/types.py
"""

from typing import Dict, Any, Optional, List, Callable
from dataclasses import dataclass, field

@dataclass
class InterpretResult:
    """Result from semantic interpretation"""
    data: Any
    raw_response: str
    context: Dict[str, Any]

@dataclass
class ExtractConfig:
    """Configuration for semantic extraction"""
    instruction: str  # Pattern/prompt for extraction
    format: str = "json"  # Expected output format
    filters: Optional[List[Callable[[Any], bool]]] = field(default_factory=list)
    sort_key: Optional[str] = None
    validation: Optional[Dict[str, Any]] = field(default_factory=dict)

@dataclass
class ExtractionState:
    """Tracks extraction state across attempts"""
    items: List[Any]
    position: int = 0
    raw_response: str = ""
    error: Optional[str] = None
    content: Any = None
    config: Optional[ExtractConfig] = None
