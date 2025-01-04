"""
Primary coder agent implementation using semantic extraction.
Path: c4h_agents/agents/coder.py
"""
from typing import Dict, Any, List, Optional
from dataclasses import dataclass
import structlog
from datetime import datetime, timezone
from pathlib import Path
from agents.base import BaseAgent, AgentResponse, LogDetail
from skills.semantic_merge import SemanticMerge
from skills.semantic_iterator import SemanticIterator
from skills.asset_manager import AssetManager, AssetResult
from skills.shared.types import ExtractConfig

logger = structlog.get_logger()

@dataclass 
class CoderMetrics:
    """Detailed metrics for code processing operations"""
    total_changes: int = 0
    successful_changes: int = 0
    failed_changes: int = 0
    start_time: str = ""
    end_time: str = ""
    processing_time: float = 0.0
    error_count: int = 0

class Coder(BaseAgent):
    """Handles code modifications using semantic processing"""
    
    def __init__(self, config: Dict[str, Any] = None):
        """Initialize coder with configuration"""
        super().__init__(config=config)
        
        # Get coder-specific config 
        coder_config = self._get_agent_config()
        
        # Initialize backup location
        backup_path = Path(coder_config.get('backup', {}).get('path', 'workspaces/backups'))
        
        # Create semantic tools
        self.iterator = SemanticIterator(config=config)
        self.merger = SemanticMerge(config=config)
        
        # Setup asset management
        self.asset_manager = AssetManager(
            backup_enabled=coder_config.get('backup_enabled', True),
            backup_dir=backup_path,
            merger=self.merger,
            config=config
        )
        
        # Initialize metrics
        self.operation_metrics = CoderMetrics()
        
        logger.info("coder.initialized", backup_path=str(backup_path))

    def _get_required_keys(self) -> List[str]:
        """Define keys required by coder agent."""
        return ['input_data']  # Only need the raw input

    def process(self, context: Dict[str, Any]) -> AgentResponse:
        """Process code changes using semantic extraction"""
        logger.info("coder.process_start", context_keys=list(context.keys()))
        logger.debug("coder.input_data", data=context)

        try:
            # Get raw input data
            data = self._get_data(context)
            input_data = data.get('input_data', {})
            
            # Configure iterator to find repeating blocks
            self.iterator.configure(
                content=input_data.get('response', ''),
                config=ExtractConfig(
                    instruction="Extract each code change object",
                    format="json"  # Semantic Iterator will handle the JSON parsing
                )
            )

            # Track results
            results = []
            
            # Let iterator find and process each change
            for change in self.iterator:
                logger.debug("coder.processing_change", change=change)
                result = self.asset_manager.process_action(change)
                
                if result.success:
                    logger.info("coder.change_applied",
                            file=str(result.path))
                    self.operation_metrics.successful_changes += 1
                else:
                    logger.error("coder.change_failed", 
                            file=str(result.path),
                            error=result.error)
                    self.operation_metrics.failed_changes += 1
                    self.operation_metrics.error_count += 1
                
                self.operation_metrics.total_changes += 1
                results.append(result)

            success = bool(results) and any(r.success for r in results)
            
            # Update final metrics
            self.operation_metrics.end_time = datetime.now(timezone.utc).isoformat()
            if self._should_log(LogDetail.DETAILED):
                logger.info("coder.metrics_final",
                          metrics=vars(self.operation_metrics))
                
            return AgentResponse(
                success=success,
                data={
                    "changes": [
                        {
                            "file": str(r.path),
                            "success": r.success,
                            "error": r.error,
                            "backup": str(r.backup_path) if r.backup_path else None
                        }
                        for r in results
                    ],
                    "metrics": vars(self.operation_metrics)
                },
                error=None if success else "No changes were successful"
            )

        except Exception as e:
            logger.error("coder.process_failed", error=str(e))
            self.operation_metrics.error_count += 1
            return AgentResponse(success=False, data={}, error=str(e))