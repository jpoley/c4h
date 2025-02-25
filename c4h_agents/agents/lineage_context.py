"""
Lineage context management for agent coordination.
Path: c4h_agents/agents/lineage_context.py
"""

from typing import Dict, Any, Optional, List
import uuid
import structlog
from copy import deepcopy
from datetime import datetime, timezone
import json

logger = structlog.get_logger()

class LineageContext:
    """
    Utility class for managing execution context with lineage tracking.
    Provides methods to create properly structured contexts for agent and skill calls.
    """
    
    @staticmethod
    def create_workflow_context(workflow_run_id: str, base_context: Dict[str, Any] = None) -> Dict[str, Any]:
        """
        Create a base workflow context with appropriate lineage IDs.
        
        Args:
            workflow_run_id: The workflow run ID
            base_context: Optional base context to extend
            
        Returns:
            Context dictionary with workflow tracking IDs
        """
        context = deepcopy(base_context) if base_context else {}
        
        # Set workflow run ID as the overarching execution ID
        context["workflow_run_id"] = workflow_run_id
        
        # Add to system namespace for compatibility
        if "system" not in context:
            context["system"] = {}
        context["system"]["runid"] = workflow_run_id
        
        # Add tracking metadata
        context["lineage_metadata"] = {
            "workflow_run_id": workflow_run_id,
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "execution_path": []
        }
        
        return context
    
    @staticmethod
    def create_agent_context(workflow_run_id: str, agent_type: str, parent_id: Optional[str] = None, 
                           base_context: Dict[str, Any] = None, step: Optional[int] = None) -> Dict[str, Any]:
        """
        Create a context for an agent execution with lineage tracking.
        
        Args:
            workflow_run_id: The workflow run ID
            agent_type: Type of agent (e.g., "discovery", "solution_designer")
            parent_id: Optional parent execution ID
            base_context: Optional base context to extend
            step: Optional step/sequence number
            
        Returns:
            Context dictionary with agent tracking IDs
        """
        context = deepcopy(base_context) if base_context else {}
        
        # Generate unique execution ID for this agent
        agent_execution_id = str(uuid.uuid4())
        
        # Set workflow and agent IDs
        context["workflow_run_id"] = workflow_run_id
        context["agent_execution_id"] = agent_execution_id
        
        # Set parent relationship
        if parent_id:
            context["parent_id"] = parent_id
        
        # Set agent type and step if provided
        if step is not None:
            context["step"] = step
        
        # Get or create lineage metadata
        if "lineage_metadata" not in context:
            context["lineage_metadata"] = {
                "workflow_run_id": workflow_run_id,
                "timestamp": datetime.now(timezone.utc).isoformat(),
                "execution_path": []
            }
        
        # Update execution path
        if "execution_path" in context["lineage_metadata"]:
            # Copy to avoid mutating the original
            path = list(context["lineage_metadata"]["execution_path"])
        else:
            path = []
            
        # Add this agent to the path
        path.append(f"{agent_type}:{agent_execution_id[:8]}")
        context["lineage_metadata"]["execution_path"] = path
        
        # Add to system namespace for compatibility
        if "system" not in context:
            context["system"] = {}
        context["system"]["runid"] = workflow_run_id
        context["system"]["agent_id"] = agent_execution_id
        
        return context
    
    @staticmethod
    def create_skill_context(agent_id: str, skill_type: str, workflow_run_id: Optional[str] = None,
                           base_context: Dict[str, Any] = None) -> Dict[str, Any]:
        """
        Create a context for a skill execution with proper lineage tracking.
        
        Args:
            agent_id: ID of the agent calling this skill
            skill_type: Type of skill (e.g., "semantic_extract", "semantic_merge")
            workflow_run_id: Optional workflow run ID (will extract from base_context if not provided)
            base_context: Optional base context to extend
            
        Returns:
            Context dictionary with skill tracking IDs
        """
        context = deepcopy(base_context) if base_context else {}
        
        # Generate unique execution ID for this skill
        skill_execution_id = str(uuid.uuid4())
        
        # Extract workflow run ID from base context if not provided
        if not workflow_run_id and base_context:
            workflow_run_id = base_context.get("workflow_run_id")
            if not workflow_run_id and "system" in base_context:
                workflow_run_id = base_context["system"].get("runid")
        
        # Set parent relationship - always use the calling agent as parent
        context["parent_id"] = agent_id
        
        # Set skill identifiers
        context["agent_execution_id"] = skill_execution_id
        context["skill_type"] = skill_type
        
        # Preserve workflow run ID
        if workflow_run_id:
            context["workflow_run_id"] = workflow_run_id
            
            # Add to system namespace for compatibility
            if "system" not in context:
                context["system"] = {}
            context["system"]["runid"] = workflow_run_id
        
        # Get or create lineage metadata
        if "lineage_metadata" not in context:
            context["lineage_metadata"] = {
                "workflow_run_id": workflow_run_id,
                "timestamp": datetime.now(timezone.utc).isoformat(),
                "execution_path": []
            }
            
        # Update execution path
        if "execution_path" in context["lineage_metadata"]:
            # Copy to avoid mutating the original
            path = list(context["lineage_metadata"]["execution_path"])
        else:
            path = []
            
        # Add this skill to the path
        path.append(f"{skill_type}:{skill_execution_id[:8]}")
        context["lineage_metadata"]["execution_path"] = path
        
        return context
    
    @staticmethod
    def extract_lineage_info(context: Dict[str, Any]) -> Dict[str, Any]:
        """
        Extract lineage tracking information from a context.
        
        Args:
            context: Context dictionary
            
        Returns:
            Dictionary with extracted lineage information
        """
        # Default empty values
        lineage_info = {
            "agent_execution_id": None,
            "parent_id": None, 
            "workflow_run_id": None,
            "execution_path": [],
            "step": None,
            "agent_type": None,
            "skill_type": None
        }
        
        # Extract direct keys
        for key in lineage_info.keys():
            if key in context:
                lineage_info[key] = context[key]
        
        # Extract from lineage_metadata if available
        if "lineage_metadata" in context:
            metadata = context["lineage_metadata"]
            for key in ["workflow_run_id", "execution_path", "step"]:
                if key in metadata and lineage_info[key] is None:
                    lineage_info[key] = metadata[key]
        
        # Extract from system namespace as fallback
        if "system" in context:
            system = context["system"]
            if lineage_info["workflow_run_id"] is None and "runid" in system:
                lineage_info["workflow_run_id"] = system["runid"]
            if lineage_info["agent_execution_id"] is None and "agent_id" in system:
                lineage_info["agent_execution_id"] = system["agent_id"]
        
        return lineage_info