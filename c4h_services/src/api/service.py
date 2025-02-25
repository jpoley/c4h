"""
API service implementation supporting config-less startup and full API configuration.
Path: c4h_services/src/api/service.py
"""

from fastapi import FastAPI, HTTPException, Depends
from pydantic import BaseModel
from typing import Dict, Any, Optional, Callable
import structlog
from pathlib import Path
import uuid
import os

from c4h_agents.config import deep_merge
from c4h_agents.core.project import Project
from c4h_services.src.api.models import WorkflowRequest, WorkflowResponse
from c4h_services.src.intent.impl.prefect.workflows import run_basic_workflow

logger = structlog.get_logger()

# In-memory storage for workflow results (for demonstration purposes)
# In production, this would be a database or persistent storage
workflow_storage: Dict[str, Dict[str, Any]] = {}

def create_app(default_config: Dict[str, Any] = None) -> FastAPI:
    """
    Create FastAPI application with optional default configuration.
    
    Args:
        default_config: Optional base configuration for the service
        
    Returns:
        Configured FastAPI application
    """
    app = FastAPI(
        title="C4H Workflow Service",
        description="API for executing C4H workflows",
        version="0.1.0"
    )
    
    # Store default config in app state
    app.state.default_config = default_config or {}
    
    # Register routes
    @app.post("/api/v1/workflow", response_model=WorkflowResponse)
    async def run_workflow(request: WorkflowRequest):
        """
        Execute a workflow with the provided configuration.
        Configuration from the request is merged with the default configuration.
        """
        try:
            # Merge default config with request configs
            config = deep_merge(app.state.default_config, request.system_config or {})
            if request.app_config:
                config = deep_merge(config, request.app_config)
            
            # Generate workflow ID
            workflow_id = f"wf_{uuid.uuid4()}"
            
            # Add workflow ID to config for lineage tracking
            if 'system' not in config:
                config['system'] = {}
            config['system']['runid'] = workflow_id
            config['workflow_run_id'] = workflow_id
            
            # Set project path in config
            if 'project' not in config:
                config['project'] = {}
            config['project']['path'] = request.project_path
            
            # Store intent in config
            config['intent'] = request.intent
            
            # Log workflow start
            logger.info("workflow.starting", 
                        workflow_id=workflow_id, 
                        project_path=request.project_path,
                        config_keys=list(config.keys()))
            
            # Execute workflow (we'll use Prefect's run_basic_workflow)
            # In a production environment, this would be an async task
            try:
                result = run_basic_workflow(
                    project_path=Path(request.project_path),
                    intent_desc=request.intent,
                    config=config
                )
                
                # Store result
                workflow_storage[workflow_id] = {
                    "status": "success",
                    "stages": result.get("stages", {}),
                    "changes": result.get("changes", []),
                    "storage_path": os.path.join("workspaces", "lineage", workflow_id) if config.get("lineage", {}).get("enabled", False) else None
                }
                
                return WorkflowResponse(
                    workflow_id=workflow_id,
                    status="success",
                    storage_path=workflow_storage[workflow_id].get("storage_path")
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
        return {"status": "healthy", "workflows_tracked": len(workflow_storage)}
            
    return app

# Default app instance for direct imports
app = create_app()