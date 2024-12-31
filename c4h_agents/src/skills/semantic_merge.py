"""
Semantic merge implementation for code modifications.
Path: src/skills/semantic_merge.py
"""

from typing import Dict, Any
import structlog
from agents.base import BaseAgent, AgentResponse
from config import locate_config

logger = structlog.get_logger()

class SemanticMerge(BaseAgent):
    """Handles merging of code modifications."""
    
    def __init__(self, config: Dict[str, Any] = None):
        """Initialize merger with configuration."""
        super().__init__(config=config)
        logger.info("semantic_merge.initialized")

    def _get_agent_name(self) -> str:
        """Get agent name for config lookup"""
        return "semantic_merge"

    def process(self, context: Dict[str, Any]) -> AgentResponse:
        """Process merge by passing entire context to LLM"""
        logger.info("merge.starting")

        try:
            # Let LLM handle everything through the system prompt
            result = super().process(context)
            
            if not result.success:
                logger.warning("merge.failed", error=result.error)
                return result

            return AgentResponse(
                success=True,
                data={
                    "response": result.data.get("response", ""),
                    "raw_output": result.data.get("raw_output")
                }
            )

        except Exception as e:
            logger.error("merge.failed", error=str(e))
            return AgentResponse(success=False, data={}, error=str(e))