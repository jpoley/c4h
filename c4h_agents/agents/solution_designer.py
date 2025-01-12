"""
Solution designer implementation focused on synchronous operation.
Path: src/agents/solution_designer.py
"""

from typing import Dict, Any, Optional
import structlog
from datetime import datetime
import json
from .base import BaseAgent, AgentResponse, LogDetail
from config import locate_config

logger = structlog.get_logger()

class SolutionDesigner(BaseAgent):
    """Designs specific code modifications based on intent and discovery analysis."""
    
    def __init__(self, config: Dict[str, Any] = None):
        """Initialize designer with configuration."""
        super().__init__(config=config)
        
        # Let base agent initialize core config
        logger.info("solution_designer.initialized")

    def _get_agent_name(self) -> str:
        """Get agent name for config lookup"""
        return "solution_designer"

    def _format_request(self, context: Dict[str, Any]) -> str:
        """Format solution design request with proper ordering:
        1. System prompt (how to format output)
        2. Discovery context (what code exists)
        3. Intent (what changes to make)
        """
        try:
            # Get our agent-specific config including intent
            agent_config = locate_config(self.config or {}, self._get_agent_name())
            
            # Get intent from agent's config section
            intent_desc = agent_config.get('intent', {}).get('description', '')
            if not intent_desc:
                logger.warning("solution_designer.no_intent_found",
                            config_keys=list(agent_config.keys()))

            # Get discovery data from context
            input_data = context.get('input_data', {})
            discovery_data = input_data.get('discovery_data', {})
            raw_output = discovery_data.get('raw_output', '')

            # Log the components we're formatting
            if self._should_log(LogDetail.DEBUG):
                logger.debug("solution_designer.format_request",
                            has_discovery=bool(raw_output),
                            intent_length=len(intent_desc),
                            discovery_length=len(raw_output),
                            iteration=context.get('iteration', 0))
                    
                # Log first 100 chars of each component
                logger.debug("solution_designer.request_preview",
                            intent_preview=intent_desc[:100] + "..." if len(intent_desc) > 100 else intent_desc,
                            discovery_preview=raw_output[:100] + "..." if len(raw_output) > 100 else raw_output)

            # Get solution template from agent's prompts
            solution_template = self._get_prompt('solution')
            if self._should_log(LogDetail.DEBUG):
                logger.debug("solution_designer.template_loaded",
                        template_length=len(solution_template))

            # Format the complete request
            formatted_request = solution_template.format(
                source_code=raw_output,
                intent=intent_desc
            )

            # Log final request length
            if self._should_log(LogDetail.DEBUG):
                logger.debug("solution_designer.request_formatted",
                            request_length=len(formatted_request))

            return formatted_request

        except Exception as e:
            logger.error("solution_designer.format_failed", 
                        error=str(e),
                        error_type=type(e).__name__)
            raise

    def _extract_context_data(self, context: Dict[str, Any]) -> Dict[str, Any]:
        """Extract consistent data whether from nested or flat context"""
        try:
            if 'input_data' in context:
                input_data = context['input_data']
                discovery_data = input_data.get('discovery_data', {})
                raw_output = discovery_data.get('raw_output', '')
                intent = input_data.get('intent', {})
                intent_desc = intent.get('description', '') if isinstance(intent, dict) else str(intent)
            else:
                discovery_data = context.get('discovery_data', {})
                raw_output = discovery_data.get('raw_output', '')
                intent = context.get('intent', {})
                intent_desc = intent.get('description', '') if isinstance(intent, dict) else str(intent)

            return {
                'source_code': raw_output,
                'intent': intent_desc,
                'iteration': context.get('iteration', 0)
            }

        except Exception as e:
            logger.error("solution_designer.context_extraction_failed", error=str(e))
            return {}

    def _validate_input(self, context: Dict[str, Any]) -> bool:
        """Validate required input data is present"""
        discovery_data = None
        raw_output = None
            
        if 'input_data' in context:
            discovery_data = context['input_data'].get('discovery_data', {})
        elif 'discovery_data' in context:
            discovery_data = context['discovery_data']

        if hasattr(discovery_data, 'raw_output'):
            raw_output = discovery_data.raw_output
        elif isinstance(discovery_data, dict):
            raw_output = discovery_data.get('raw_output')

        logger.info("solution_designer.validate_input", 
                has_discovery=bool(raw_output),
                has_context=bool(context))

        return bool(raw_output)

    def process(self, context: Dict[str, Any]) -> AgentResponse:
        """Process solution design request"""
        try:
            # Let BaseAgent handle the LLM interaction
            response = super().process(context)
            
            # Log raw response for debugging
            if self._should_log(LogDetail.DEBUG):
                logger.debug("solution_designer.llm_response",
                            raw_response=response.data.get("raw_output"),
                            response_content=response.data.get("response"))

            # Just pass through the response
            return response

        except Exception as e:
            logger.error("solution_designer.process_failed", error=str(e))
            return AgentResponse(success=False, data={}, error=str(e))

    def _process_llm_response(self, content: str, raw_response: Any) -> Dict[str, Any]:
        """Process LLM response into standard format"""
        try:
            # Extract JSON changes from response
            if isinstance(content, str):
                data = json.loads(content)
            else:
                data = content

            return {
                "changes": data.get("changes", []),
                "raw_output": raw_response,
                "raw_content": content,
                "timestamp": datetime.utcnow().isoformat()
            }

        except json.JSONDecodeError as e:
            logger.error("solution_designer.json_parse_error", error=str(e))
            return {
                "error": f"Failed to parse LLM response: {str(e)}",
                "raw_output": raw_response,
                "raw_content": content,
                "timestamp": datetime.utcnow().isoformat()
            }