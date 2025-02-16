"""
Prefect task wrapper for agent execution.
Path: c4h_services/src/intent/impl/prefect/tasks.py
"""

from typing import Dict, Any, Optional
import structlog
from prefect import task, get_run_logger
from pathlib import Path

from c4h_agents.agents.base_agent import BaseAgent, AgentResponse 
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
    """Prefect task wrapper for agent execution."""
    prefect_logger = get_run_logger()
    
    try:
        # Initialize agent
        agent = agent_config.agent_class(config=agent_config.config)
        task_name = task_name or agent_config.task_name

        prefect_logger.info(f"Running {task_name} task")

        # Special handling for iterator
        if isinstance(agent, SemanticIterator):
            # Iterator handling remains unchanged
            pass
            
        # Standard agent execution
        result = agent.process(context)
        
        # Capture complete agent response including messages
        response = {
            "success": result.success,
            "result_data": result.data,
            "error": result.error,
            "input": {
                "messages": result.messages.to_dict() if result.messages else None,
                "context": context
            },
            "raw_output": result.raw_output,
            "metrics": result.metrics
        }

        return response

    except Exception as e:
        error_msg = str(e)
        logger.error(f"Task failed: {error_msg}")
        return {
            "success": False,
            "result_data": {},
            "error": error_msg,
            "input": {"context": context},  # Preserve original context on error
            "raw_output": None,
            "metrics": None
        }