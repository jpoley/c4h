"""
Lineage processing utilities for workflow continuation.
Path: c4h_services/src/utils/lineage_utils.py
"""

from typing import Dict, Any
from pathlib import Path
import json
from datetime import datetime, timezone
from c4h_services.src.utils.logging import get_logger

logger = get_logger()

def load_lineage_file(lineage_file_path: str) -> Dict[str, Any]:
    """
    Load and parse a lineage file to extract content for workflow continuation.
    
    Args:
        lineage_file_path: Path to the lineage file
        
    Returns:
        Parsed lineage event data
    """
    try:
        lineage_path = Path(lineage_file_path)
        if not lineage_path.exists():
            raise FileNotFoundError(f"Lineage file not found: {lineage_file_path}")
            
        with open(lineage_path, 'r') as f:
            lineage_data = json.load(f)
            
        logger.info("lineage.file_loaded", 
                   path=str(lineage_path),
                   agent=lineage_data.get("agent", {}).get("name"),
                   workflow_id=lineage_data.get("workflow", {}).get("run_id"))
                   
        return lineage_data
    except json.JSONDecodeError as e:
        logger.error("lineage.parse_failed", 
                   error=str(e),
                   path=str(lineage_file_path))
        raise ValueError(f"Invalid JSON in lineage file: {e}")
    except Exception as e:
        logger.error("lineage.load_failed", 
                   error=str(e),
                   path=str(lineage_file_path))
        raise

def prepare_context_from_lineage(lineage_data: Dict[str, Any], stage: str, config: Dict[str, Any]) -> Dict[str, Any]:
    """
    Prepare workflow context from lineage data for the specified stage.
    
    Args:
        lineage_data: Parsed lineage event data
        stage: Target stage to execute
        config: Configuration dictionary
        
    Returns:
        Context dictionary for the specified stage
    """
    try:
        # Extract workflow ID
        workflow_run_id = lineage_data.get("workflow", {}).get("run_id")
        if not workflow_run_id:
            raise ValueError("No workflow run ID found in lineage data")
            
        # Extract agent info
        agent_name = lineage_data.get("agent", {}).get("name")
        if not agent_name:
            raise ValueError("No agent name found in lineage data")
            
        # Extract input context from lineage
        if "llm_input" not in lineage_data:
            raise ValueError("No LLM input found in lineage data")
            
        # Extract output from lineage
        if "llm_output" not in lineage_data:
            raise ValueError("No LLM output found in lineage data")
            
        # Initialize base context
        context = {
            "workflow_run_id": workflow_run_id,
            "system": {"runid": workflow_run_id},
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "config": config,
            "lineage_source": {
                "agent": agent_name,
                "event_id": lineage_data.get("event_id")
            }
        }
        
        # Add project path if available
        project_path = config.get("project", {}).get("path")
        if project_path:
            context["project_path"] = project_path
            context["project"] = config.get("project", {})
        
        # Add agent-specific context based on stage
        if stage == "solution_designer" and agent_name == "discovery":
            # From discovery to solution_designer
            context["input_data"] = {
                "discovery_data": {
                    "response": lineage_data.get("llm_output"),
                    "raw_output": lineage_data.get("llm_output")
                },
                "intent": config.get("intent", {})
            }
        elif stage == "coder" and agent_name == "solution_designer":
            # From solution_designer to coder
            context["input_data"] = {
                "response": lineage_data.get("llm_output"),
                "raw_output": lineage_data.get("llm_output")
            }
        else:
            # Generic fallback
            context["input_data"] = {
                "response": lineage_data.get("llm_output"),
                "raw_output": lineage_data.get("llm_output"),
                "intent": config.get("intent", {})
            }
            
        logger.info("context.prepared_from_lineage",
                   workflow_id=workflow_run_id,
                   source_agent=agent_name,
                   target_stage=stage,
                   context_keys=list(context.keys()))
                   
        return context
        
    except Exception as e:
        logger.error("context.preparation_failed", error=str(e))
        raise

def run_workflow_from_lineage(orchestrator, lineage_file_path: str, stage: str, config: Dict[str, Any]) -> Dict[str, Any]:
    """
    Run a workflow stage using a lineage file as input.
    
    Args:
        orchestrator: Orchestrator instance to execute the workflow
        lineage_file_path: Path to the lineage file
        stage: Target stage to execute
        config: Configuration dictionary
        
    Returns:
        Workflow result
    """
    try:
        # Load lineage file
        lineage_data = load_lineage_file(lineage_file_path)
        
        # Prepare context from lineage
        context = prepare_context_from_lineage(lineage_data, stage, config)
        
        # Execute workflow starting from specified stage
        result = orchestrator.execute_workflow(
            entry_team=stage,
            context=context
        )
        
        logger.info("workflow.completed_from_lineage",
                   workflow_id=result.get("workflow_run_id", "unknown"),
                   status=result.get("status", "unknown"),
                   stage=stage)
                 
        return result
    except Exception as e:
        error_msg = str(e)
        logger.error("workflow.from_lineage_failed", error=error_msg)
        return {
            "status": "error",
            "error": error_msg,
            "timestamp": datetime.now(timezone.utc).isoformat()
        }