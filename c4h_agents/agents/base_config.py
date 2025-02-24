"""
Configuration management for agent implementations following design principles.
"""

from typing import Dict, Any, Optional, List, Union
from pathlib import Path
import structlog
from datetime import datetime
from functools import wraps
import time

from c4h_agents.core.project import Project, ProjectPaths
from c4h_agents.config import locate_config, locate_keys, get_value
from .types import LogDetail, LLMProvider

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

    def ensure_paths(self):
        # Implement path creation if necessary
        pass

    def lookup(self, path: str) -> Any:
        """
        Lookup a value in the full configuration using a hierarchical path (e.g., "system/runid").
        """
        return get_value(self.config, path)

    def _get_runtime_config(self) -> Dict[str, Any]:
        runtime_config = locate_config(self.config, "runtime")
        if not runtime_config:
            logger.debug("config.no_runtime_found", agent=self._get_agent_name())
            return {}
        logger.debug("config.runtime_loaded", agent=self._get_agent_name(), config_keys=list(runtime_config.keys()))
        return runtime_config

    def _get_lineage_config(self) -> Dict[str, Any]:
        runtime_config = self._get_runtime_config()
        lineage_config = runtime_config.get('lineage', {})
        logger.debug("config.lineage_loaded", agent=self._get_agent_name(), enabled=lineage_config.get('enabled', False), config_keys=list(lineage_config.keys()))
        return lineage_config

    def _get_provider_config(self, provider: LLMProvider) -> Dict[str, Any]:
        try:
            provider_config = self.config.get("llm_config", {}).get("providers", {}).get(provider.value, {})
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
                logger.debug("provider.config_loaded", provider=str(provider), retry_config=litellm_params.get("retry"), max_retries=litellm_params.get("max_retries"))
            return provider_config
        except Exception as e:
            logger.error("provider.config_failed", provider=str(provider), error=str(e))
            return {}

    def _get_agent_config(self) -> Dict[str, Any]:
        """
        Instead of returning a subtree, return the full configuration.
        Agents can use the lookup method to get agent-specific values.
        """
        return self.config

    def _resolve_model(self, explicit_model: Optional[str], provider_config: Dict[str, Any]) -> str:
        try:
            if explicit_model:
                model = explicit_model
            elif self.lookup(f"{self._get_agent_name()}/model"):
                model = self.lookup(f"{self._get_agent_name()}/model")
            elif "default_model" in provider_config:
                model = provider_config["default_model"]
            elif self.config.get("llm_config", {}).get("default_model"):
                model = self.config["llm_config"]["default_model"]
            else:
                raise ValueError(f"No model specified for provider and no defaults found")
            valid_models = provider_config.get("valid_models", [])
            if valid_models and model not in valid_models:
                logger.warning("config.invalid_model", model=model, valid_models=valid_models, using_default=provider_config.get("default_model"))
                model = provider_config.get("default_model")
                if not model:
                    raise ValueError(f"Invalid model {model} and no default available")
            return model
        except Exception as e:
            logger.error("config.model_resolution_failed", error=str(e), provider=self.provider.value if hasattr(self, 'provider') else None)
            raise

    def _should_log(self, level: LogDetail) -> bool:
        log_levels = {
            LogDetail.MINIMAL: 0,
            LogDetail.BASIC: 1, 
            LogDetail.DETAILED: 2,
            LogDetail.DEBUG: 3
        }
        return log_levels[level] <= log_levels[self.log_level]
    
    def _update_metrics(self, duration: float, success: bool, error: Optional[str] = None) -> None:
        self.metrics["total_requests"] += 1
        self.metrics["total_duration"] += duration
        if success:
            self.metrics["successful_requests"] += 1
        else:
            self.metrics["failed_requests"] += 1
            self.metrics["last_error"] = error
        if self._should_log(LogDetail.DETAILED):
            logger.info("agent.metrics_updated", metrics=self.metrics, duration=duration, success=success)

    def _get_agent_name(self) -> str:
        raise NotImplementedError("Agent classes must implement _get_agent_name")
