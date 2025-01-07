"""
Basic intent workflow implementation focusing on core refactoring flow.
Path: c4h_services/src/intent/impl/prefect/workflows.py
"""

from prefect import flow, get_run_logger
from prefect.states import Completed, Failed
from typing import Dict, Any
import structlog
from pathlib import Path

from .tasks import run_agent_task
from .factories import (
    create_discovery_task,
    create_solution_task,
    create_coder_task
)

logger = structlog.get_logger()

@flow(name="basic_refactoring",
      description="Core workflow for intent-based refactoring",
      retries=1,
      retry_delay_seconds=60)
def run_basic_workflow(
    project_path: Path,
    intent_desc: Dict[str, Any],
    config: Dict[str, Any]
) -> Dict[str, Any]:
    """
    Basic workflow implementing the core refactoring steps:
    1. Discovery
    2. Solution Design
    3. Code Implementation
    """
    flow_logger = get_run_logger()
    flow_logger.info("Starting basic refactoring workflow")
    
    try:
        # Get project path from config if available, otherwise use provided path
        config_project_path = config.get('project', {}).get('path')
        if config_project_path:
            project_dir = Path(config_project_path).resolve()
            # Update config with resolved path
            config['project']['path'] = str(project_dir)
        else:
            # Fallback to provided path
            project_dir = Path(project_path).resolve()

        logger.info("workflow.paths.initialize",
            config_project_path=config_project_path,
            provided_path=str(project_path),
            resolved_dir=str(project_dir),
            cwd=str(Path.cwd())
        )

        if not project_dir.exists():
            return Failed(
                message=f"Project path does not exist: {project_dir}",
                result={
                    "status": "error",
                    "error": f"Project path does not exist: {project_dir}",
                    "stage": "discovery"
                }
            )

        # Update context with resolved project path
        discovery_config = create_discovery_task(config)
        discovery_result = run_agent_task(
            agent_config=discovery_config,
            context={
                "project_path": str(project_dir),
                "project": {
                    "path": str(project_dir),
                    "workspace_root": config.get('project', {}).get('workspace_root')
                }
            },
            task_name="discovery"
        )
        
        if not discovery_result["success"]:
            return Failed(
                message=f"Discovery failed: {discovery_result['error']}",
                result={
                    "status": "error",
                    "error": discovery_result["error"],
                    "stage": "discovery"
                }
            )

        flow_logger.info("Discovery completed successfully")

        # Ensure project context is passed to solution design
        solution_config = create_solution_task(config)
        solution_result = run_agent_task(
            agent_config=solution_config,
            context={
                "input_data": {
                    "discovery_data": discovery_result["result_data"],
                    "intent": intent_desc,
                    "project": {
                        "path": str(project_dir),
                        "workspace_root": config.get('project', {}).get('workspace_root')
                    }
                }
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
                    "discovery_data": discovery_result["result_data"]
                }
            )

        flow_logger.info("Solution design completed successfully")

        # Pass project context to coder
        coder_config = create_coder_task(config)
        coder_result = run_agent_task(
            agent_config=coder_config,
            context={
                "input_data": solution_result["result_data"],
                "project": {
                    "path": str(project_dir),
                    "workspace_root": config.get('project', {}).get('workspace_root')
                }
            },
            task_name="coder"
        )

        if not coder_result["success"]:
            return Failed(
                message=f"Code implementation failed: {coder_result['error']}",
                result={
                    "status": "error",
                    "error": coder_result["error"],
                    "stage": "coder",
                    "discovery_data": discovery_result["result_data"],
                    "solution_data": solution_result["result_data"]
                }
            )

        flow_logger.info("Code implementation completed successfully")

        # Return successful completion state
        return Completed(
            message="Workflow completed successfully",
            result={
                "status": "success",
                "stages": {
                    "discovery": discovery_result["result_data"],
                    "solution_design": solution_result["result_data"],
                    "coder": coder_result["result_data"]
                },
                "changes": coder_result["result_data"].get("changes", []),
                "project_path": str(project_dir)
            }
        )

    except Exception as e:
        error_msg = str(e)
        logger.error("basic_workflow.failed", error=error_msg)
        return Failed(
            message=f"Workflow failed: {error_msg}",
            result={
                "status": "error",
                "error": error_msg
            }
        )