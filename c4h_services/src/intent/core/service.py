"""
Core service interface for intent-based refactoring.
Path: c4h_services/src/intent/core/service.py
"""

from typing import Dict, Any, Protocol, runtime_checkable
from pathlib import Path
import structlog

logger = structlog.get_logger()

@runtime_checkable
class IntentService(Protocol):
    """
    Protocol defining the interface for intent-based refactoring services.
    Implementations must provide this standard interface regardless of backend.
    """
    
    def process_intent(
        self,
        project_path: Path,
        intent_desc: Dict[str, Any],
        max_iterations: int = 3
    ) -> Dict[str, Any]:
        """
        Process a refactoring intent for the given project.
        
        Args:
            project_path: Path to the project to refactor
            intent_desc: Description of intended changes
            max_iterations: Maximum number of refinement iterations
            
        Returns:
            Dict containing:
            - status: "success" or "error"
            - workflow_data: Complete workflow state
            - error: Error message if failed
        """
        ...

    def get_status(self, intent_id: str) -> Dict[str, Any]:
        """
        Get current status of an intent workflow.
        
        Args:
            intent_id: Unique identifier of the workflow
            
        Returns:
            Current workflow status and state
        """
        ...

    def cancel_intent(self, intent_id: str) -> bool:
        """
        Cancel a running intent workflow.
        
        Args:
            intent_id: Unique identifier of the workflow to cancel
            
        Returns:
            True if cancelled successfully
        """
        ...