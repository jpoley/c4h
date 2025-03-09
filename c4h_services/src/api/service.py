"""
API service implementation focused exclusively on team-based orchestration.
Path: c4h_services/src/api/service.py
"""

from fastapi import FastAPI, HTTPException, Depends
from pydantic import BaseModel
from typing import Dict, Any, Optional, Callable
from c4h_services.src.utils.logging import get_logger
from pathlib import Path
import uuid
import os

from c4h_agents.config import deep_merge
from c4h_agents.core.project import Project
from c4h_services.src.api.models import WorkflowRequest, WorkflowResponse
from c4h_services.src.orchestration.orchestrator import Orchestrator

logger = get_logger()

# In-memory storage for workflow results (for demonstration purposes)
# In production, this would be a database or persistent storage
workflow_storage: Dict[str, Dict[str, Any]] = {}

def create_app(default_config: Dict[str, Any] = None) -> FastAPI:
    """
    Create FastAPI application with team-based orchestration.
    
    Args:
        default_config: Optional base configuration for the service
        
    Returns:
        Configured FastAPI application
    """
    app = FastAPI(
        title="C4H Workflow Service",
        description="API for executing C4H team-based workflows",
        version="0.2.0"
    )
    
    # Store default config in app state
    app.state.default_config = default_config or {}
    
    # Create orchestrator
    app.state.orchestrator = Orchestrator(app.state.default_config)
    logger.info("api.team_orchestration_initialized", 
               teams=len(app.state.orchestrator.teams))
    
    # Register routes
    @app.post("/api/v1/workflow", response_model=WorkflowResponse)
    async def run_workflow(request: WorkflowRequest):
        """
        Execute a team-based workflow with the provided configuration.
        Configuration from the request is merged with the default configuration.
        """
        try:
            # Merge default config with request configs
            config = deep_merge(app.state.default_config, request.system_config or {})
            if request.app_config:
                config = deep_merge(config, request.app_config)
            
            # Initialize workflow with consistent defaults
            prepared_config, context = app.state.orchestrator.initialize_workflow(
                project_path=request.project_path,
                intent_desc=request.intent,
                config=config
            )
            
            workflow_id = context["workflow_run_id"]
                 
            # Store intent in config
            config['intent'] = request.intent
                 
            # Log workflow start
            logger.info("workflow.starting", 
                        workflow_id=workflow_id, 
                        project_path=request.project_path,
                        config_keys=list(prepared_config.keys()))
             
            # Execute workflow
            try:
                # Get entry team from config or use default
                entry_team = prepared_config.get("orchestration", {}).get("entry_team", "discovery")
                 
                result = app.state.orchestrator.execute_workflow(
                    entry_team=entry_team,
                    context=context
                )
                 
                # Store result
                workflow_storage[workflow_id] = {
                    "status": result.get("status", "error"),
                    "team_results": result.get("team_results", {}),
                    "changes": result.get("data", {}).get("changes", []),
                    "storage_path": os.path.join("workspaces", "lineage", workflow_id) if prepared_config.get("lineage", {}).get("enabled", False) else None
                }
                 
                return WorkflowResponse(
                    workflow_id=workflow_id,
                    status=result.get("status", "error"),
                    storage_path=workflow_storage[workflow_id].get("storage_path"),
                    error=result.get("error") if result.get("status") == "error" else None
                )
                 
            except Exception as e:
                logger.error("workflow.execution_failed", 
                           workflow_id=workflow_id, 
                           error=str(e))
                 
                workflow_storage[workflow_id] = {
                    "status": "error",
                    "error": str(e),
                    "storage_path": None
                }
                 
                return WorkflowResponse(
                    workflow_id=workflow_id,
                    status="error",
                    error=str(e)
                )
                 
        except Exception as e:
            logger.error("workflow.request_failed", error=str(e))
            raise HTTPException(status_code=500, detail=str(e))

    @app.get("/api/v1/workflow/{workflow_id}", response_model=WorkflowResponse)
    async def get_workflow(workflow_id: str):
        """Get workflow status and results"""
        if workflow_id in workflow_storage:
            data = workflow_storage[workflow_id]
            return WorkflowResponse(
                workflow_id=workflow_id, 
                status=data.get("status", "unknown"), 
                storage_path=data.get("storage_path"),
                error=data.get("error")
            )
        else:
            raise HTTPException(status_code=404, detail="Workflow not found")
            
    @app.get("/health")
    async def health_check():
        """Simple health check endpoint"""
        return {
            "status": "healthy", 
            "workflows_tracked": len(workflow_storage),
            "teams_available": len(app.state.orchestrator.teams)
        }
            
    return app

# Default app instance for direct imports
app = create_app()