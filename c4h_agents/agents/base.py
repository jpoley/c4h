"""
Base agent implementation with integrated LiteLLM configuration, Project support,
and automatic continuation handling for token limited responses.
Path: c4h_agents/agents/base.py
"""

from abc import ABC, abstractmethod
import structlog
from dataclasses import dataclass
from datetime import datetime
from enum import Enum
import asyncio
from typing import Dict, Any, Optional, List, Literal, Tuple, Union
from functools import wraps
import time
import litellm
from litellm import completion
import json
from pathlib import Path

# Change relative import to absolute
from c4h_agents.core.project import Project, ProjectPaths
from c4h_agents.config import locate_config, locate_keys

logger = structlog.get_logger()

class LogDetail(str, Enum):
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
class AgentResponse:
    """Standard response format"""
    success: bool
    data: Dict[str, Any]
    error: Optional[str] = None
    timestamp: datetime = datetime.utcnow()

def log_operation(operation_name: str):
    """Operation logging decorator"""
    def decorator(func):
        @wraps(func)
        def wrapper(self, *args, **kwargs):
            start_time = time.time()
            try:
                result = func(self, *args, **kwargs)
                self._update_metrics(time.time() - start_time, True)
                return result
            except Exception as e:
                self._update_metrics(time.time() - start_time, False, str(e))
                raise
        return wrapper
    return decorator

@dataclass
class AgentConfig:
    """Configuration requirements for base agent"""
    provider: Literal['anthropic', 'openai', 'gemini']
    model: str
    temperature: float = 0
    api_base: Optional[str] = None
    context_length: Optional[int] = None

