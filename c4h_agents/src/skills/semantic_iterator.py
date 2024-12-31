"""
Semantic iterator with configurable extraction modes.
Path: src/skills/semantic_iterator.py
"""

from typing import List, Dict, Any, Optional, Iterator, Union, Literal
from enum import Enum
import structlog
from dataclasses import dataclass, field
import json
from config import locate_config
from agents.base import BaseAgent, LLMProvider, AgentResponse
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
        return "semantic_iterator"

    def configure(self, content: Any, config: ExtractConfig) -> 'SemanticIterator':
        """Configure iterator for use"""
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
            logger.error("iterator.configure_failed",
                        error=str(e),
                        error_type=type(e).__name__)
            raise

    def _get_extractor(self, mode: str):
        """Get mode-specific extractor"""
        return self._fast_extractor if mode == "fast" else self._slow_extractor

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
        
        self._position = 0
        return self

    def __next__(self):
        """Get next item based on current mode"""
        try:
            if self._current_mode == "fast":
                return self._next_fast()
            else:
                return self._next_slow()
                
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

    def _next_fast(self):
        """Handle fast mode iteration"""
        if not self._current_items:
            response = self._fast_extractor.process({
                'content': self._content,
                'config': self._extract_config
            })
            if response.success:
                content = response.data.get('response', '[]')
                if isinstance(content, str):
                    self._current_items = json.loads(content)
                else:
                    self._current_items = content
                logger.debug("fast_extraction.success",
                           items_found=len(self._current_items))
            else:
                self._current_items = []
                if self.extractor_config.allow_fallback:
                    logger.info("fast_extraction.fallback",
                              error=response.error)
                    self._current_mode = "slow"
                    return self.__next__()

        if self._position < len(self._current_items):
            item = self._current_items[self._position]
            self._position += 1
            return item
        raise StopIteration

    """
    Semantic iterator with configurable extraction modes.
    Path: src/skills/semantic_iterator.py
    """

    def _next_slow(self):
        """Handle slow mode iteration"""
        logger.debug("slow_iteration.starting", 
                    current_position=self._position,
                    has_content=bool(self._content))
                    
        response = self._slow_extractor.process({
            'content': self._content,
            'config': self._extract_config,
            'position': self._position
        })
        
        logger.debug("slow_iteration.response_received",
                    position=self._position,
                    success=response.success,
                    has_response=bool(response.data.get('response')))

        if 'NO_MORE_ITEMS' in str(response.data.get('response', '')):
            logger.info("slow_iteration.completed", 
                    final_position=self._position)
            raise StopIteration
                
        if response.success:
            self._position += 1
            logger.debug("slow_iteration.position_advanced",
                        new_position=self._position,
                        previous_position=self._position-1)
            return response.data.get('response')
                
        raise StopIteration