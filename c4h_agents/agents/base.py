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
        Get completion with automatic continuation handling.
        Handles overload conditions with exponential backoff.
        """
        try:
            attempt = 0
            max_tries = max_attempts or self.max_continuation_attempts
            accumulated_content = ""
            final_response = None
            retry_count = 0
            max_retries = 5  # Max retries for overload conditions
            
            # Get provider config excluding retry settings
            provider_config = self._get_provider_config(self.provider)
            
            # Basic completion parameters
            completion_params = {
                "model": self.model_str,
                "messages": messages,
            }

            # Only add temperature for providers that support it
            if self.provider != LLMProvider.OPENAI:
                completion_params["temperature"] = self.temperature
            
            if "api_base" in provider_config:
                completion_params["api_base"] = provider_config["api_base"]

            while attempt < max_tries:
                if attempt > 0:
                    logger.info("llm.continuation_attempt",
                            attempt=attempt,
                            messages_count=len(messages))
                
                try:
                    response = completion(**completion_params)

                    # Reset retry count on successful completion
                    retry_count = 0

                    if not response or not response.choices:
                        logger.error("llm.no_response",
                                attempt=attempt,
                                provider=self.provider.serialize())
                        break

                    # Process response through standard interface
                    result = self._process_response(response, response)
                    final_response = response
                    accumulated_content += result['response']
                    
                    finish_reason = getattr(response.choices[0], 'finish_reason', None)
                        
                    if finish_reason == 'length':
                        logger.info("llm.length_limit_reached", attempt=attempt)
                        messages.append({"role": "assistant", "content": result['response']})
                        messages.append({
                            "role": "user", 
                            "content": "Continue exactly from where you left off, maintaining exact format and indentation. Do not repeat any content."
                        })
                        completion_params["messages"] = messages
                        attempt += 1
                        continue
                    else:
                        logger.info("llm.completion_finished",
                                finish_reason=finish_reason,
                                continuation_count=attempt)
                        break

                except litellm.InternalServerError as e:
                    error_data = str(e)
                    if "overloaded_error" in error_data:
                        retry_count += 1
                        if retry_count > max_retries:
                            logger.error("llm.max_retries_exceeded",
                                    retries=retry_count,
                                    error=str(e))
                            raise
                            
                        # Exponential backoff
                        delay = min(2 ** (retry_count - 1), 32)  # Max 32 second delay
                        logger.warning("llm.overloaded_retrying",
                                    retry_count=retry_count,
                                    delay=delay)
                        time.sleep(delay)
                        continue
                    else:
                        raise

                except Exception as e:
                    logger.error("llm.request_failed", 
                            error=str(e),
                            attempt=attempt)
                    raise

            if final_response and final_response.choices:
                final_response.choices[0].message.content = accumulated_content

            self.metrics["continuation_attempts"] = attempt + 1
            return accumulated_content, final_response

        except Exception as e:
            logger.error("llm.continuation_failed", error=str(e))
            raise

    def _process_response(self, content: str, raw_response: Any) -> Dict[str, Any]:
        """
        Process LLM response with comprehensive validation and logging.
        Maintains consistent response format while preserving metadata.
        
        Args:
            content: Initial content from LLM
            raw_response: Complete response object
            
        Returns:
            Standardized response dictionary with:
            - response: Processed content
            - raw_output: Original response string
            - timestamp: Processing time
            - usage: Token usage if available
            - error: Any processing errors
        """
        try:
            # Extract content using standard method
            processed_content = self._get_llm_content(content)
            
            # Debug logging for response processing
            if self._should_log(LogDetail.DEBUG):
                logger.debug("agent.processing_response",
                            content_length=len(str(processed_content)) if processed_content else 0,
                            response_type=type(raw_response).__name__,
                            continuation_attempts=self.metrics["continuation_attempts"])

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
            error_msg = str(e)
            logger.error("response_processing.failed", 
                        error=error_msg,
                        content_type=type(content).__name__)
            return {
                "response": str(content),
                "raw_output": str(raw_response),
                "timestamp": datetime.utcnow().isoformat(),
                "error": error_msg
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
        try:
            provider_config = self.config.get("providers", {}).get(provider.value, {})
            
            # Ensure litellm_params contains retry configuration
            litellm_params = provider_config.get("litellm_params", {})
            if "retry" not in litellm_params:
                litellm_params.update({
                    "retry": True,
                    "max_retries": 3,
                    "backoff": {
                        "initial_delay": 1,
                        "max_delay": 30,
                        "exponential": True
                    }
                })
                provider_config["litellm_params"] = litellm_params
                
            if self._should_log(LogDetail.DEBUG):
                logger.debug("provider.config_loaded", 
                            provider=str(provider),
                            retry_config=litellm_params.get("retry"),
                            max_retries=litellm_params.get("max_retries"))
                    
            return provider_config
                
        except Exception as e:
            logger.error("provider.config_failed", 
                        provider=str(provider),
                        error=str(e))
            return {}

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
        try:
            litellm_params = provider_config.get("litellm_params", {})
            
            # Set retry configuration globally
            if "retry" in litellm_params:
                litellm.success_callback = []
                litellm.failure_callback = []
                litellm.retry = litellm_params.get("retry", True)
                litellm.max_retries = litellm_params.get("max_retries", 3)
                
                # Handle backoff settings
                backoff = litellm_params.get("backoff", {})
                litellm.retry_wait = backoff.get("initial_delay", 1)
                litellm.max_retry_wait = backoff.get("max_delay", 30)
                litellm.retry_exponential = backoff.get("exponential", True)
                
            # Set rate limits if provided
            if "rate_limit_policy" in litellm_params:
                rate_limits = litellm_params["rate_limit_policy"]
                litellm.requests_per_min = rate_limits.get("requests", 50)
                litellm.token_limit = rate_limits.get("tokens", 4000)
                litellm.limit_period = rate_limits.get("period", 60)
                
            if self._should_log(LogDetail.DEBUG):
                logger.debug("litellm.configured", 
                            provider=self.provider.serialize(),
                            retry_settings={
                                "enabled": litellm.retry,
                                "max_retries": litellm.max_retries,
                                "initial_delay": litellm.retry_wait,
                                "max_delay": litellm.max_retry_wait
                            })

        except Exception as e:
            logger.error("litellm.setup_failed", error=str(e))
            # Don't re-raise - litellm setup failure shouldn't be fatal

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