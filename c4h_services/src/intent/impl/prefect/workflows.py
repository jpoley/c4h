"""
Path: c4h_services/src/intent/impl/prefect/workflows.py
Compatibility layer redirecting to team-based orchestration.
"""

from prefect import flow, get_run_logger
from prefect.context import get_run_context
from typing import Dict, Any, Optional
import structlog
from pathlib import Path

from c4h_services.src.orchestration.orchestrator import Orchestrator
from c4h_services.src.intent.impl.prefect.flows import run_intent_workflow

logger = structlog.get_logger()

def prepare_workflow_config(base_config: Dict[str, Any]) -> Dict[str, Any]:
    """
    Prepare workflow configuration with proper run ID and context.
    Now redirects to team-based orchestration.
    """
    # This is now a compatibility function that delegates to the 
    # orchestration module for config preparation
    orchestrator = Orchestrator(base_config)
    return orchestrator.prepare_config()

@flow(name="basic_refactoring")
def run_basic_workflow(
    project_path: Path,
    intent_desc: Dict[str, Any],
    config: Dict[str, Any]
) -> Dict[str, Any]:
    """
    Legacy compatibility wrapper redirecting to team-based workflow.
    Uses the new run_intent_workflow with team orchestration.
    """
    logger.warning("workflows.using_legacy_interface", 
                 message="Using deprecated workflow interface - please migrate to team-based orchestration")
    
    # Redirect to the new team-based workflow
    return run_intent_workflow(
        project_path=project_path,
        intent_desc=intent_desc,
        config=config
    )