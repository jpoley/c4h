"""
Slow extraction mode with lazy LLM calls.
Path: c4h_agents/skills/_semantic_slow.py
"""

from typing import Dict, Any, Optional 
import structlog
from agents.base import BaseAgent, AgentResponse
from skills.shared.types import ExtractConfig
import json
from config import locate_config

logger = structlog.get_logger()

class ExtractionError(Exception):
    """Custom exception for extraction errors"""
    pass

class ExtractionComplete(StopIteration):
    """Custom exception to signal clean completion of extraction"""
    pass

class SlowItemIterator:
    """Iterator for slow extraction results with lazy LLM calls"""
    
    def __init__(self, extractor: 'SlowExtractor', content: Any, config: ExtractConfig):
        """Initialize iterator with extraction parameters"""
        self._extractor = extractor
        self._content = content
        self._config = config
        self._position = 0
        self._exhausted = False
        self._max_attempts = 7  # Safety limit
        self._returned_items = set()  # Track returned items

    def __iter__(self):
        return self

    def __next__(self) -> Any:
        """Get next item using lazy extraction"""
        print("!!! SLOW ITERATOR __NEXT__ CALLED !!!")  
        logger.critical("SLOW_ITERATOR_NEXT_CALLED", 
                    position=self._position,
                    max_attempts=self._max_attempts,
                    exhausted=self._exhausted)

        if self._exhausted or self._position >= self._max_attempts:
            print("!!! SLOW ITERATOR EXHAUSTED - STOPPING !!!")
            raise StopIteration

        try:
            # Run extraction using the extractor instance
            agent_response = self._extractor.process({
                'content': self._content,
                'config': self._config,
                'position': self._position
            })

            if not agent_response.success:
                logger.error("slow_iterator.extraction_failed", 
                            error=agent_response.error,
                            position=self._position)
                self._exhausted = True
                raise StopIteration

            # Extract just the actual response content 
            content = agent_response.data.get('response')  

            # Log the complete response chain
            logger.debug("slow_iterator.response",
                        position=self._position,
                        content_type=type(content).__name__,
                        content=content)

            # Handle completion signals
            if not content:
                logger.debug("slow_iterator.empty_response")
                self._exhausted = True
                raise StopIteration

            if isinstance(content, str):
                content = content.strip()
                if content.upper() == "NO_MORE_ITEMS":
                    logger.debug("slow_iterator.no_more_items", 
                            position=self._position)
                    self._exhausted = True
                    raise StopIteration

                # Try to parse JSON if it's a string
                try:
                    content = json.loads(content)
                except json.JSONDecodeError:
                    pass  # Keep as string if not valid JSON

            # Track item and increment position
            if str(content) in self._returned_items:
                logger.debug("slow_iterator.duplicate_item",
                        position=self._position,
                        content=content)
                self._exhausted = True
                raise StopIteration

            self._returned_items.add(str(content))
            self._position += 1

            logger.info("slow_iterator.item_extracted",
                    position=self._position - 1,
                    item_type=type(content).__name__)

            return content

        except Exception as e:
            logger.error("slow_iterator.error", 
                        error=str(e),
                        position=self._position)
            self._exhausted = True
            raise StopIteration

class SlowExtractor(BaseAgent):
    """Implements slow extraction mode using iterative LLM queries"""

    def __init__(self, config: Dict[str, Any] = None):
        """Initialize with parent agent configuration"""
        super().__init__(config=config)
        
        # Get our config section
        slow_cfg = locate_config(self.config or {}, self._get_agent_name())
        
        # Validate template at initialization
        template = self._get_prompt('extract')
        if '{ordinal}' not in template:
            logger.error("slow_extractor.invalid_template", 
                        reason="Missing {ordinal} placeholder")
            raise ValueError("Slow extractor requires {ordinal} in prompt template")

        logger.info("slow_extractor.initialized",
                   settings=slow_cfg)

    def _get_agent_name(self) -> str:
        return "semantic_slow_extractor"

    def _format_request(self, context: Dict[str, Any]) -> str:
        """Format extraction request for slow mode using config template"""
        if not context.get('config'):
            logger.error("slow_extractor.missing_config")
            raise ValueError("Extract config required")

        position = context.get('position', 0)
        ordinal = self._get_ordinal(position + 1)
        
        # Format instruction with ordinal
        instruction = context['config'].instruction.format(ordinal=ordinal)

        # Format complete request using template
        request = self._get_prompt('extract').format(
            ordinal=ordinal,
            content=context.get('content', ''),
            instruction=instruction,
            format=context['config'].format
        )

        logger.debug("slow_extractor.request",
                   position=position,
                   ordinal=ordinal,
                   request_length=len(request))

        return request

    @staticmethod
    def _get_ordinal(n: int) -> str:
        """Generate ordinal string for a number"""
        suffix = {1: 'st', 2: 'nd', 3: 'rd'}.get(n % 10 if n % 100 not in [11, 12, 13] else 0, 'th')
        return f"{n}{suffix}"

    def create_iterator(self, content: Any, config: ExtractConfig) -> SlowItemIterator:
        """Create iterator for slow extraction"""
        logger.debug("slow_extractor.creating_iterator",
                    content_type=type(content).__name__)
        return SlowItemIterator(self, content, config)