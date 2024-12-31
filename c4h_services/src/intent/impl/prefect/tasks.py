"""
Prefect task wrapper for agent execution.
Path: c4h_services/src/intent/impl/prefect/tasks.py
"""

from typing import Dict, Any, Type, Optional
from dataclasses import dataclass
from datetime import datetime
import structlog
from prefect import task, get_run_logger
from prefect.context import get_run_context
from pathlib import Path

from c4h_agents.agents.base import BaseAgent
from c4h_agents.skills.semantic_iterator import SemanticIterator
from c4h_agents.skills.shared.types import ExtractConfig

logger = structlog.get_logger()

@dataclass
class AgentTaskConfig:
    """Configuration for agent task execution"""
    agent_class: Type[BaseAgent]
    config: Dict[str, Any]
    task_name: Optional[str] = None

@task(retries=2, retry_delay_seconds=10)
def run_agent_task(
    agent_config: AgentTaskConfig,
    context: Dict[str, Any],
    task_name: Optional[str] = None
) -> Dict[str, Any]:
    """
    Prefect task wrapper for agent execution.
    """
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
            
            prefect_logger.info(f"Configuring iterator with format: {format_hint}")
            
            agent.configure(
                content=content,
                config=extract_config
            )
            
            # Collect all items
            results = []
            try:
                for item in agent:
                    results.append(item)
                    prefect_logger.info(f"Extracted item {len(results)}")
            except StopIteration:
                if not results:
                    raise ValueError("No items could be extracted")

            return {
                "success": True,
                "result_data": {"results": results},
                "error": None
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