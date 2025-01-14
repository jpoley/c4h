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

class SlowItemIterator:
    """Iterator for slow extraction results with lazy LLM calls"""
    
    def __init__(self, extractor: 'SlowExtractor', content: Any, config: ExtractConfig):
        """Initialize iterator with extraction parameters"""
        self._extractor = extractor
        self._content = content
        self._config = config
        self._position = 0
        self._exhausted = False
        self._max_attempts = 100  # Safety limit
        self._returned_items = set()  # Track returned items

    def __iter__(self):
        return self

    def __next__(self):
        """Get next item using lazy extraction"""
        if self._exhausted or self._position >= self._max_attempts:
            raise StopIteration

        try:
            # Run extraction synchronously
            result = self._extractor.process({
                'content': self._content,
                'config': self._config,
                'position': self._position
            })

            # Handle extraction result
            if result.success:
                # Get content from standard response location 
                content = result.data.get('response', '')
                
                # Handle NO_MORE_ITEMS as clean completion
                if isinstance(content, str) and 'NO_MORE_ITEMS' in content:
                    logger.debug("slow_extraction.complete", position=self._position)
                    self._exhausted = True
                    raise StopIteration

                # Parse response if needed
                try:
                    if isinstance(content, str):
                        # Handle potential markdown code blocks
                        if content.startswith('```') and content.endswith('```'):
                            content = content.split('```')[1]
                            if content.startswith('json'):
                                content = content[4:]
                        content = json.loads(content)
                except json.JSONDecodeError:
                    pass  # Keep original string if not JSON
                        
                self._position += 1
                return content

            else:
                logger.warning("slow_extraction.failed", 
                            error=result.error,
                            position=self._position)
                self._exhausted = True
                raise StopIteration

        except Exception as e:
            if not isinstance(e, StopIteration):
                logger.error("slow_iteration.failed", 
                            error=str(e), 
                            position=self._position)
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

        extract_template = self._get_prompt('extract')
        position = context.get('position', 0)
        ordinal = self._get_ordinal(position + 1)
        
        # First substitute ordinal in the instruction
        instruction = context['config'].instruction.format(ordinal=ordinal)
        
        # Then use the processed instruction in the main template
        return extract_template.format(
            ordinal=ordinal,
            content=context.get('content', ''),
            instruction=instruction,
            format=context['config'].format
        )

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