class BaseAgent:
    def __init__(self, config: Dict[str, Any] = None, project: Optional[Project] = None):
        """Initialize agent with configuration and optional project"""
        self.config = config or {}
        self.project = project
        
        # Create important paths if using project
        if self.project:
            self.ensure_paths()
        
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

    def _get_completion_with_continuation(
        self, 
        messages: List[Dict[str, str]],
        max_attempts: Optional[int] = None
    ) -> Tuple[str, Any]:
        """
        Get completion with automatic continuation handling - synchronous version.
        """
        try:
            combined_content = []
            attempt = 0
            max_tries = max_attempts or self.max_continuation_attempts
            
            original_message_count = len(messages)
            last_continuation_length = 0
            
            while attempt < max_tries:
                # Log the attempt details
                if attempt > 0:
                    logger.info("llm.continuation_attempt",
                            attempt=attempt,
                            messages_count=len(messages),
                            combined_length=len(''.join(combined_content)),
                            last_chunk_length=last_continuation_length)
                
                # Synchronous completion
                response = completion(
                    model=self.model_str,
                    messages=messages,
                    temperature=self.temperature,
                    api_base=self._get_provider_config(self.provider).get("api_base")
                )

                # Rest of the logic remains the same
                if not response or not response.choices:
                    logger.error("llm.no_response",
                            attempt=attempt,
                            provider=self.provider.serialize())
                    break
                    
                choice = response.choices[0]
                content = choice.message.content
                
                # Update metrics
                self.metrics["continuation_attempts"] = attempt + 1
                
                # Check completion status
                finish_reason = getattr(choice, 'finish_reason', None)
                
                if finish_reason == 'length':
                    logger.info("llm.length_limit_reached", 
                              attempt=attempt,
                              content_length=last_continuation_length,
                              total_length=len(''.join(combined_content)))
                    
                    # Add continuation prompt
                    messages.append({"role": "assistant", "content": content})
                    messages.append({
                        "role": "user", 
                        "content": "Continue exactly from where you left off, maintaining exact format and indentation. Do not repeat any content."
                    })
                    attempt += 1
                else:
                    logger.info("llm.completion_finished",
                              finish_reason=finish_reason,
                              final_length=len(''.join(combined_content)),
                              continuation_count=attempt)
                    break
                    
            final_content = ''.join(combined_content)
            
            if attempt >= max_tries:
                logger.warning("llm.continuation_limit_reached",
                             max_attempts=max_tries,
                             final_length=len(final_content))
            
            # Log completion summary
            logger.debug("llm.completion_summary",
                        total_attempts=attempt + 1,
                        original_messages=original_message_count,
                        final_messages=len(messages),
                        final_length=len(final_content))
                
            return final_content, response
            
        except Exception as e:
            logger.error("llm.continuation_failed", error=str(e))
            raise

    def _get_llm_content(self, response: Any) -> Any:
        """
        Extract content from LLM response regardless of provider/library.
        Handles raw strings, ModelResponse objects, and dictionaries.
        
        Args:
            response: Raw response from LLM
            
        Returns:
            Extracted content in the most appropriate format
        """
        try:
            # Handle ModelResponse objects
            if hasattr(response, 'choices') and response.choices:
                content = response.choices[0].message.content
            # Handle dictionary responses
            elif isinstance(response, dict):
                content = response.get('content', response.get('text', response))
            else:
                content = str(response)
                
            # Try to parse JSON if it's a string
            if isinstance(content, str):
                try:
                    return json.loads(content)
                except json.JSONDecodeError:
                    return content
                    
            return content
            
        except Exception as e:
            logger.error("llm.content_extraction_failed", error=str(e))
            return str(response)

    def _process_response(self, content: str, raw_response: Any) -> Dict[str, Any]:
        """Process LLM response with integrity checks"""
        try:
            # Extract content from raw response if needed
            processed_content = self._get_llm_content(content)
            
            if self._should_log(LogDetail.DEBUG):
                logger.debug("agent.processing_response",
                            content_length=len(str(processed_content)) if processed_content else 0,
                            response_type=type(raw_response).__name__,
                            continuation_attempts=self.metrics["continuation_attempts"])
                
            # Log usage statistics if available
            if hasattr(raw_response, 'usage'):
                usage = raw_response.usage
                logger.info("llm.token_usage",
                        completion_tokens=getattr(usage, 'completion_tokens', 0),
                        prompt_tokens=getattr(usage, 'prompt_tokens', 0),
                        total_tokens=getattr(usage, 'total_tokens', 0))
                
            # Basic content integrity validation
            if processed_content and isinstance(processed_content, str):
                # Check for unmatched delimiters
                delimiters = [
                    ('{', '}'),
                    ('[', ']'),
                    ('(', ')'),
                ]
                
                for start, end in delimiters:
                    if processed_content.count(start) != processed_content.count(end):
                        logger.warning("agent.content_integrity_check_failed",
                                    start_char=start,
                                    end_char=end,
                                    start_count=processed_content.count(start),
                                    end_count=processed_content.count(end))

            return {
                "response": processed_content,
                "raw_output": str(raw_response),  # Ensure serializable
                "timestamp": datetime.utcnow().isoformat()
            }

        except Exception as e:
            logger.error("response_processing.failed", error=str(e))
            return {
                "response": str(content),
                "raw_output": str(raw_response),
                "timestamp": datetime.utcnow().isoformat()
            }
    
    def _resolve_model(self, explicit_model: Optional[str], provider_config: Dict[str, Any]) -> str:
        """Resolve model using fallback chain"""
        # 1. Use explicitly passed model if provided
        if explicit_model:
            return explicit_model
            
        # 2. Check agent-specific config
        agent_config = self.config.get("llm_config", {}).get("agents", {}).get(self._get_agent_name(), {})
        if "model" in agent_config:
            return agent_config["model"]
            
        # 3. Use provider's default model
        if "default_model" in provider_config:
            return provider_config["default_model"]
            
        # 4. Use system-wide default model
        system_default = self.config.get("llm_config", {}).get("default_model")
        if system_default:
            return system_default
        
        raise ValueError(f"No model specified for provider {self.provider} and no defaults found")

    def _get_model_str(self) -> str:
        """Get the appropriate model string for the provider"""
        if self.provider == LLMProvider.OPENAI:
            return self.model
        elif self.provider == LLMProvider.ANTHROPIC:
            return f"anthropic/{self.model}"
        elif self.provider == LLMProvider.GEMINI:
            return f"google/{self.model}"
        else:
            return f"{self.provider.value}/{self.model}"

    def _get_provider_config(self, provider: LLMProvider) -> Dict[str, Any]:
        """Get provider configuration from system config"""
        return self.config.get("providers", {}).get(provider.value, {})

    def _get_agent_config(self) -> Dict[str, Any]:
        """Extract relevant config for this agent"""
        try:
            # If we have a project, use its configuration system
            if self.project:
                config = self.project.get_agent_config(self._get_agent_name())
                logger.debug("agent.using_project_config",
                           agent=self._get_agent_name(),
                           project=self.project.metadata.name)
                return config
                
            # Use locate_config to find agent's settings
            agent_config = locate_config(self.config or {}, self._get_agent_name())
            
            # Get provider name - prefer agent specific over default
            provider_name = agent_config.get('provider', 
                                        self.config.get('llm_config', {}).get('default_provider'))
            
            # Get provider level config
            provider_config = self.config.get('providers', {}).get(provider_name, {})
            
            # Resolve model using proper chain
            model = self._resolve_model(agent_config.get('model'), provider_config)
            
            # Build complete config with correct override order
            config = {
                'provider': provider_name,
                'model': model,  # Using resolved model
                'temperature': 0,
                'api_base': provider_config.get('api_base'),
                'context_length': provider_config.get('context_length')
            }
            
            # Override with agent specific settings (most specific wins)
            config.update({
                k: v for k, v in agent_config.items() 
                if k in ['provider', 'temperature', 'api_base']
            })
            
            logger.debug("agent.config_loaded",
                        agent=self._get_agent_name(),
                        config=config)
                        
            return config

        except Exception as e:
            logger.error("agent.config_failed",
                        agent=self._get_agent_name(),
                        error=str(e))
            return {}

    def ensure_paths(self) -> None:
        """Ensure required project paths exist"""
        if not self.project:
            return
            
        try:
            # Create standard paths if they don't exist
            self.project.paths.workspace.mkdir(parents=True, exist_ok=True)
            self.project.paths.output.mkdir(parents=True, exist_ok=True)
            
            # Log path status
            logger.debug("agent.paths_validated",
                        workspace=str(self.project.paths.workspace),
                        output=str(self.project.paths.output))
                        
        except Exception as e:
            logger.error("agent.path_validation_failed",
                        error=str(e))
        
    def resolve_path(self, path: Union[str, Path]) -> Path:
        """Resolve path using project context if available"""
        path = Path(path)
        if self.project:
            return self.project.resolve_path(path)
        return path.resolve()
        
    def get_relative_path(self, path: Union[str, Path]) -> Path:
        """Get path relative to project root if available"""
        if self.project:
            return self.project.get_relative_path(Path(path))
        return Path(path)        

    def _should_log(self, level: LogDetail) -> bool:
        """Check if should log at this level"""
        log_levels = {
            LogDetail.MINIMAL: 0,
            LogDetail.BASIC: 1, 
            LogDetail.DETAILED: 2,
            LogDetail.DEBUG: 3
        }
        return log_levels[level] <= log_levels[self.log_level]
    
    def _update_metrics(self, duration: float, success: bool, error: Optional[str] = None) -> None:
        """Update agent metrics"""
        self.metrics["total_requests"] += 1
        self.metrics["total_duration"] += duration
        if success:
            self.metrics["successful_requests"] += 1
        else:
            self.metrics["failed_requests"] += 1
            self.metrics["last_error"] = error

        if self._should_log(LogDetail.DETAILED):
            logger.info("agent.metrics_updated",
                       metrics=self.metrics,
                       duration=duration,
                       success=success)

    def _setup_litellm(self, provider_config: Dict[str, Any]) -> None:
        """Configure litellm with provider settings"""
        litellm_config = provider_config.get("litellm_params", {})
        
        for key, value in litellm_config.items():
            setattr(litellm, key, value)
            
        if self._should_log(LogDetail.DEBUG):
            logger.debug("litellm.configured", 
                        provider=self.provider.serialize(),
                        config=litellm_config)

    @abstractmethod
    def _get_agent_name(self) -> str:
        """Get agent name for config lookup"""
        pass
        
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
    
    def _get_llm_content(self, response: Any) -> str:
        """Extract content from LLM response regardless of provider/library"""
        if hasattr(response, 'choices') and response.choices:
            return response.choices[0].message.content
        return str(response)