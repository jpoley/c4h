"""
Path: c4h_services/src/intent/impl/prefect/workflows.py
Core workflow implementation with proper run ID propagation.
"""

from prefect import flow, get_run_logger
from prefect.runtime import flow_run
from typing import Dict, Any, Optional
import structlog
from pathlib import Path
from datetime import datetime, timezone
from copy import deepcopy

from c4h_agents.core.project import Project
from .tasks import run_agent_task
from .factories import (
    create_discovery_task,
    create_solution_task,
    create_coder_task
)

logger = structlog.get_logger()

def prepare_workflow_config(base_config: Dict[str, Any]) -> Dict[str, Any]:
    """Prepare workflow configuration with proper run ID and context"""
    try:
        # Get workflow run ID from Prefect
        workflow_id = str(flow_run.get_id())
        
        # Deep copy to avoid mutations
        config = deepcopy(base_config)
        
        # Add runtime config following hierarchy
        if 'runtime' not in config:
            config['runtime'] = {}
            
        config['runtime'].update({
            'workflow_run_id': workflow_id,  # Primary workflow ID
            'run_id': workflow_id,          # Legacy support
            'workflow': {
                'id': workflow_id,
                'start_time': datetime.now(timezone.utc).isoformat()
            }
        })
        
        logger.debug("workflow.config_prepared",
            workflow_id=workflow_id,
            config_keys=list(config.keys()))
            
        return config
        
    except Exception as e:
        logger.error("workflow.config_prep_failed", error=str(e))
        raise

def resolve_project_path(project_path: Path, config: Dict[str, Any]) -> Path:
    """Resolve project path from config or provided path"""
    try:
        # Check config first
        config_project_path = config.get('project', {}).get('path')
        if config_project_path:
            project_dir = Path(config_project_path).resolve()
        else:
            # Fallback to provided path
            project_dir = Path(project_path).resolve()

        logger.info("workflow.paths.resolve",
            config_path=config_project_path,
            provided_path=str(project_path),
            resolved_dir=str(project_dir))

        if not project_dir.exists():
            raise ValueError(f"Project path does not exist: {project_dir}")

        return project_dir

    except Exception as e:
        logger.error("workflow.path_resolution_failed", error=str(e))
        raise

@flow(name="basic_refactoring")
def run_basic_workflow(
    project_path: Path,
    intent_desc: Dict[str, Any],
    config: Dict[str, Any]
) -> Dict[str, Any]:
    """Basic workflow implementing the core refactoring steps"""
    flow_logger = get_run_logger()
    
    try:
        # Get Prefect run ID
        workflow_id = str(flow_run.get_id())
        logger.info("workflow.initialized", 
                   flow_id=workflow_id,
                   project_path=str(project_path))
        
        # Prepare workflow configuration
        workflow_config = prepare_workflow_config(config)
        
        # Initialize project with proper context
        try:
            project_config = {
                'project': {
                    'path': str(project_path.resolve()),
                    'workspace_root': workflow_config.get('project', {}).get('workspace_root', 'workspaces')
                }
            }
            project = Project.from_config(project_config)
            workflow_config['project'] = project
        except Exception as e:
            logger.error("workflow.project_init_failed", error=str(e))
            raise

        # Configure agents with workflow context
        discovery_config = create_discovery_task(workflow_config)
        solution_config = create_solution_task(workflow_config)
        coder_config = create_coder_task(workflow_config)
        
        # Run discovery with lineage context
        discovery_result = run_agent_task(
            agent_config=discovery_config,
            context={
                "project_path": str(project_path),
                "workflow_run_id": workflow_id,
                "project": {
                    "path": str(project_path),
                    "workspace_root": project.paths.workspace
                }
            }
        )

        if not discovery_result.get("success"):
            return {
                "status": "error",
            "error": error_msg,
            "workflow_run_id": workflow_id,
            "stage": "workflow",
            "project_path": str(project_path)
        }

        # Run solution design with lineage context
        solution_result = run_agent_task(
            agent_config=solution_config,
            context={
                "input_data": {
                    "discovery_data": discovery_result["result_data"],
                    "intent": intent_desc,
                    "project": {
                        "path": str(project_path),
                        "workspace_root": project.paths.workspace
                    }
                },
                "workflow_run_id": workflow_id
            }
        )

        if not solution_result.get("success"):
            return {
                "status": "error",
                "error": solution_result.get("error"),
                "stage": "solution_design",
                "workflow_run_id": workflow_id,
                "project_path": str(project_path),
                "timestamp": datetime.now(timezone.utc).isoformat(),
                "discovery_data": discovery_result.get("result_data")
            }

        # Run coder with lineage context
        coder_result = run_agent_task(
            agent_config=coder_config,
            context={
                "input_data": solution_result["result_data"],
                "workflow_run_id": workflow_id,
                "project": {
                    "path": str(project_path),
                    "workspace_root": project.paths.workspace
                }
            }
        )

        if not coder_result.get("success"):
            return {
                "status": "error",
                "error": coder_result.get("error"),
                "stage": "coder",
                "workflow_run_id": workflow_id,
                "project_path": str(project_path),
                "timestamp": datetime.now(timezone.utc).isoformat(),
                "discovery_data": discovery_result.get("result_data"),
                "solution_data": solution_result.get("result_data")
            }

        # Return workflow result with lineage context
        return {
            "status": "success",
            "stages": {
                "discovery": discovery_result["result_data"],
                "solution_design": solution_result["result_data"],
                "coder": coder_result["result_data"]
            },
            "changes": coder_result["result_data"].get("changes", []),
            "project_path": str(project_path),
            "workflow_run_id": workflow_id,
            "metrics": {
                "discovery": discovery_result.get("metrics", {}),
                "solution_design": solution_result.get("metrics", {}),
                "coder": coder_result.get("metrics", {})
            },
            "timestamps": {
                "start": workflow_config["runtime"]["workflow"]["start_time"],
                "end": datetime.now(timezone.utc).isoformat()
            }
        }

    except Exception as e:
        error_msg = str(e)
        workflow_id = str(flow_run.get_id())  # Still try to get workflow ID for error tracking
        logger.error("workflow.failed", 
                    error=error_msg,
                    workflow_id=workflow_id,
                    project_path=str(project_path))
        return {
            "status": "error",
            "error": error_msg,
            "workflow_run_id": workflow_id,
            "project_path": str(project_path),
            "stage": "workflow",
            "timestamp": datetime.now(timezone.utc).isoformat()
        }