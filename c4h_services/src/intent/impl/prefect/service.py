"""
Prefect implementation of intent service.
Path: c4h_services/src/intent/impl/prefect/service.py
"""

from typing import Dict, Any, Optional
from pathlib import Path
import structlog
from datetime import datetime
import uuid
from prefect.client import get_client
from prefect.deployments import Deployment

from c4h_agents.config import load_config, load_with_app_config
from .workflows import run_basic_workflow

logger = structlog.get_logger()

class PrefectIntentService:
    """
    Prefect-based implementation of intent service interface.
    Handles workflow orchestration while maintaining agent independence.
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
            
            # Initialize Prefect client for flow operations
            self.client = get_client()
            
            logger.info("prefect_service.initialized",
                       config_path=str(config_path) if config_path else None)
            
        except Exception as e:
            logger.error("prefect_service.init_failed", error=str(e))
            raise

    async def process_intent(
        self,
        project_path: Path,
        intent_desc: Dict[str, Any],
        max_iterations: int = 3
    ) -> Dict[str, Any]:
        """Process refactoring intent through Prefect workflow"""
        try:
            logger.info("prefect_service.processing",
                       project_path=str(project_path),
                       intent=intent_desc)

            # Execute workflow
            flow_run = await self.client.create_flow_run(
                flow=run_basic_workflow,
                parameters={
                    "project_path": project_path,
                    "intent_desc": intent_desc,
                    "config": self.config
                }
            )
            
            # Wait for completion
            flow_state = await self.client.wait_for_flow_run(
                flow_run.id,
                timeout=1800  # 30 minutes
            )

            if flow_state.is_completed():
                result = flow_state.result()
                logger.info("prefect_service.completed",
                          flow_id=flow_run.id,
                          status=result.get("status"))
                return result
            else:
                error = f"Flow failed: {flow_state.message}"
                logger.error("prefect_service.flow_failed",
                           flow_id=flow_run.id,
                           error=error)
                return {
                    "status": "error",
                    "error": error,
                    "workflow_data": {}
                }

        except Exception as e:
            error_msg = str(e)
            logger.error("prefect_service.failed", error=error_msg)
            return {
                "status": "error",
                "error": error_msg,
                "workflow_data": {}
            }

    async def get_status(self, intent_id: str) -> Dict[str, Any]:
        """Get status of a workflow run"""
        try:
            # Get flow run state
            flow_run = await self.client.read_flow_run(intent_id)
            
            return {
                "status": "success",
                "workflow_data": {
                    "flow_id": flow_run.id,
                    "status": flow_run.state.name,
                    "start_time": flow_run.start_time,
                    "end_time": flow_run.end_time,
                    "duration": flow_run.total_run_time,
                    "error": flow_run.state.message if flow_run.state.is_failed() else None
                }
            }
            
        except Exception as e:
            logger.error("status.failed", error=str(e), intent_id=intent_id)
            return {
                "status": "error",
                "error": f"Failed to get status: {str(e)}"
            }

    async def cancel_intent(self, intent_id: str) -> bool:
        """Cancel a running workflow"""
        try:
            await self.client.set_flow_run_state(
                flow_run_id=intent_id,
                state="CANCELLED"
            )
            
            logger.info("intent.cancelled", intent_id=intent_id)
            return True
            
        except Exception as e:
            logger.error("cancel.failed", error=str(e), intent_id=intent_id)
            return False