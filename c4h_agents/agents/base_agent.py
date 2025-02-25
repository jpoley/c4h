"""
Base agent implementation.
Path: c4h_agents/agents/base_agent.py
"""

from typing import Dict, Any, Optional, List, Tuple
import structlog
import json
from pathlib import Path
from datetime import datetime

from c4h_agents.core.project import Project
from c4h_agents.config import create_config_node
from .base_lineage import BaseLineage
from .types import LogDetail, LLMProvider, LLMMessages, AgentResponse, AgentMetrics
from .base_config import BaseConfig, log_operation
from .base_llm import BaseLLM

logger = structlog.get_logger()

class BaseAgent(BaseConfig, BaseLLM):
    """Base agent implementation"""
    
    def __init__(self, config: Dict[str, Any] = None, project: Optional[Project] = None):
        # Pass full config to BaseConfig
        super().__init__(config=config, project=project)
        
        # Create configuration node for hierarchical access
        self.config_node = create_config_node(self.config)
        agent_name = self._get_agent_name()
        
        # Ensure system namespace exists
        if "system" not in self.config:
            self.config["system"] = {}
            
        # Resolve provider, model, and temperature using hierarchical lookup
        agent_path = f"llm_config.agents.{agent_name}"
        provider_name = self.config_node.get_value(f"{agent_path}.provider") or self.config_node.get_value("llm_config.default_provider") or "anthropic"
        self.provider = LLMProvider(provider_name)
        
        self.model = self.config_node.get_value(f"{agent_path}.model") or self.config_node.get_value("llm_config.default_model") or "claude-3-opus-20240229"
        self.temperature = self.config_node.get_value(f"{agent_path}.temperature") or 0
        
        # Continuation settings
        self.max_continuation_attempts = self.config_node.get_value(f"{agent_path}.max_continuation_attempts") or 5
        self.continuation_token_buffer = self.config_node.get_value(f"{agent_path}.continuation_token_buffer") or 1000
        
        # Initialize metrics
        self.metrics = AgentMetrics(project=self.project.metadata.name if self.project else None)
        
        # Set logging detail level from config
        log_level = self.config_node.get_value("logging.agent_level") or "basic"
        self.log_level = LogDetail.from_str(log_level)
        
        # Build model string and setup LiteLLM
        self.model_str = self._get_model_str()
        self._setup_litellm(self._get_provider_config(self.provider))
        
        # Initialize logger with enhanced context
        log_context = {
            "agent": agent_name,
            "provider": self.provider.serialize(),
            "model": self.model,
            "log_level": str(self.log_level)
        }
        if self.project:
            log_context.update({
                "project_name": self.project.metadata.name,
                "project_version": self.project.metadata.version,
                "project_root": str(self.project.paths.root)
            })
            
        self.logger = structlog.get_logger().bind(**log_context)
        
        # Initialize lineage tracking with the full configuration
        self.lineage = None
        try:
            # Log what run_id we're using
            run_id = self._get_workflow_run_id()
            if run_id:
                logger.debug(f"{agent_name}.using_workflow_run_id", 
                            run_id=run_id, 
                            source="config", 
                            config_keys=list(self.config.keys()))
            
            self.lineage = BaseLineage(
                namespace="c4h_agents",
                agent_name=agent_name,
                config=self.config
            )
        except Exception as e:
            logger.error(f"{agent_name}.lineage_init_failed", error=str(e))

        logger.info(f"{agent_name}.initialized", 
                    continuation_settings={
                        "max_attempts": self.max_continuation_attempts,
                        "token_buffer": self.continuation_token_buffer
                    },
                    **log_context)

    def _get_workflow_run_id(self) -> Optional[str]:
        """Extract workflow run ID from configuration using hierarchical path queries"""
        # Check hierarchical sources in order of priority
        run_id = (
            # 1. Direct context parameter (highest priority)
            self.config_node.get_value("workflow_run_id") or
            # 2. System namespace
            self.config_node.get_value("system.runid") or
            # 3. Runtime configuration (backward compatibility)
            self.config_node.get_value("runtime.workflow_run_id") or
            self.config_node.get_value("runtime.run_id") or
            # 4. Workflow section 
            self.config_node.get_value("runtime.workflow.id")
        )
        
        if run_id:
            return str(run_id)
        return None

    def process(self, context: Dict[str, Any]) -> AgentResponse:
        """Main process entry point"""
        return self._process(context)

    def _process(self, context: Dict[str, Any]) -> AgentResponse:
        try:
            if self._should_log(LogDetail.DETAILED):
                logger.info("agent.processing", context_keys=list(context.keys()) if context else None)
            data = self._get_data(context)
            system_message = self._get_system_message()
            user_message = self._format_request(data)
            if self._should_log(LogDetail.DEBUG):
                logger.debug("agent.messages",
                            system_length=len(system_message),
                            user_length=len(user_message),
                            system=system_message[:500] + "..." if len(system_message) > 500 else system_message,
                            user_message=user_message[:500] + "..." if len(user_message) > 500 else user_message)
            enhanced_context = {
                **context,
                "prompts": {
                    "system": system_message,
                    "user": user_message
                }
            }
            workflow_run_id = context.get('workflow_run_id')
            if workflow_run_id:
                enhanced_context['workflow_run_id'] = workflow_run_id
                logger.debug("lineage.workflow_id_found", workflow_run_id=workflow_run_id)
            messages = LLMMessages(
                system=system_message,
                user=user_message,
                formatted_request=user_message,
                raw_context=enhanced_context
            )
            try:
                lineage_enabled = hasattr(self, 'lineage') and self.lineage and getattr(self.lineage, 'enabled', False)
                if lineage_enabled:
                    try:
                        logger.debug("lineage.start_tracking", agent=self._get_agent_name())
                        if hasattr(self.lineage, 'emit_start'):
                            self.lineage.emit_start(enhanced_context)
                    except Exception as e:
                        logger.error("lineage.start_tracking_failed", error=str(e), agent=self._get_agent_name())
                content, raw_response = self._get_completion_with_continuation([
                    {"role": "system", "content": messages.system},
                    {"role": "user", "content": messages.user}
                ])
                processed_data = self._process_response(content, raw_response)
                if lineage_enabled:
                    try:
                        logger.debug("lineage.tracking_attempt", agent=self._get_agent_name(), has_context=bool(enhanced_context), has_messages=bool(messages), has_metrics=hasattr(raw_response, 'usage'))
                        if hasattr(self.lineage, 'track_llm_interaction'):
                            self.lineage.track_llm_interaction(
                                context=enhanced_context,
                                messages=messages,
                                response=raw_response,
                                metrics={"token_usage": getattr(raw_response, 'usage', {})}
                            )
                        elif hasattr(self.lineage, 'emit_complete'):
                            self.lineage.emit_complete(
                                context=enhanced_context,
                                result={
                                    "processed_data": processed_data,
                                    "metrics": {"token_usage": getattr(raw_response, 'usage', {})}
                                }
                            )
                        logger.info("lineage.tracking_complete", agent=self._get_agent_name())
                    except Exception as e:
                        logger.error("lineage.tracking_failed", error=str(e), error_type=type(e).__name__, agent=self._get_agent_name())
                else:
                    logger.debug("lineage.tracking_skipped",
                            has_lineage=hasattr(self, 'lineage'),
                            lineage_enabled=getattr(self.lineage, 'enabled', False) if hasattr(self, 'lineage') else False,
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
                if lineage_enabled and hasattr(self.lineage, 'emit_failed'):
                    try:
                        self.lineage.emit_failed(enhanced_context, str(e))
                    except Exception as lineage_error:
                        logger.error("lineage.failure_tracking_failed", error=str(lineage_error))
                logger.error("llm.completion_failed", error=str(e))
                return AgentResponse(success=False, data={}, error=f"LLM completion failed: {str(e)}", messages=messages)
        except Exception as e:
            logger.error("process.failed", error=str(e))
            return AgentResponse(success=False, data={}, error=str(e))

    def _get_data(self, context: Dict[str, Any]) -> Dict[str, Any]:
        try:
            if isinstance(context, dict):
                return context
            return {'content': str(context)}
        except Exception as e:
            logger.error("get_data.failed", error=str(e))
            return {}

    def _format_request(self, context: Dict[str, Any]) -> str:
        return str(context)
    
    def _get_llm_content(self, response: Any) -> Any:
        try:
            if hasattr(response, 'choices') and response.choices:
                content = response.choices[0].message.content
                if self._should_log(LogDetail.DEBUG):
                    logger.debug("content.extracted_from_model", content_length=len(content) if content else 0)
                return content
            return str(response)
        except Exception as e:
            logger.error("content_extraction.failed", error=str(e))
            return str(response)

    def _process_response(self, content: str, raw_response: Any) -> Dict[str, Any]:
        try:
            processed_content = self._get_llm_content(content)
            if self._should_log(LogDetail.DEBUG):
                logger.debug("agent.processing_response", content_length=len(str(processed_content)) if processed_content else 0, response_type=type(raw_response).__name__)
            response = {
                "response": processed_content,
                "raw_output": str(raw_response),
                "timestamp": datetime.utcnow().isoformat()
            }
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
        return []

    def _get_agent_name(self) -> str:
        return self.__class__.__name__.lower()

    def _get_system_message(self) -> str:
        return self.config.get("llm_config", {}).get("agents", {}).get(self._get_agent_name(), {}).get("prompts", {}).get("system", "")

    def _get_prompt(self, prompt_type: str) -> str:
        prompts = self.config.get("llm_config", {}).get("agents", {}).get(self._get_agent_name(), {}).get("prompts", {})
        if prompt_type not in prompts:
            raise ValueError(f"No prompt template found for type: {prompt_type}")
        return prompts[prompt_type]
