"""
Basic intent workflow implementation focusing on core refactoring flow.
Path: c4h_services/src/intent/impl/prefect/workflows.py
"""

from prefect import flow, get_run_logger
from prefect.states import Completed, Failed
from typing import Dict, Any, Optional
import structlog
from pathlib import Path
from datetime import datetime, timezone

from .tasks import run_agent_task
from .factories import (
    create_discovery_task,
    create_solution_task,
    create_coder_task
)

logger = structlog.get_logger()

def store_event(workflow_dir: Path, stage: str, event_num: str, content: Any) -> None:
    """Store raw event content without parsing"""
    try:
        event_file = workflow_dir / 'events' / f'{event_num}_{stage}.txt'
        with open(event_file, 'w', encoding='utf-8') as f:
            f.write(f'Timestamp: {datetime.now(timezone.utc).isoformat()}\n')
            f.write(f'Stage: {stage}\n')
            f.write('Content:\n')
            f.write(str(content))
    except Exception as e:
        logger.error("workflow.storage.event_failed",
                    stage=stage,
                    error=str(e))

def store_workflow_state(workflow_dir: Path, state: str) -> None:
    """Store minimal workflow state"""
    try:
        state_file = workflow_dir / 'workflow_state.txt'
        with open(state_file, 'w', encoding='utf-8') as f:
            f.write(f'Timestamp: {datetime.now(timezone.utc).isoformat()}\n')
            f.write(f'Status: {state}\n')
    except Exception as e:
        logger.error("workflow.storage.state_failed", error=str(e))

def get_workflow_storage(config: Dict[str, Any]) -> Optional[Path]:
    """Initialize workflow storage directory if enabled"""
    storage_config = config.get('runtime', {}).get('workflow', {}).get('storage', {})
    if not storage_config.get('enabled', False):
        return None
        
    try:
        # Get prefect logger for context
        flow_logger = get_run_logger()
        # Extract ID from flow run context
        workflow_id = getattr(flow_logger, 'flow_run_id', 'default')
        
        root_dir = Path(storage_config.get('root_dir', 'workspaces/workflows'))
        format_str = storage_config.get('format', '{timestamp}_{workflow_id}')
        
        timestamp = datetime.now().strftime('%y%m%d_%H%M')
        workflow_dir = root_dir / format_str.format(
            workflow_id=workflow_id,
            timestamp=timestamp
        )
        
        workflow_dir.mkdir(parents=True, exist_ok=True)
        (workflow_dir / 'events').mkdir(exist_ok=True)
        
        return workflow_dir
        
    except Exception as e:
        logger.error("workflow.storage.init_failed", error=str(e))
        return None

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
    
    # Initialize workflow storage
    workflow_dir = get_workflow_storage(config)
    if workflow_dir:
        store_workflow_state(workflow_dir, "started")
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
        
        # Store raw discovery event
        if workflow_dir:
            store_event(workflow_dir, "discovery", "01", discovery_result)

        if not discovery_result["success"]:
            if workflow_dir:
                store_workflow_state(workflow_dir, f"error: {discovery_result.get('error', 'Unknown error')}")
            return Failed(
                message=f"Discovery failed: {discovery_result.get('error')}",
                result={
                    "status": "error",
                    "error": discovery_result.get('error'),
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

        # Store raw solution event
        if workflow_dir:
            store_event(workflow_dir, "solution_design", "02", solution_result)

        if not solution_result["success"]:
            if workflow_dir:
                store_workflow_state(workflow_dir, f"error: {solution_result.get('error', 'Unknown error')}")
            return Failed(
                message=f"Solution design failed: {solution_result.get('error')}",
                result={
                    "status": "error",
                    "error": solution_result.get('error'),
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

        # Store raw coder event
        if workflow_dir:
            store_event(workflow_dir, "coder", "03", coder_result)

        if not coder_result["success"]:
            if workflow_dir:
                store_workflow_state(workflow_dir, f"error: {coder_result.get('error', 'Unknown error')}")
            return Failed(
                message=f"Code implementation failed: {coder_result.get('error')}",
                result={
                    "status": "error",
                    "error": coder_result.get('error'),
                    "stage": "coder",
                    "discovery_data": discovery_result["result_data"],
                    "solution_data": solution_result["result_data"]
                }
            )

        flow_logger.info("Code implementation completed successfully")

        # Store final workflow state
        if workflow_dir:
            store_workflow_state(workflow_dir, "completed")

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
        
        # Store error state
        if workflow_dir:
            store_workflow_state(workflow_dir, f"error: {error_msg}")

        return Failed(
            message=f"Workflow failed: {error_msg}",
            result={
                "status": "error",
                "error": error_msg
            }
        )