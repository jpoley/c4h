"""
API request and response models for workflow service.
Path: c4h_services/src/api/models.py
"""

from pydantic import BaseModel, Field
from typing import Dict, Any, Optional, List

class WorkflowRequest(BaseModel):
    """
    Request model for workflow execution.
    Contains all necessary configuration for the workflow to run.
    """
    project_path: str = Field(..., description="Path to the project to be processed")
    intent: Dict[str, Any] = Field(..., description="Intent description for the workflow")
    system_config: Optional[Dict[str, Any]] = Field(default=None, description="Base system configuration")
    app_config: Optional[Dict[str, Any]] = Field(default=None, description="Application-specific configuration overrides")

class WorkflowResponse(BaseModel):
    """
    Response model for workflow operations.
    Provides workflow ID and status information.
    """
    workflow_id: str = Field(..., description="Unique identifier for the workflow")
    status: str = Field(..., description="Current status of the workflow")
    storage_path: Optional[str] = Field(default=None, description="Path to stored results if available")
    error: Optional[str] = Field(default=None, description="Error message if status is 'error'")

class WorkflowDetail(BaseModel):
    """
    Detailed workflow information model.
    Used for returning complete workflow execution details.
    """
    status: str = Field(..., description="Current status of the workflow")
    stages: Dict[str, Any] = Field(default_factory=dict, description="Results from each workflow stage")
    changes: List[Dict[str, Any]] = Field(default_factory=list, description="List of changes made by the workflow")
    events: List[Dict[str, Any]] = Field(default_factory=list, description="Execution events in chronological order")
    storage_path: Optional[str] = Field(default=None, description="Path to stored results if available")
    error: Optional[str] = Field(default=None, description="Error message if status is 'error'")
    execution_metadata: Optional[Dict[str, Any]] = Field(default=None, description="Execution metadata and tracking info")