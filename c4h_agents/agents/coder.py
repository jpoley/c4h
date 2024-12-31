"""
Primary coder agent implementation using semantic extraction.
Path: src/agents/coder.py
"""

from typing import Dict, Any, List, Optional
from dataclasses import dataclass
import structlog
from datetime import datetime
from pathlib import Path
import json
from agents.base import BaseAgent, AgentResponse
from skills.semantic_merge import SemanticMerge
from skills.semantic_iterator import SemanticIterator
from skills.asset_manager import AssetManager, AssetResult
from skills.shared.types import ExtractConfig
from config import locate_config

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
        
        # Get coder-specific config using locate_config pattern
        coder_config = locate_config(self.config or {}, self._get_agent_name())
        
        # Initialize backup location from config
        backup_path = Path(coder_config.get('backup', {}).get('path', 'workspaces/backups'))
        
        # Create semantic tools with same config inheritance
        self.iterator = SemanticIterator(config=config)
        self.merger = SemanticMerge(config=config)
        
        # Setup asset management with inherited config
        self.asset_manager = AssetManager(
            backup_enabled=coder_config.get('backup_enabled', True),
            backup_dir=backup_path,
            merger=self.merger,
            config=config
        )
        
        # Initialize metrics
        self.operation_metrics = CoderMetrics()
        
        logger.info("coder.initialized",
                   backup_path=str(backup_path))

    def _get_agent_name(self) -> str:
        return "coder"

    def process(self, context: Dict[str, Any]) -> AgentResponse:
        """Process code changes using semantic extraction"""
        logger.info("coder.process_start", context_keys=list(context.keys()))
        logger.debug("coder.input_data", data=context.get('input_data'))

        try:
            # Parse input - could be string or dict
            if isinstance(context.get('input_data'), str):
                data = json.loads(context['input_data'])
            else:
                data = context.get('input_data', {})
                
            # Get the array of changes
            changes = data.get('changes', [])
            logger.debug("coder.processing_changes", count=len(changes))
            
            # Track results
            results = []
            
            # Process each change in the array
            for change in changes:
                logger.debug("coder.processing_change", change=change)
                result = self.asset_manager.process_action(change)
                
                if result.success:
                    logger.info("coder.change_applied",
                            file=str(result.path))
                else:
                    logger.error("coder.change_failed", 
                            file=str(result.path),
                            error=result.error)
                
                results.append(result)

            success = bool(results) and any(r.success for r in results)
            
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
                },
                error=None if success else "No changes were successful"
            )

        except Exception as e:
            logger.error("coder.process_failed", error=str(e))
            return AgentResponse(success=False, data={}, error=str(e))