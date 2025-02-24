"""
Path: c4h_services/src/intent/impl/prefect/tasks.py
Task wrapper implementation with proper run ID and context propagation.
"""

from typing import Dict, Any, Optional
import structlog
from prefect import task, get_run_logger
from prefect.runtime import flow_run
from pathlib import Path

from c4h_agents.agents.base_agent import BaseAgent
from c4h_agents.skills.semantic_iterator import SemanticIterator
from c4h_agents.skills.shared.types import ExtractConfig
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
        # Ensure agent configuration has system.runid set
        if 'system' not in agent_config.config:
            agent_config.config['system'] = {}
            
        # Initialize agent with complete config
        agent = agent_config.agent_class(config=agent_config.config)
        task_name = task_name or agent_config.task_name

        # Ensure workflow run ID propagation using hierarchy:
        # 1. Context workflow_run_id
        # 2. Flow run ID
        # 3. Runtime config run_id
        run_id = (
            context.get('workflow_run_id') or 
            str(flow_run.get_id()) or
            agent_config.config.get('runtime', {}).get('run_id') or
            agent_config.config.get('system', {}).get('runid')
        )
        
        if not run_id:
            logger.warning("task.missing_run_id", 
                task=task_name,
                context_keys=list(context.keys()))
        else:
            # Set the run ID in both places to ensure it's found
            agent_config.config['system']['runid'] = run_id
            if 'workflow_run_id' not in context:
                context['workflow_run_id'] = run_id

        prefect_logger.info(f"Running {task_name} task with run_id: {run_id}")

        # Enhance context with task metadata
        enhanced_context = {
            **context,
            'workflow_run_id': run_id,
            'task_name': task_name,
            'task_retry_count': agent_config.max_retries
        }

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