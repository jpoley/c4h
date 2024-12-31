"""
Prefect task wrapper for agent execution.
Path: c4h_services/src/intent/impl/prefect/tasks.py
"""

from typing import Dict, Any, Type, Optional
from dataclasses import dataclass
from datetime import datetime
import structlog
from prefect import task, get_run_logger
from prefect.utilities.annotations import unmapped
from prefect.context import get_run_context
from pathlib import Path
import json

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
    retry_delay_seconds: int = 30
    task_name: Optional[str] = None

@task(retries=3, retry_delay_seconds=30, task_run_name="{task_name}")
def run_agent_task(
    agent_config: AgentTaskConfig,
    context: Dict[str, Any],
    workflow_state: Optional[Dict[str, Any]] = None,
    task_name: Optional[str] = None
) -> Dict[str, Any]:
    """
    Prefect task wrapper for agent execution.
    Maintains agent autonomy while providing orchestration.
    
    Args:
        agent_config: Configuration for agent execution
        context: Input context for agent
        workflow_state: Optional workflow state for context
        task_name: Optional task name for Prefect UI
    
    Returns:
        Dictionary containing:
        - success: Whether execution succeeded
        - stage_data: Data about this execution stage
        - error: Error message if failed
        - result_data: Raw result data from agent
    """
    prefect_logger = get_run_logger()
    run_context = get_run_context()
    
    try:
        # Log task start with context
        logger.info("agent_task.starting",
                   agent=agent_config.agent_class.__name__,
                   task_name=task_name or run_context.task_run.name,
                   requires_approval=agent_config.requires_approval)

        # Initialize agent with its config
        agent = agent_config.agent_class(config=agent_config.config)

        # Add workflow state context if provided
        if workflow_state:
            context["workflow_state"] = workflow_state

        # Add Prefect context
        context["prefect_context"] = {
            "flow_run_id": str(run_context.flow_run.id),
            "task_run_id": str(run_context.task_run.id),
            "task_name": task_name or run_context.task_run.name
        }

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

        # Enhance logging with result metrics
        logger.info("agent_task.completed",
                   agent=agent_config.agent_class.__name__,
                   success=result.success,
                   metrics=stage_data.metrics,
                   files_count=len(stage_data.files))

        return {
            "success": result.success,
            "stage_data": stage_data.__dict__,
            "error": result.error,
            "result_data": result.data
        }

    except Exception as e:
        error_msg = str(e)
        logger.error("agent_task.failed",
                    agent=agent_config.agent_class.__name__,
                    error=error_msg,
                    task_name=task_name)
                    
        # Return structured error response
        return {
            "success": False,
            "stage_data": StageData(
                status="failed",
                error=error_msg,
                timestamp=datetime.utcnow().isoformat()
            ).__dict__,
            "error": error_msg,
            "result_data": {}
        }

# Convenience factory functions for agent tasks
def create_discovery_task(config: Dict[str, Any]) -> AgentTaskConfig:
    """Create discovery agent task configuration"""
    from c4h_agents.agents.discovery import DiscoveryAgent
    return AgentTaskConfig(
        agent_class=DiscoveryAgent,
        config=config,
        task_name="discovery"
    )

def create_solution_task(config: Dict[str, Any]) -> AgentTaskConfig:
    """Create solution designer task configuration"""
    from c4h_agents.agents.solution_designer import SolutionDesigner
    return AgentTaskConfig(
        agent_class=SolutionDesigner,
        config=config,
        requires_approval=True,
        task_name="solution_design"
    )

def create_coder_task(config: Dict[str, Any]) -> AgentTaskConfig:
    """Create coder task configuration"""
    from c4h_agents.agents.coder import Coder
    return AgentTaskConfig(
        agent_class=Coder,
        config=config,
        max_retries=2,
        task_name="coder"
    )

def create_assurance_task(config: Dict[str, Any]) -> AgentTaskConfig:
    """Create assurance task configuration"""
    from c4h_agents.agents.assurance import AssuranceAgent
    return AgentTaskConfig(
        agent_class=AssuranceAgent,
        config=config,
        task_name="assurance"
    )