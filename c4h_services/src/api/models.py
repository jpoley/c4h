from pydantic import BaseModel
from typing import Dict, Any, Optional, List

class WorkflowRequest(BaseModel):
    system_config: Dict[str, Any]
    app_config: Optional[Dict[str, Any]] = None
    project_path: str
    intent: Dict[str, Any]

class WorkflowResponse(BaseModel):
    workflow_id: str
    status: str
    storage_path: Optional[str] = None

class WorkflowDetail(BaseModel):
    status: str
    stages: Dict[str, Any]
    events: List[Dict[str, Any]]
    storage_path: Optional[str] = None