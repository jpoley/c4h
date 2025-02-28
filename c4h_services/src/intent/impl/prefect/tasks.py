"""
Path: c4h_services/src/intent/impl/prefect/tasks.py
Task wrapper implementation with enhanced configuration handling.
"""

from typing import Dict, Any, Optional
import structlog
from prefect import task, get_run_logger
from prefect.runtime import flow_run
import importlib

from c4h_agents.agents.base_agent import BaseAgent
from c4h_agents.skills.semantic_iterator import SemanticIterator
from c4h_agents.skills.shared.types import ExtractConfig
from c4h_agents.config import create_config_node
from .models import AgentTaskConfig

logger = structlog.get_logger()

@task(retries=2, retry_delay_seconds=10)
def run_agent_task(
    agent_config: AgentTaskConfig,
    context: Dict[str, Any],
    task_name: Optional[str] = None
) -> Dict[str, Any]:
    """Prefect task wrapper for agent execution with lineage tracking"""
    prefect_logger = get_run_logger()
    
    try:
        # Get task name from config or parameter
        task_name = task_name or agent_config.task_name
        
        # Create configuration nodes for hierarchical access
        config_node = create_config_node(agent_config.config)
        context_node = create_config_node(context)
        
        # Get the run ID with priority order using path queries
        run_id = (
            # 1. Context parameters (highest priority)
            context_node.get_value("workflow_run_id") or 
            context_node.get_value("system.runid") or
            # 2. Prefect flow context
            str(flow_run.get_id()) or
            # 3. Agent config
            config_node.get_value("workflow_run_id") or
            config_node.get_value("system.runid") or
            # 4. Runtime config (backward compatibility)
            config_node.get_value("runtime.workflow_run_id") or
            config_node.get_value("runtime.run_id")
        )
            
        # Initialize agent with the prepared configuration
        task_name = task_name or agent_config.task_name

        if not run_id:
            logger.warning("task.missing_run_id", 
                task=task_name,
                context_keys=list(context.keys()),
                config_keys=list(agent_config.config.keys()))
            # Create a fallback ID if nothing was found
            run_id = "fallback_" + str(flow_run.get_id())
        
        # Ensure run ID is set in both configuration locations
        if "system" not in agent_config.config:
            agent_config.config["system"] = {}
        agent_config.config["system"]["runid"] = run_id
        agent_config.config["workflow_run_id"] = run_id
        
        # Support both class instance and dynamic class loading
        agent_class = agent_config.agent_class
        
        # If a string is provided, dynamically load the class
        if isinstance(agent_class, str):
            try:
                module_path, class_name = agent_class.rsplit(".", 1)
                module = importlib.import_module(module_path)
                agent_class = getattr(module, class_name)
            except (ValueError, ImportError, AttributeError) as e:
                logger.error("task.agent_class_loading_failed", 
                           task=task_name,
                           agent_class=agent_class,
                           error=str(e))
                raise ValueError(f"Failed to load agent class {agent_class}: {str(e)}")
        
        # Log the configuration for debugging
        logger.debug("task.agent_config_prepared", 
                    task=task_name,
                    run_id=run_id,
                    config_has_system=bool(agent_config.config.get("system")),
                    context_has_workflow_run_id=bool(context.get("workflow_run_id")))

        prefect_logger.info(f"Running {task_name} task with run_id: {run_id}")

        # Enhance context with task metadata and ensure run ID is set
        enhanced_context = {
            **context,
            'workflow_run_id': run_id,
            'system': {'runid': run_id},  # Explicitly include system namespace
            'task_name': task_name,
            'task_retry_count': agent_config.max_retries
        }
        
        # Create the agent with configuration only
        # Each agent will create its own Project instance if needed
        agent = agent_class(config=agent_config.config)

        # Special handling for iterator
        if isinstance(agent, SemanticIterator):
            # Get extract config
            extract_config = None
            if 'config' in context:
                extract_config = ExtractConfig(**context['config'])
            
            # Configure iterator if config provided
            if extract_config:
                agent.configure(
                    content=context.get('content'),
                    config=extract_config
                )
                
            # Process with configured iterator
            result = agent.process(enhanced_context)
            
        else:
            # Standard agent execution
            result = agent.process(enhanced_context)
        
        # Capture complete agent response 
        response = {
            "success": result.success,
            "result_data": result.data,
            "error": result.error,
            "input": {
                "messages": result.messages.to_dict() if result.messages else None,
                "context": enhanced_context
            },
            "raw_output": result.raw_output,
            "metrics": result.metrics,
            "run_id": run_id,
            "task_name": task_name
        }

        return response

    except Exception as e:
        error_msg = str(e)
        logger.error(f"Task failed: {error_msg}")
        return {
            "success": False,
            "result_data": {},
            "error": error_msg,
            "input": {"context": context},  # Preserve original context
            "raw_output": None,
            "metrics": None,
            "task_name": task_name
        }