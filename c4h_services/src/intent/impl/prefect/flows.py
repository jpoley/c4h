"""
Prefect workflow definitions using native state management.
Path: c4h_services/src/intent/impl/prefect/flows.py
"""

from prefect import flow, task, get_run_logger
from prefect.states import Completed, Failed, Pending
from prefect.context import get_flow_context, FlowRunContext
from typing import Dict, Any, Optional
import structlog
from pathlib import Path
import json

from c4h_services.src.orchestration.orchestrator import Orchestrator

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

        # Create orchestrator for team-based execution
        orchestrator = Orchestrator(config)
        
        # Prepare context for team execution
        context = {
            "project_path": str(project_path),
            "intent": intent_desc,
            "workflow_run_id": str(flow_run.id),
            "max_iterations": max_iterations,
            "config": config
        }
        
        # Execute workflow using team-based orchestration
        result = orchestrator.execute_workflow(
            entry_team="discovery",  # Start with discovery team
            context=context,
            max_teams=max_iterations * 3  # Allow multiple iterations
        )
        
        if result.get("status") != "success":
            return Failed(
                message=f"Workflow failed: {result.get('error')}",
                result={
                    "status": "error",
                    "error": result.get("error"),
                    "flow_id": str(flow_run.id)
                }
            )
        
        # Return completed state with team execution results
        return Completed(
            message="Workflow completed successfully",
            result={
                "status": "success",
                "flow_id": str(flow_run.id),
                "data": result.get("data", {}),
                "changes": result.get("data", {}).get("changes", []),
                "execution_path": result.get("execution_path", []),
                "team_results": result.get("team_results", {})
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
        
        # Create orchestrator for team-based recovery
        orchestrator = Orchestrator(config)
        
        # Prepare recovery context
        context = {
            "workflow_run_id": flow_run_id,
            "failed_stage": failed_stage,
            "failed_result": failed_result,
            "config": config,
            "recovery": True
        }
        
        # Determine appropriate entry team for recovery
        entry_team = "recovery"  # Default recovery team
        if failed_stage == "discovery":
            entry_team = "discovery"
        elif failed_stage == "solution_design":
            entry_team = "solution"
        elif failed_stage == "coder":
            entry_team = "coder"
        
        # Execute recovery workflow
        result = orchestrator.execute_workflow(
            entry_team=entry_team,
            context=context
        )

        if result.get("status") != "success":
            return Failed(
                message=f"Recovery failed: {result.get('error')}",
                result={
                    "status": "error",
                    "error": result.get("error"),
                    "flow_id": flow_run_id
                }
            )
        
        return Completed(
            message="Recovery completed successfully",
            result={
                "status": "success",
                "flow_id": flow_run_id,
                "data": result.get("data", {}),
                "recovery_path": result.get("execution_path", [])
            }
        )

    except Exception as e:
        error_msg = str(e)
        logger.error("recovery_workflow.failed", error=error_msg)
        return Failed(
            message=f"Recovery failed: {error_msg}",
            result={"status": "error", "error": error_msg}
        )