"""
Local implementation of intent service using direct agent orchestration.
Path: c4h_services/src/intent/impl/local/service.py
"""

from typing import Dict, Any, Optional
from pathlib import Path
import structlog
from datetime import datetime
import uuid

from c4h_agents.config import load_config, load_with_app_config
from c4h_agents.agents.discovery import DiscoveryAgent
from c4h_agents.agents.solution_designer import SolutionDesigner
from c4h_agents.agents.coder import Coder
from c4h_agents.agents.assurance import AssuranceAgent
from c4h_agents.models.workflow_state import WorkflowState

logger = structlog.get_logger()

class LocalIntentService:
    """
    Simple implementation using direct agent orchestration.
    Maintains compatibility with existing code while providing service interface.
    """
    
    def __init__(self, config_path: Optional[Path] = None):
        """Initialize service with configuration"""
        try:
            # Load config using existing patterns
            system_path = Path("config/system_config.yml")
            if config_path:
                self.config = load_with_app_config(system_path, config_path)
            else:
                self.config = load_config(system_path)
                
            # Track running workflows
            self._workflows: Dict[str, WorkflowState] = {}
            
            logger.info("local_service.initialized",
                       config_path=str(config_path) if config_path else None)
            
        except Exception as e:
            logger.error("local_service.init_failed", error=str(e))
            raise

    def process_intent(
        self,
        project_path: Path,
        intent_desc: Dict[str, Any],
        max_iterations: int = 3
    ) -> Dict[str, Any]:
        """Process refactoring intent through direct agent orchestration"""
        try:
            # Generate workflow ID
            intent_id = str(uuid.uuid4())
            
            # Initialize workflow state
            workflow_state = WorkflowState(
                intent_description=intent_desc,
                project_path=str(project_path),
                max_iterations=max_iterations
            )
            
            self._workflows[intent_id] = workflow_state
            
            # Execute discovery
            discovery = DiscoveryAgent(config=self.config)
            discovery_result = discovery.process({
                "project_path": str(project_path)
            })
            
            if not discovery_result.success:
                return self._handle_error(intent_id, "Discovery failed", discovery_result.error)
                
            workflow_state.update_agent_state("discovery", discovery_result)
            
            # Execute solution design
            solution = SolutionDesigner(config=self.config)
            solution_result = solution.process({
                "input_data": {
                    "discovery_data": discovery_result.data,
                    "intent": intent_desc
                },
                "iteration": workflow_state.iteration
            })
            
            if not solution_result.success:
                return self._handle_error(intent_id, "Solution design failed", solution_result.error)
                
            workflow_state.update_agent_state("solution_design", solution_result)
            
            # Execute code changes
            coder = Coder(config=self.config)
            coder_result = coder.process({
                "input_data": solution_result.data
            })
            
            if not coder_result.success:
                return self._handle_error(intent_id, "Code changes failed", coder_result.error)
                
            workflow_state.update_agent_state("coder", coder_result)
            
            # Execute assurance
            assurance = AssuranceAgent(config=self.config)
            assurance_result = assurance.process({
                "changes": coder_result.data.get("changes", []),
                "intent": intent_desc
            })
            
            workflow_state.update_agent_state("assurance", assurance_result)
            
            return {
                "status": "success",
                "intent_id": intent_id,
                "workflow_data": workflow_state.to_dict(),
                "error": None
            }

        except Exception as e:
            return self._handle_error(intent_id, "Workflow failed", str(e))

    def get_status(self, intent_id: str) -> Dict[str, Any]:
        """Get status of workflow by ID"""
        workflow = self._workflows.get(intent_id)
        if not workflow:
            return {
                "status": "error",
                "error": f"No workflow found with ID: {intent_id}"
            }
        return {
            "status": "success",
            "workflow_data": workflow.to_dict()
        }

    def cancel_intent(self, intent_id: str) -> bool:
        """Cancel a running workflow"""
        if intent_id in self._workflows:
            del self._workflows[intent_id]
            return True
        return False
        
    def _handle_error(self, intent_id: str, message: str, error: str) -> Dict[str, Any]:
        """Handle workflow error with proper logging"""
        logger.error("workflow.error",
                    intent_id=intent_id,
                    message=message,
                    error=error)
        workflow = self._workflows.get(intent_id)
        return {
            "status": "error",
            "intent_id": intent_id,
            "error": f"{message}: {error}",
            "workflow_data": workflow.to_dict() if workflow else {}
        }