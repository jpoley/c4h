"""
Primary base agent implementation with core functionality.
Path: c4h_agents/agents/base_agent.py
"""

from typing import Dict, Any, Optional, List, Tuple
import structlog
import json
from pathlib import Path
from datetime import datetime

from c4h_agents.core.project import Project
from c4h_agents.config import locate_keys
from .base_lineage import BaseLineage
from .types import (
    LogDetail,
    LLMProvider,
    LLMMessages,
    AgentResponse,
    AgentMetrics
)
from .base_config import BaseConfig, log_operation
from .base_llm import BaseLLM

logger = structlog.get_logger()

class BaseAgent(BaseConfig, BaseLLM):
    """Base agent implementation"""
    
    def __init__(self, config: Dict[str, Any] = None, project: Optional[Project] = None):
        """Initialize agent with configuration and optional project"""
        # Initialize config first
        super().__init__(config=config, project=project)
        
        # Extract and validate config for this agent
        agent_config = self._get_agent_config()
        
        # Set provider and model
        self.provider = LLMProvider(agent_config.get('provider', 'anthropic'))
        self.model = agent_config.get('model', 'claude-3-opus-20240229')
        self.temperature = agent_config.get('temperature', 0)
        
        # Get continuation settings
        self.max_continuation_attempts = agent_config.get('max_continuation_attempts', 5)
        self.continuation_token_buffer = agent_config.get('continuation_token_buffer', 1000)
        
        # Initialize metrics using AgentMetrics dataclass
        self.metrics = AgentMetrics(
            project=self.project.metadata.name if self.project else None
        )

        # Set logging detail level from config
        log_level = self.config.get('logging', {}).get('agent_level', 'basic')
        self.log_level = LogDetail.from_str(log_level)
        
        # Build model string and setup LiteLLM
        self.model_str = self._get_model_str()
        self._setup_litellm(self._get_provider_config(self.provider))
        
        # Initialize logger with enhanced context
        log_context = {
            "agent": self._get_agent_name(),
            "provider": self.provider.serialize(),
            "model": self.model,
            "log_level": str(self.log_level)
        }
        
        # Add project context if available
        if self.project:
            log_context.update({
                "project_name": self.project.metadata.name,
                "project_version": self.project.metadata.version,
                "project_root": str(self.project.paths.root)
            })
            
        self.logger = structlog.get_logger().bind(**log_context)
        
        logger.info(f"{self._get_agent_name()}.initialized", 
                   continuation_settings={
                       "max_attempts": self.max_continuation_attempts,
                       "token_buffer": self.continuation_token_buffer
                   },
                   **log_context)

    def process(self, context: Dict[str, Any]) -> AgentResponse:
        """Main process entry point"""
        return self._process(context)

    def _process(self, context: Dict[str, Any]) -> AgentResponse:
        """Internal synchronous implementation"""
        try:
            if self._should_log(LogDetail.DETAILED):
                logger.info("agent.processing",
                        context_keys=list(context.keys()) if context else None)

            # Get required data using discovery pattern 
            data = self._get_data(context)
            
            # Get system message first
            system_message = self._get_system_message()
            
            # Format user request once
            user_message = self._format_request(data)
            
            # Log messages at debug with full system
            if self._should_log(LogDetail.DEBUG):
                logger.debug("agent.messages",
                            system_length=len(system_message),
                            user_length=len(user_message),
                            system=system_message,
                            user_message=user_message)
            
            # Enhance context with prompts for event storage
            enhanced_context = {
                **context,
                "prompts": {
                    "system": system_message,
                    "user": user_message
                }
            }
            
            # Create message set with enhanced context
            messages = LLMMessages(
                system=system_message,
                user=user_message,
                formatted_request=user_message,
                raw_context=enhanced_context  # Use enhanced context here
            )

            try:
                # Get LLM completion
                content, raw_response = self._get_completion_with_continuation([
                    {"role": "system", "content": messages.system},
                    {"role": "user", "content": messages.user}
                ])
                
                # Process response with integrity checks
                processed_data = self._process_response(content, raw_response)
                
                # Track lineage if enabled - with safety check
                if hasattr(self, 'lineage') and self.lineage:
                     try:
                        logger.debug("lineage.attempt_tracking",
                                   agent=self._get_agent_name(),
                                   has_context=bool(enhanced_context),
                                   has_messages=bool(messages),
                                   has_metrics=hasattr(raw_response, 'usage'))
                                   
                        self.lineage.track_llm_interaction(
                            context=enhanced_context,
                            messages=messages,
                            response=raw_response,
                            metrics={"token_usage": getattr(raw_response, 'usage', {})}
                        )
                        
                        logger.info("lineage.tracking_complete",
                                  agent=self._get_agent_name())
                                  
                     except Exception as e:
                        logger.error("lineage.tracking_failed", 
                                    error=str(e),
                                    error_type=type(e).__name__,
                                    agent=self._get_agent_name())
                else:
                    logger.debug("lineage.tracking_skipped",
                               has_lineage=hasattr(self, 'lineage'),
                               lineage_enabled=bool(getattr(self, 'lineage', None)),
                               agent=self._get_agent_name())

                return AgentResponse(
                    success=True,
                    data=processed_data,
                    error=None,
                    messages=messages,
                    raw_output=raw_response,
                    metrics={"token_usage": getattr(raw_response, 'usage', {})}
                )
                
            except Exception as e:
                logger.error("llm.completion_failed", error=str(e))
                return AgentResponse(
                    success=False,
                    data={},
                    error=f"LLM completion failed: {str(e)}",
                    messages=messages
                )
                
        except Exception as e:
            logger.error("process.failed", error=str(e))
            return AgentResponse(
                success=False, 
                data={}, 
                error=str(e)
            )


    def _get_data(self, context: Dict[str, Any]) -> Dict[str, Any]:
        """Extract data from context with basic formatting"""
        try:
            if isinstance(context, dict):
                return context
            return {'content': str(context)}
        except Exception as e:
            logger.error("get_data.failed", error=str(e))
            return {}

    def _format_request(self, context: Dict[str, Any]) -> str:
        """Format request message - can be overridden by derived classes"""
        return str(context)
    
    def _get_llm_content(self, response: Any) -> Any:
        """Extract content from LLM response with consistent interface"""
        try:
            if hasattr(response, 'choices') and response.choices:
                content = response.choices[0].message.content
                if self._should_log(LogDetail.DEBUG):
                    logger.debug("content.extracted_from_model",
                            content_length=len(content) if content else 0)
                return content

            return str(response)
                
        except Exception as e:
            logger.error("content_extraction.failed", error=str(e))
            return str(response)

    def _process_response(self, content: str, raw_response: Any) -> Dict[str, Any]:
        """Process LLM response into standardized format"""
        try:
            # Extract content using standard helper
            processed_content = self._get_llm_content(content)
            
            # Debug logging for response processing
            if self._should_log(LogDetail.DEBUG):
                logger.debug("agent.processing_response",
                            content_length=len(str(processed_content)) if processed_content else 0,
                            response_type=type(raw_response).__name__)

            # Build standard response structure
            response = {
                "response": processed_content,
                "raw_output": str(raw_response),
                "timestamp": datetime.utcnow().isoformat()
            }

            # Log and include token usage if available
            if hasattr(raw_response, 'usage'):
                usage = raw_response.usage
                usage_data = {
                    "completion_tokens": getattr(usage, 'completion_tokens', 0),
                    "prompt_tokens": getattr(usage, 'prompt_tokens', 0),
                    "total_tokens": getattr(usage, 'total_tokens', 0)
                }
                logger.info("llm.token_usage", **usage_data)
                response["usage"] = usage_data

            return response

        except Exception as e:
            logger.error("response_processing.failed", error=str(e))
            return {
                "response": str(content),
                "raw_output": str(raw_response),
                "timestamp": datetime.utcnow().isoformat(),
                "error": str(e)
            }

    def _get_required_keys(self) -> List[str]:
        """Define keys required by this agent"""
        return []

    def _get_agent_name(self) -> str:
        """Get agent name for config lookup - default to class name in lowercase"""
        return self.__class__.__name__.lower()

    def _get_system_message(self) -> str:
        """Get system message from config"""
        return self.config.get("llm_config", {}).get("agents", {}).get(
            self._get_agent_name(), {}).get("prompts", {}).get("system", "")

    def _get_prompt(self, prompt_type: str) -> str:
        """Get prompt template by type"""
        prompts = self.config.get("llm_config", {}).get("agents", {}).get(
            self._get_agent_name(), {}).get("prompts", {})
        if prompt_type not in prompts:
            raise ValueError(f"No prompt template found for type: {prompt_type}")
        return prompts[prompt_type]