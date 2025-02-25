"""
Path: c4h_services/src/intent/impl/prefect/workflows.py
Core workflow implementation with enhanced lineage tracking.
"""

from prefect import flow, get_run_logger
from prefect.context import get_run_context
from typing import Dict, Any, Optional, List
import structlog
from pathlib import Path
from datetime import datetime, timezone
from copy import deepcopy
import uuid

from c4h_agents.config import create_config_node
from c4h_agents.agents.lineage_context import LineageContext
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
        
        # Set lineage tracking configuration
        if 'llm_config' not in config:
            config['llm_config'] = {}
        
        if 'agents' not in config['llm_config']:
            config['llm_config']['agents'] = {}
            
        if 'lineage' not in config['llm_config']['agents']:
            config['llm_config']['agents']['lineage'] = {}
            
        # Ensure lineage is enabled
        config['llm_config']['agents']['lineage'].update({
            'enabled': True,
            'namespace': 'c4h_agents',
            'event_detail_level': 'full',  # full, standard, or minimal
            'separate_input_output': False, # Set to True for large payloads
            'backend': {
                'type': 'file',
                'path': 'workspaces/lineage'
            }
        })
        
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
        
        # Create a workflow context with proper lineage tracking
        workflow_context = LineageContext.create_workflow_context(workflow_id)
        
        # Set step sequence for visualization and tracking
        step_sequence = 0
        
        # Run discovery with proper lineage tracking context
        step_sequence += 1
        discovery_context = LineageContext.create_agent_context(
            workflow_run_id=workflow_id,
            agent_type="discovery",
            step=step_sequence,
            base_context={
                "project_path": str(project_path),
                "project": workflow_config['project']
            }
        )
        
        logger.debug("workflow.discovery_context", 
                   workflow_id=workflow_id, 
                   agent_execution_id=discovery_context.get("agent_execution_id"),
                   step=step_sequence,
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
                "project_path": str(project_path),
                "execution_metadata": {
                    "agent_execution_id": discovery_context.get("agent_execution_id"),
                    "step": step_sequence,
                    "timestamp": datetime.now(timezone.utc).isoformat()
                }
            }

        # Extract discovery execution metadata
        discovery_metadata = discovery_result.get("result_data", {}).get("execution_metadata", {})
        discovery_agent_id = discovery_metadata.get("agent_execution_id")

        # Run solution design with proper lineage tracking
        step_sequence += 1
        solution_context = LineageContext.create_agent_context(
            workflow_run_id=workflow_id,
            agent_type="solution_designer",
            step=step_sequence,
            base_context={
                "input_data": {
                    "discovery_data": discovery_result["result_data"],
                    "intent": intent_desc,
                    "project": workflow_config['project']
                }
            }
        )
        
        logger.debug("workflow.solution_context", 
                   workflow_id=workflow_id,
                   agent_execution_id=solution_context.get("agent_execution_id"),
                   step=step_sequence,
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
                "discovery_data": discovery_result.get("result_data"),
                "execution_metadata": {
                    "agent_execution_id": solution_context.get("agent_execution_id"),
                    "step": step_sequence,
                    "previous_step": discovery_agent_id,
                    "timestamp": datetime.now(timezone.utc).isoformat()
                }
            }

        # Extract solution execution metadata
        solution_metadata = solution_result.get("result_data", {}).get("execution_metadata", {})
        solution_agent_id = solution_metadata.get("agent_execution_id")

        # Run coder with proper lineage tracking
        step_sequence += 1
        coder_context = LineageContext.create_agent_context(
            workflow_run_id=workflow_id,
            agent_type="coder",
            step=step_sequence,
            base_context={
                "input_data": solution_result["result_data"],
                "project": workflow_config['project']
            }
        )
        
        logger.debug("workflow.coder_context", 
                   workflow_id=workflow_id,
                   agent_execution_id=coder_context.get("agent_execution_id"),
                   step=step_sequence,
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
                "solution_data": solution_result.get("result_data"),
                "execution_metadata": {
                    "agent_execution_id": coder_context.get("agent_execution_id"),
                    "step": step_sequence,
                    "previous_step": solution_agent_id,
                    "timestamp": datetime.now(timezone.utc).isoformat()
                }
            }

        # Extract coder execution metadata
        coder_metadata = coder_result.get("result_data", {}).get("execution_metadata", {})
        coder_agent_id = coder_metadata.get("agent_execution_id")

        # Return workflow result with comprehensive lineage context
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
            },
            "execution_metadata": {
                "workflow_run_id": workflow_id,
                "step_sequence": step_sequence,
                "agent_sequence": [
                    {"agent": "discovery", "id": discovery_agent_id, "step": 1},
                    {"agent": "solution_designer", "id": solution_agent_id, "step": 2},
                    {"agent": "coder", "id": coder_agent_id, "step": 3}
                ],
                "execution_path": LineageContext.extract_lineage_info(coder_context).get("execution_path", [])
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
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "execution_metadata": {
                "error": error_msg,
                "error_type": type(e).__name__,
                "workflow_run_id": workflow_id,
                "timestamp": datetime.now(timezone.utc).isoformat()
            }
        }