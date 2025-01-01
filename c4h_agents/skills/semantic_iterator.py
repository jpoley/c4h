"""
Semantic iterator with configurable extraction modes.
Path: c4h_agents/skills/semantic_iterator.py
"""

from typing import List, Dict, Any, Optional, Iterator, Union, Literal
from enum import Enum
import structlog
from dataclasses import dataclass, field
import json
from config import locate_config
from agents.base import BaseAgent, AgentResponse
from skills.shared.types import ExtractConfig
from skills._semantic_fast import FastExtractor, FastItemIterator
from skills._semantic_slow import SlowExtractor, SlowItemIterator

logger = structlog.get_logger()

class ExtractionMode(str, Enum):
    """Available extraction modes"""
    FAST = "fast"      # Direct extraction from structured data
    SLOW = "slow"      # Sequential item-by-item extraction

@dataclass
class ExtractorConfig:
    """Configuration requirements for extraction behavior"""
    mode: str = "fast"
    allow_fallback: bool = True
    fallback_modes: List[str] = field(default_factory=lambda: ["slow"])
    batch_size: int = 100
    timeout: int = 30

class SemanticIterator(BaseAgent):
    """Coordinates semantic extraction using configurable modes"""
    
    def __init__(self, config: Dict[str, Any] = None):
        """Initialize iterator with configuration."""
        super().__init__(config=config)
        
        # Get iterator config using locate_config
        iterator_cfg = locate_config(self.config or {}, self._get_agent_name())
        
        # Get extractor config settings
        extractor_cfg = iterator_cfg.get('extractor_config', {})
        self.extractor_config = ExtractorConfig(**extractor_cfg)
        
        # Initialize processing state
        self._content = None
        self._extract_config = None
        self._position = 0
        self._current_items = None
        self._current_mode = self.extractor_config.mode

        # Initialize extractors with same base config
        self._fast_extractor = FastExtractor(config=config)
        self._slow_extractor = SlowExtractor(config=config)

        logger.info("semantic_iterator.initialized",
                   mode=self._current_mode,
                   allow_fallback=self.extractor_config.allow_fallback)

    def _get_agent_name(self) -> str:
        """Get agent name for config lookup"""
        return "semantic_iterator"

    def process(self, context: Dict[str, Any]) -> AgentResponse:
        """Process using standard BaseAgent interface."""
        try:
            # Extract parameters from context
            if isinstance(context.get('input_data'), dict):
                input_data = context['input_data']
                content = input_data.get('content', input_data)
                instruction = input_data.get('instruction', '')
                format_hint = input_data.get('format', 'json')
            else:
                content = context.get('content', context.get('input_data', ''))
                instruction = context.get('instruction', '')
                format_hint = context.get('format', 'json')

            # Use configure() to maintain compatibility
            self.configure(
                content=content,
                config=ExtractConfig(
                    instruction=instruction,
                    format=format_hint
                )
            )

            # Get all results using iterator protocol
            results = []
            for item in self:
                results.append(item)

            return AgentResponse(
                success=bool(results),
                data={"results": results},
                error="No items extracted" if not results else None
            )

        except Exception as e:
            logger.error("semantic_iterator.process_failed", error=str(e))
            return AgentResponse(
                success=False,
                data={},
                error=str(e)
            )

    def configure(self, content: Any, config: ExtractConfig) -> 'SemanticIterator':
        """Configure iterator for use."""
        try:
            self._content = content
            self._extract_config = config
            self._position = 0
            self._current_items = None
            self._current_mode = self.extractor_config.mode
            
            logger.info("iterator.configured",
                       mode=self._current_mode,
                       content_type=type(content).__name__)
            
            return self
            
        except Exception as e:
            logger.error("iterator.configure_failed", error=str(e))
            raise

    def __iter__(self):
        """Initialize iteration based on configured mode"""
        logger.debug("iterator.starting", mode=self._current_mode)
        
        if self._current_mode == "fast":
            self._current_items = self._fast_extractor.create_iterator(
                self._content,
                self._extract_config
            )
            if not self._current_items.has_items() and self.extractor_config.allow_fallback:
                logger.info("extraction.fallback_to_slow")
                self._current_mode = "slow"
        
        if self._current_mode == "slow":
            self._current_items = self._slow_extractor.create_iterator(
                self._content,
                self._extract_config
            )
            
        self._position = 0
        return self

    def __next__(self):
        """Get next item based on current mode"""
        try:
            if not self._current_items:
                raise StopIteration
                
            return next(self._current_items)
                
        except StopIteration:
            logger.info("iterator.complete",
                       mode=self._current_mode,
                       items_processed=self._position)
            raise
        except Exception as e:
            logger.error("iterator.next_failed",
                        error=str(e),
                        mode=self._current_mode,
                        position=self._position)
            raise StopIteration