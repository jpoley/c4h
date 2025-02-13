"""
Asset management with minimal processing and LLM-first design.
Path: c4h_agents/skills/asset_manager.py
"""

from pathlib import Path
from typing import Optional, Dict, Any, Union
from dataclasses import dataclass
import structlog
import shutil
from datetime import datetime

from c4h_agents.agents.base_agent import BaseAgent, AgentResponse 
from c4h_agents.skills.semantic_merge import SemanticMerge

logger = structlog.get_logger()

@dataclass
class AssetResult:
    """Result of an asset operation"""
    success: bool
    path: Path
    backup_path: Optional[Path] = None
    error: Optional[str] = None

class AssetManager(BaseAgent):
    """Manages file operations with simple backup support"""
    
    def __init__(self, config: Dict[str, Any] = None, **kwargs):
        """Initialize with basic config and backup settings"""
        super().__init__(config=config)
        
        # Get project path from config if available
        self.project_path = None
        if isinstance(config, dict) and 'project' in config:
            project_config = config['project']
            if isinstance(project_config, dict):
                self.project_path = Path(project_config.get('path', '.')).resolve()
                workspace_path = Path(project_config.get('workspace_root', 'workspaces'))
                if not workspace_path.is_absolute():
                    workspace_path = self.project_path / workspace_path
                self.backup_dir = workspace_path / "backups"
            else:
                # Handle Project instance
                self.project_path = project_config.paths.root
                self.backup_dir = project_config.paths.workspace / "backups"
        else:
            # Fallback for no project config
            self.backup_dir = Path(kwargs.get('backup_dir', 'workspaces/backups'))

        # Configure backup and create merger
        self.backup_enabled = kwargs.get('backup_enabled', True)
        if self.backup_enabled:
            self.backup_dir.mkdir(parents=True, exist_ok=True)
        
        # Get semantic merger
        self.merger = kwargs.get('merger')
        if not self.merger:
            self.merger = SemanticMerge(config=config)

        logger.info("asset_manager.initialized",
                   backup_enabled=self.backup_enabled,
                   backup_dir=str(self.backup_dir),
                   project_path=str(self.project_path) if self.project_path else None)

    def process_action(self, action: Union[str, Dict[str, Any]]) -> AssetResult:
        """Process single file action focusing on path handling and backup"""
        try:
            # Find file path in action using semantic extractor pattern
            file_path = None
            if isinstance(action, dict):
                # Check common path keys
                for key in ['file_path', 'path', 'file', 'filename']:
                    if key in action and action[key]:
                        file_path = action[key]
                        break
                    
            if not file_path:
                raise ValueError("No file path found in action")

            # Resolve path using project context if available 
            path = Path(file_path)
            if not path.is_absolute() and self.project_path:
                path = (self.project_path / path).resolve()

            # Create backup if needed
            backup_path = None
            if self.backup_enabled and path.exists():
                timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
                backup_path = self.backup_dir / timestamp
                if self.project_path:
                    try:
                        rel_path = path.relative_to(self.project_path)
                        backup_path = backup_path / rel_path
                    except ValueError:
                        backup_path = backup_path / path.name
                else:
                    backup_path = backup_path / path.name
                    
                backup_path.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(path, backup_path)

            # Let merger handle content merging/creation
            merge_result = self.merger.process(action)
            if not merge_result.success:
                return AssetResult(
                    success=False,
                    path=path,
                    error=merge_result.error
                )
                
            content = merge_result.data.get('response')
            if not content:
                return AssetResult(
                    success=False,
                    path=path,
                    error="No content after merge"
                )

            # Write final content
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(content)
            
            return AssetResult(success=True, path=path, backup_path=backup_path)

        except Exception as e:
            logger.error("asset.process_failed", 
                error=str(e),
                path=str(path) if 'path' in locals() else None,  
                project=str(self.project_path) if self.project_path else None
            )
            return AssetResult(
                success=False,
                path=path if 'path' in locals() else Path('.'),
                error=str(e)
            )

    def process(self, context: Dict[str, Any]) -> AgentResponse:
        """Process asset operations with standard agent interface"""
        try:
            result = self.process_action(context)
            return AgentResponse(
                success=result.success,
                data={
                    "path": str(result.path),
                    "backup_path": str(result.backup_path) if result.backup_path else None
                },
                error=result.error
            )
        except Exception as e:
            logger.error("asset_manager.process_failed", error=str(e))
            return AgentResponse(success=False, data={}, error=str(e))