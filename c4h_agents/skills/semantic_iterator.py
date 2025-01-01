"""
Semantic iterator with standardized BaseAgent implementation.
Path: c4h_agents/skills/semantic_iterator.py
"""

from typing import List, Dict, Any, Optional, Iterator, Union
import structlog
from dataclasses import dataclass
import json
from config import locate_config
from agents.base import BaseAgent, AgentResponse
from skills.shared.types import ExtractConfig
from skills._semantic_fast import FastExtractor
from skills._semantic_slow import SlowExtractor
from enum import Enum

logger = structlog.get_logger()

class ExtractionMode(str, Enum):
    """Available extraction modes"""
    FAST = "fast"      # Direct extraction from structured data
    SLOW = "slow"      # Sequential item-by-item extraction

@dataclass
class ExtractorState:
    """Internal state for extraction process"""
    mode: str
    position: int = 0
    content: Any = None
    config: Optional[ExtractConfig] = None
    current_items: Optional[List[Any]] = None

class SemanticIterator(BaseAgent):
    """
    Agent responsible for semantic extraction using configurable modes.
    Follows standard BaseAgent pattern while maintaining iterator protocol.
    """
    
    def __init__(self, config: Dict[str, Any] = None):
        """Initialize iterator with configuration."""
        super().__init__(config=config)
        
        # Get iterator-specific config
        iterator_config = locate_config(self.config or {}, self._get_agent_name())
        extractor_config = iterator_config.get('extractor_config', {})
        
        # Initialize extraction state
        self._state = ExtractorState(
            mode=extractor_config.get('mode', 'fast'),
            position=0
        )
        
        # Configure extractors
        self._allow_fallback = extractor_config.get('allow_fallback', True)
        self._fast_extractor = FastExtractor(config=config)
        self._slow_extractor = SlowExtractor(config=config)
        
        logger.info("semantic_iterator.initialized",
                   mode=self._state.mode,
                   allow_fallback=self._allow_fallback)

    def _get_agent_name(self) -> str:
        """Get agent name for config lookup"""
        return "semantic_iterator"

    def process(self, context: Dict[str, Any]) -> AgentResponse:
        """
        Process extraction request following standard agent interface.
        
        Args:
            context: Must contain either:
                - input_data with content and instruction
                - content and instruction directly
                
        Returns:
            AgentResponse with extracted items in data["results"]
        """
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

            # Initialize extraction config
            extract_config = ExtractConfig(
                instruction=instruction,
                format=format_hint
            )
            
            # Set up state for iteration
            self._state = ExtractorState(
                mode=self._state.mode,
                content=content,
                config=extract_config
            )
            
            # Get all results using iterator protocol
            results = []
            try:
                iterator = iter(self)
                while True:
                    results.append(next(iterator))
            except StopIteration:
                pass
            
            if not results:
                return AgentResponse(
                    success=False,
                    data={},
                    error="No items could be extracted"
                )
                
            return AgentResponse(
                success=True,
                data={"results": results}
            )

        except Exception as e:
            logger.error("semantic_iterator.process_failed", error=str(e))
            return AgentResponse(
                success=False,
                data={},
                error=str(e)
            )

    def configure(self, content: Any, config: ExtractConfig) -> 'SemanticIterator':
        """
        Legacy configuration method for backward compatibility.
        
        Args:
            content: Content to extract from
            config: Extraction configuration
            
        Returns:
            Self for chaining
        """
        logger.warning("semantic_iterator.using_deprecated_configure")
        self._state = ExtractorState(
            mode=self._state.mode,
            content=content,
            config=config
        )
        return self

    def __iter__(self) -> Iterator[Any]:
        """Initialize iteration in configured mode"""
        logger.debug("iterator.starting", mode=self._state.mode)
        
        if not self._state.content or not self._state.config:
            raise ValueError("Iterator not configured. Call process() first.")
        
        if self._state.mode == ExtractionMode.FAST:
            # Try fast extraction first
            response = self._fast_extractor.process({
                'content': self._state.content,
                'config': self._state.config
            })
            
            logger.debug("fast_extractor.response", 
                        success=response.success,
                        data_keys=list(response.data.keys()) if response.data else None,
                        response_type=type(response.data.get('response')).__name__ if response.data else None)
            
            if response.success:
                # Handle direct response or nested data
                if 'response' in response.data and isinstance(response.data['response'], (list, str)):
                    if isinstance(response.data['response'], str):
                        try:
                            self._state.current_items = json.loads(response.data['response'])
                        except json.JSONDecodeError:
                            self._state.current_items = None
                    else:
                        self._state.current_items = response.data['response']
                else:
                    self._state.current_items = response.data
                
                logger.debug("iterator.items_loaded", 
                           items_type=type(self._state.current_items).__name__,
                           item_count=len(self._state.current_items) if self._state.current_items else 0)
            
            if not self._state.current_items and self._allow_fallback:
                logger.info("extraction.fallback_to_slow")
                self._state.mode = ExtractionMode.SLOW
                
        self._state.position = 0
        return self

    def __next__(self) -> Any:
        """Get next item using current extraction mode"""
        try:
            if self._state.mode == ExtractionMode.FAST:
                return self._next_fast()
            else:
                return self._next_slow()
        except Exception as e:
            logger.error("iterator.next_failed",
                        error=str(e),
                        mode=self._state.mode,
                        position=self._state.position)
            raise StopIteration

    def _next_fast(self) -> Any:
        """Handle fast mode iteration"""
        if not self._state.current_items:
            logger.debug("fast_iteration.no_items")
            raise StopIteration

        if isinstance(self._state.current_items, list):
            items = self._state.current_items
        else:
            logger.error("fast_iteration.invalid_items_type", 
                        type=type(self._state.current_items).__name__)
            raise StopIteration
            
        if self._state.position >= len(items):
            logger.debug("fast_iteration.complete", total_items=len(items))
            raise StopIteration
            
        item = items[self._state.position]
        self._state.position += 1
        
        logger.debug("fast_iteration.next_item", 
                    position=self._state.position,
                    item_type=type(item).__name__)
        return item

    def _next_slow(self) -> Any:
        """Handle slow mode iteration"""
        response = self._slow_extractor.process({
            'content': self._state.content,
            'config': self._state.config,
            'position': self._state.position
        })
        
        if not response.success:
            raise StopIteration
            
        content = response.data.get('response', '')
        if 'NO_MORE_ITEMS' in str(content):
            raise StopIteration
            
        self._state.position += 1
        return content