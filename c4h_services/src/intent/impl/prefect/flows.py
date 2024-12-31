"""
Prefect workflow definitions using native state management.
Path: c4h_services/src/intent/impl/prefect/flows.py
"""

from prefect import flow, task, get_run_logger
from prefect.states import Completed, Failed, Pending
from prefect.context import get_flow_context, FlowRunContext
from prefect.utilities.annotations import unmapped
from typing import Dict, Any, Optional
import structlog
from pathlib import Path
import json

from .tasks import (
    run_agent_task,
    create_discovery_task,
    create_solution_task,
    create_coder_task,
    create_assurance_task
)

logger = structlog.get_logger()

@flow(name="intent_refactoring",
      description="Main workflow for intent-based refactoring",
      retries=2,
      retry_delay_seconds=60,
      persist_result=True)
def run_intent_workflow(
    project_path: Path,
    intent_desc: Dict[str, Any],
    config: Dict[str, Any],
    max_iterations: int = 3
) -> Dict[str, Any]:
    """
    Main workflow for intent-based refactoring using Prefect state management.
    
    Args:
        project_path: Path to project to refactor
        intent_desc: Description of intended changes
        config: Complete configuration dictionary
        max_iterations: Maximum number of refinement iterations
        
    Returns:
        Dictionary containing workflow results and state
    """
    flow_context = get_flow_context()
    logger = get_run_logger()
    
    try:
        # Store initial metadata in flow state
        flow_run = flow_context.flow_run
        flow_run.update(
            parameters={
                "project_path": str(project_path),
                "intent": intent_desc,
                "max_iterations": max_iterations
            }
        )

        # Configure tasks
        discovery_config = create_discovery_task(config)
        solution_config = create_solution_task(config)
        coder_config = create_coder_task(config)
        assurance_config = create_assurance_task(config)

        # Run discovery with state tracking
        discovery_result = run_agent_task(
            agent_config=discovery_config,
            context={"project_path": str(project_path)},
            task_name="discovery"
        )
        
        if not discovery_result["success"]:
            return Failed(
                message=f"Discovery failed: {discovery_result['error']}",
                result={
                    "status": "error",
                    "error": discovery_result["error"],
                    "stage": "discovery",
                    "flow_id": str(flow_run.id)
                }
            )

        # Run solution design
        solution_result = run_agent_task(
            agent_config=solution_config,
            context={
                "input_data": {
                    "discovery_data": discovery_result["result_data"],
                    "intent": intent_desc
                },
                "iteration": 0  # Track in flow state
            },
            task_name="solution_design"
        )

        if not solution_result["success"]:
            return Failed(
                message=f"Solution design failed: {solution_result['error']}",
                result={
                    "status": "error",
                    "error": solution_result["error"],
                    "stage": "solution_design",
                    "flow_id": str(flow_run.id),
                    "discovery_data": discovery_result["stage_data"]
                }
            )

        # Run coder
        coder_result = run_agent_task(
            agent_config=coder_config,
            context={
                "input_data": solution_result["result_data"]
            },
            task_name="coder"
        )

        if not coder_result["success"]:
            return Failed(
                message=f"Code changes failed: {coder_result['error']}",
                result={
                    "status": "error",
                    "error": coder_result["error"],
                    "stage": "coder",
                    "flow_id": str(flow_run.id),
                    "discovery_data": discovery_result["stage_data"],
                    "solution_data": solution_result["stage_data"]
                }
            )

        # Run assurance
        assurance_result = run_agent_task(
            agent_config=assurance_config,
            context={
                "changes": coder_result["result_data"].get("changes", []),
                "intent": intent_desc
            },
            task_name="assurance"
        )

        # Return completed state with full result data
        return Completed(
            message="Workflow completed successfully",
            result={
                "status": "success",
                "flow_id": str(flow_run.id),
                "stages": {
                    "discovery": discovery_result["stage_data"],
                    "solution_design": solution_result["stage_data"],
                    "coder": coder_result["stage_data"],
                    "assurance": assurance_result["stage_data"]
                },
                "result": {
                    "changes": coder_result["result_data"].get("changes", []),
                    "validation": assurance_result["result_data"]
                }
            }
        )

    except Exception as e:
        error_msg = str(e)
        logger.error("intent_workflow.failed", error=error_msg)
        return Failed(
            message=f"Workflow failed: {error_msg}",
            result={
                "status": "error",
                "error": error_msg,
                "flow_id": str(flow_context.flow_run.id)
            }
        )

@flow(name="intent_recovery")
def run_recovery_workflow(
    flow_run_id: str,
    config: Dict[str, Any]
) -> Dict[str, Any]:
    """
    Recovery workflow for handling failed runs using Prefect states.
    """
    try:
        # Get failed flow run state
        flow_run = get_flow_context().client.read_flow_run(flow_run_id)
        
        if not flow_run.state.is_failed():
            return Completed(
                message="Flow run is not in failed state",
                result={"status": "error", "error": "Flow is not failed"}
            )

        # Extract failure point and data
        failed_result = flow_run.state.result()
        failed_stage = failed_result.get("stage")
        
        if not failed_stage:
            return Failed(
                message="Could not determine failure point",
                result={"status": "error", "error": "Unknown failure point"}
            )

        # Resume from failed stage
        # TODO: Implement stage-specific recovery logic
        return Pending(message="Recovery not yet implemented")

    except Exception as e:
        error_msg = str(e)
        logger.error("recovery_workflow.failed", error=error_msg)
        return Failed(
            message=f"Recovery failed: {error_msg}",
            result={"status": "error", "error": error_msg}
        )