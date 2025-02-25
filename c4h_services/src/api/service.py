from fastapi import FastAPI, HTTPException
from pydantic import BaseModel
from typing import Dict, Any, Optional

from c4h_agents.config import deep_merge
from c4h_agents.core.project import Project
from c4h_services.src.api.models import WorkflowRequest, WorkflowResponse

app = FastAPI(
    title="C4H Workflow Service",
    description="API for executing C4H workflows",
    version="0.1.0"
)

# In-memory storage for workflow results (for demonstration purposes)
workflow_storage: Dict[str, Dict[str, Any]] = {}

@app.post("/api/v1/workflow", response_model=WorkflowResponse)
async def run_workflow(request: WorkflowRequest):
    try:
        # Merge system and app config if provided
        system_config = request.system_config
        app_config = request.app_config or {}
        config = deep_merge(system_config, app_config)

        # Initialize project using provided project path
        project = Project(path=request.project_path, config=config)

        # Execute workflow logic: Placeholder for actual workflow execution
        workflow_id = "wf_" + project.id
        # Here you would call the actual workflow runner, e.g., run_flow(...)
        workflow_storage[workflow_id] = {
            "status": "success",
            "stages": {},
            "storage_path": None
        }

        return WorkflowResponse(workflow_id=workflow_id, status="success", storage_path=None)
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.get("/api/v1/workflow/{workflow_id}", response_model=WorkflowResponse)
async def get_workflow(workflow_id: str):
    if workflow_id in workflow_storage:
        data = workflow_storage[workflow_id]
        return WorkflowResponse(workflow_id=workflow_id, status=data.get("status", "unknown"), storage_path=data.get("storage_path"))
    else:
        raise HTTPException(status_code=404, detail="Workflow not found")