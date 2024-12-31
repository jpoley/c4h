"""
Solution designer implementation focused on synchronous operation.
Path: src/agents/solution_designer.py
"""

from typing import Dict, Any, Optional
import structlog
from datetime import datetime
import json
from .base import BaseAgent, AgentResponse
from config import locate_config

logger = structlog.get_logger()

class SolutionDesigner(BaseAgent):
    """Designs specific code modifications based on intent and discovery analysis."""
    
    def __init__(self, config: Dict[str, Any] = None):
        """Initialize designer with configuration."""
        super().__init__(config=config)
        
        # Extract config using locate_config pattern
        self.solution_config = locate_config(self.config or {}, self._get_agent_name())
        
        logger.info("solution_designer.initialized", 
                   config_keys=list(self.solution_config.keys()) if self.solution_config else None)

    def _get_agent_name(self) -> str:
        """Get agent name for config lookup"""
        return "solution_designer"

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

    def _format_request(self, context: Dict[str, Any]) -> str:
        """Format request using configured prompt template"""
        try:
            # Extract data consistently
            data = self._extract_context_data(context)
            
            logger.debug("solution_designer.format_request",
                        intent=data.get('intent'),
                        has_discovery=bool(data.get('source_code')),
                        iteration=data.get('iteration'))
            
            # First try template formatting
            try:
                template = self._get_prompt('solution')
                return template.format(**data)
            except Exception as template_error:
                logger.warning("solution_designer.template_format_failed", 
                             error=str(template_error))
                
                # Fall back to JSON format for testharness compatibility
                if isinstance(context.get('input_data'), dict):
                    return json.dumps(context['input_data'])
                return str(context)

        except Exception as e:
            logger.error("solution_designer.format_error", error=str(e))
            return str(context)

    def process(self, context: Dict[str, Any]) -> AgentResponse:
        """Process solution design request synchronously"""
        try:
            # Validate required inputs
            if not self._validate_input(context):
                return AgentResponse(
                    success=False,
                    data={},
                    error="Missing required discovery data or intent"
                )

            # Use parent's synchronous process method
            response = super().process(context)
            
            logger.info("solution_designer.process_complete",
                    success=response.success,
                    error=response.error if not response.success else None)

            return response

        except Exception as e:
            logger.error("solution_designer.process_failed", error=str(e))
            return AgentResponse(success=False, data={}, error=str(e))

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