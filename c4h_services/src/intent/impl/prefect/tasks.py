"""
Prefect task wrappers for agent execution.
Path: c4h_services/src/intent/impl/prefect/tasks.py
"""

from typing import Dict, Any, Type, Optional
from dataclasses import dataclass
from datetime import datetime
import structlog
from prefect import task, get_run_logger
from pathlib import Path

from c4h_agents.agents.base import BaseAgent, AgentResponse
from c4h_agents.models.workflow_state import WorkflowState, StageData

logger = structlog.get_logger()

@dataclass
class AgentTaskConfig:
    """Configuration for agent task execution"""
    agent_class: Type[BaseAgent]
    config: Dict[str, Any]
    requires_approval: bool = False
    max_retries: int = 3

@task(retries=3, retry_delay_seconds=30)
def run_agent_task(
    agent_config: AgentTaskConfig,
    context: Dict[str, Any],
    workflow_state: Optional[Dict[str, Any]] = None
) -> Dict[str, Any]:
    """
    Prefect task wrapper for agent execution.
    Maintains agent autonomy while providing orchestration.
    """
    prefect_logger = get_run_logger()

    try:
        # Initialize agent with its config
        agent = agent_config.agent_class(config=agent_config.config)
        logger.info("agent_task.initialized", 
                   agent_type=agent_config.agent_class.__name__)

        # Add workflow state context if provided
        if workflow_state:
            context["workflow_state"] = workflow_state

        # Execute agent
        result = agent.process(context)

        # Create stage data
        stage_data = StageData(
            status="completed" if result.success else "failed",
            raw_output=result.data.get("raw_output", ""),
            files=result.data.get("files", {}),
            timestamp=datetime.utcnow().isoformat(),
            error=result.error,
            metrics=result.data.get("metrics", {})
        )

        return {
            "success": result.success,
            "stage_data": stage_data.__dict__,
            "error": result.error,
            "result_data": result.data
        }

    except Exception as e:
        logger.error("agent_task.failed",
                    agent=agent_config.agent_class.__name__,
                    error=str(e))
        return {
            "success": False,
            "stage_data": StageData(
                status="failed",
                error=str(e),
                timestamp=datetime.utcnow().isoformat()
            ).__dict__,
            "error": str(e),
            "result_data": {}
        }