"""
Primary base agent implementation with core types and functionality.
Path: c4h_agents/agents/base_agent.py
"""

from dataclasses import dataclass, field
from datetime import datetime
from typing import Dict, Any, Optional, List, Tuple, Literal, Union
from enum import Enum
import structlog
import json
from pathlib import Path

from c4h_agents.core.project import Project
from c4h_agents.config import locate_keys
from .base_config import BaseConfig, log_operation
from .base_llm import BaseLLM

logger = structlog.get_logger()

class LogDetail(str, Enum):
    """Log detail levels for agent operations"""
    MINIMAL = "minimal"
    BASIC = "basic"
    DETAILED = "detailed" 
    DEBUG = "debug"
    
    @classmethod
    def from_str(cls, level: str) -> 'LogDetail':
        try:
            return cls(level.lower())
        except ValueError:
            return cls.BASIC

class LLMProvider(str, Enum):
    """Supported model providers"""
    ANTHROPIC = "anthropic"
    OPENAI = "openai"
    GEMINI = "gemini"

    def __str__(self) -> str:
        """Safe string conversion ensuring no interpolation issues"""
        return str(self.value)

    def serialize(self) -> str:
        """Safe serialization for logging and persistence"""
        return f"provider_{self.value}"

@dataclass
class AgentConfig:
    """Configuration requirements for base agent"""
    provider: Literal['anthropic', 'openai', 'gemini']
    model: str
    temperature: float = 0
    api_base: Optional[str] = None
    context_length: Optional[int] = None

@dataclass
class AgentResponse:
    """Standard response format for all agents"""
    success: bool
    data: Dict[str, Any]
    error: Optional[str] = None
    timestamp: datetime = field(default_factory=datetime.utcnow)

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
        
        # Initialize metrics with project context
        self.metrics = {
            "total_requests": 0,
            "successful_requests": 0,
            "failed_requests": 0,
            "total_duration": 0.0,
            "continuation_attempts": 0,
            "last_error": None,
            "start_time": datetime.utcnow().isoformat(),
            "project": self.project.metadata.name if self.project else None
        }

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

    @log_operation("process")
    def _process(self, context: Dict[str, Any]) -> AgentResponse:
        """Internal synchronous implementation"""
        try:
            if self._should_log(LogDetail.DETAILED):
                logger.info("agent.processing",
                        context_keys=list(context.keys()) if context else None)

            # Get required data using discovery pattern 
            data = self._get_data(context)
            
            # Format request before sending
            system_message = self._get_system_message()
            user_message = self._format_request(data)
            
            messages = [
                {"role": "system", "content": system_message},
                {"role": "user", "content": user_message}
            ]

            # Use continuation handler for completion
            try:
                content, raw_response = self._get_completion_with_continuation(messages)
                
                # Process response with integrity checks
                processed_data = self._process_response(content, raw_response)
                
                return AgentResponse(
                    success=True,
                    data=processed_data,
                    error=None
                )
                
            except Exception as e:
                logger.error("llm.completion_failed", error=str(e))
                return AgentResponse(
                    success=False,
                    data={},
                    error=f"LLM completion failed: {str(e)}"
                )
                
        except Exception as e:
            logger.error("process.failed", error=str(e))
            return AgentResponse(success=False, data={}, error=str(e))
        
    def _format_request(self, context: Dict[str, Any]) -> str:
        """Format request message"""
        return str(context)
    
    def _get_llm_content(self, response: Any) -> Any:
        """
        Single point of LLM response interpretation.
        Ensures consistent interface for all agents/skills.
        """
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

    def _get_required_keys(self) -> List[str]:
        """
        Define keys required by this agent.
        Override in subclasses to specify required input keys.
        """
        return []

    def _locate_data(self, data: Dict[str, Any], keys: List[str]) -> Dict[str, Tuple[Any, List[str]]]:
        """
        Locate multiple required keys in input data.
        Uses same pattern as config location.
        """
        return locate_keys(data, keys)

    def _get_data(self, context: Dict[str, Any]) -> Dict[str, Any]:
        """
        Extract required data using key discovery with JSON parsing.
        Each agent specifies its required keys.
        """
        required = self._get_required_keys()
        if not required:
            return context
            
        try:
            results = {}
            located = locate_keys(context, required)
            
            for key, (value, path) in located.items():
                # Handle string JSON values
                if isinstance(value, str):
                    try:
                        parsed = json.loads(value)
                        results[key] = parsed
                        continue
                    except json.JSONDecodeError:
                        pass
                        
                # Use value as-is if not JSON string
                results[key] = value
                
                if self._should_log(LogDetail.DEBUG):
                    logger.debug("agent.data_extracted",
                               key=key,
                               path=path,
                               value_type=type(results[key]).__name__)
                               
            return results
            
        except Exception as e:
            logger.error("agent.data_extraction_failed",
                        error=str(e),
                        required_keys=required)
            return {}

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

    def _get_agent_name(self) -> str:
        """Get agent name for config lookup. Must be implemented by subclasses."""
        raise NotImplementedError("Agent classes must implement _get_agent_name")

# Re-export types for backward compatibility
__all__ = ['BaseAgent', 'AgentResponse', 'LogDetail', 'LLMProvider', 'AgentConfig']