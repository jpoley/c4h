"""
Path: c4h_services/src/intent/impl/prefect/workflows.py
Core workflow implementation with enhanced configuration handling.
"""

from prefect import flow, get_run_logger
from prefect.context import get_run_context
from typing import Dict, Any
import structlog
from pathlib import Path
from datetime import datetime, timezone
from copy import deepcopy
import uuid

from c4h_agents.config import create_config_node
from .tasks import run_agent_task
from .factories import (
    create_discovery_task,
    create_solution_task,
    create_coder_task
)

logger = structlog.get_logger()

def prepare_workflow_config(base_config: Dict[str, Any]) -> Dict[str, Any]:
    """
    Prepare workflow configuration with proper run ID and context.
    Uses hierarchical configuration access.
    """
    try:
        # Get workflow run ID from Prefect context
        ctx = get_run_context()
        if ctx is not None and hasattr(ctx, "flow_run") and ctx.flow_run and hasattr(ctx.flow_run, "id"):
            workflow_id = str(ctx.flow_run.id)
        else:
            workflow_id = str(uuid.uuid4())
            logger.warning("workflow.missing_prefect_context", generated_workflow_id=workflow_id)
        
        # Deep copy to avoid mutations
        config = deepcopy(base_config)
        
        # First, set the run ID at the root system namespace 
        if 'system' not in config:
            config['system'] = {}
        config['system']['runid'] = workflow_id
        
        # For backward compatibility, also set in runtime config
        if 'runtime' not in config:
            config['runtime'] = {}
            
        config['runtime'].update({
            'workflow_run_id': workflow_id,  # Primary workflow ID
            'run_id': workflow_id,           # Legacy support
            'workflow': {
                'id': workflow_id,
                'start_time': datetime.now(timezone.utc).isoformat()
            }
        })
        
        # Also set at top level for direct access
        config['workflow_run_id'] = workflow_id
        
        logger.debug("workflow.config_prepared",
            workflow_id=workflow_id,
            config_keys=list(config.keys()))
            
        return config
        
    except Exception as e:
        logger.error("workflow.config_prep_failed", error=str(e))
        raise

@flow(name="basic_refactoring")
def run_basic_workflow(
    project_path: Path,
    intent_desc: Dict[str, Any],
    config: Dict[str, Any]
) -> Dict[str, Any]:
    """
    Basic workflow implementing the core refactoring steps.
    Uses hierarchical configuration access for consistent run ID propagation.
    """
    run_logger = get_run_logger()
    
    try:
        # Prepare workflow configuration with proper run ID propagation
        workflow_config = prepare_workflow_config(config)
        
        # Create configuration node for path-based access
        config_node = create_config_node(workflow_config)
        
        # Log the workflow ID for debugging
        workflow_id = config_node.get_value("system.runid")
        logger.info("workflow.initialized", 
                  flow_id=workflow_id,
                  project_path=str(project_path))
        
        # Ensure project config exists - path resolution happens in asset manager
        if 'project' not in workflow_config:
            workflow_config['project'] = {}
            
        # Set original project path in config - let components resolve as needed
        if 'path' not in workflow_config['project']:
            workflow_config['project']['path'] = str(project_path)
        
        # Configure agent tasks - each agent will create its own domain objects if needed
        discovery_config = create_discovery_task(workflow_config)
        solution_config = create_solution_task(workflow_config)
        coder_config = create_coder_task(workflow_config)
        
        # Create a standard context that ensures the workflow ID is present
        base_context = {
            "workflow_run_id": workflow_id,
            "system": {"runid": workflow_id}  # Include system namespace directly
        }
        
        # Run discovery with consistent project config
        discovery_context = {
            **base_context,
            "project_path": str(project_path),
            "project": workflow_config['project']  # Pass config directly
        }
        logger.debug("workflow.discovery_context", 
                   workflow_id=workflow_id, 
                   context_keys=list(discovery_context.keys()))
        
        discovery_result = run_agent_task(
            agent_config=discovery_config,
            context=discovery_context
        )

        if not discovery_result.get("success"):
            return {
                "status": "error",
                "error": discovery_result.get("error"),
                "workflow_run_id": workflow_id,
                "stage": "workflow",
                "project_path": str(project_path)
            }

        # Run solution design with consistent project config
        solution_context = {
            **base_context,
            "input_data": {
                "discovery_data": discovery_result["result_data"],
                "intent": intent_desc,
                "project": workflow_config['project']  # Pass config directly
            }
        }
        logger.debug("workflow.solution_context", 
                   workflow_id=workflow_id, 
                   context_keys=list(solution_context.keys()))
                    
        solution_result = run_agent_task(
            agent_config=solution_config,
            context=solution_context
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

        # Run coder with consistent project config
        coder_context = {
            **base_context,
            "input_data": solution_result["result_data"],
            "project": workflow_config['project']  # Pass config directly
        }
        logger.debug("workflow.coder_context", 
                   workflow_id=workflow_id, 
                   context_keys=list(coder_context.keys()))
                    
        coder_result = run_agent_task(
            agent_config=coder_config,
            context=coder_context
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
        ctx = get_run_context()
        if ctx is not None and hasattr(ctx, "flow_run") and ctx.flow_run and hasattr(ctx.flow_run, "id"):
            workflow_id = str(ctx.flow_run.id)
        else:
            workflow_id = "unknown"
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