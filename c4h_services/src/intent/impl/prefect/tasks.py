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
            input_data = context.get('input_data', {})
            
            # Handle both string and dict input formats
            if isinstance(input_data, str):
                content = input_data
                instruction = agent_config.config.get('instruction', '')
                format_hint = agent_config.config.get('format', 'json')
            else:
                content = input_data.get('content', input_data.get('input_data', ''))
                instruction = input_data.get('instruction', agent_config.config.get('instruction', ''))
                format_hint = input_data.get('format', agent_config.config.get('format', 'json'))

            # Configure iterator
            extract_config = ExtractConfig(
                instruction=instruction,
                format=format_hint
            )
            
            # Use iterator directly like testharness
            agent.configure(content=content, config=extract_config)
            results = []
            for item in agent:
                results.append(item)
                prefect_logger.info(f"Extracted item: {item}")

            return {
                "success": bool(results),
                "result_data": {"results": results},
                "error": None if results else "No items extracted"
            }
            
        # Standard agent execution
        result = agent.process(context)
        
        return {
            "success": result.success,
            "result_data": result.data,
            "error": result.error
        }

    except Exception as e:
        error_msg = str(e)
        logger.error(f"Task failed: {error_msg}")
        return {
            "success": False,
            "result_data": {},
            "error": error_msg
        }