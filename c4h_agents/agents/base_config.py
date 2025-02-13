"""
Configuration and project management for agent implementations.
Path: c4h_agents/agents/base_config.py
"""

from typing import Dict, Any, Optional, List, Union
from pathlib import Path
import structlog
from datetime import datetime
from functools import wraps
import time

from c4h_agents.core.project import Project, ProjectPaths
from c4h_agents.config import locate_config, locate_keys
from .types import (
    LogDetail, 
    LLMProvider
)

logger = structlog.get_logger()

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

class BaseConfig:
    """Configuration management for agent implementations"""
    
    def __init__(self, config: Dict[str, Any] = None, project: Optional[Project] = None):
        """Initialize configuration and project context"""
        self.config = config or {}
        self.project = project
        
        # Create important paths if using project
        if self.project:
            self.ensure_paths()

        # Set logging detail level from config
        log_level = self.config.get('logging', {}).get('agent_level', 'basic')
        self.log_level = LogDetail.from_str(log_level)
        
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

    def _get_provider_config(self, provider: LLMProvider) -> Dict[str, Any]:
        """Get provider configuration from merged config."""
        try:
            # Get from llm_config providers section
            provider_config = self.config.get("llm_config", {}).get("providers", {}).get(provider.value, {})
                
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
        """Extract relevant config for this agent."""
        try:
            agent_name = self._get_agent_name() 
            
            # If we have a project, use its configuration system
            if self.project:
                config = self.project.get_agent_config(agent_name)
                logger.debug("agent.using_project_config",
                        agent=agent_name,
                        project=self.project.metadata.name)
                return config
                
            # Use locate_config to find agent's settings in llm_config.agents
            agent_config = locate_config(self.config or {}, agent_name)

            # Get provider name - prefer agent specific over llm_config default
            provider_name = agent_config.get('provider', 
                                    self.config.get('llm_config', {}).get('default_provider'))
            
            # Use consistent provider config access method
            provider = LLMProvider(provider_name)
            provider_config = self._get_provider_config(provider)
            
            # Resolve model using proper chain
            model = self._resolve_model(agent_config.get('model'), provider_config)
            
            # Build complete config 
            config = {
                'provider': provider_name,
                'model': model,
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
        
        raise ValueError(f"No model specified for provider and no defaults found")

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
        """Get agent name for config lookup"""
        raise NotImplementedError("Agent classes must implement _get_agent_name")