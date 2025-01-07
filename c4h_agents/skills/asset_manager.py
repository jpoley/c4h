"""
Asset management with Project-aware file system operations.
Path: c4h_agents/skills/asset_manager.py
"""

from pathlib import Path
from typing import Optional, Dict, Any, Union
from dataclasses import dataclass
import structlog
import shutil
from datetime import datetime

from c4h_agents.agents.base import BaseAgent, AgentResponse
from c4h_agents.core.project import Project
from c4h_agents.config import locate_config

logger = structlog.get_logger()

@dataclass
class AssetResult:
    """Result of an asset operation"""
    success: bool
    path: Path
    backup_path: Optional[Path] = None
    error: Optional[str] = None

class AssetManager(BaseAgent):
    """Manages asset operations with project-aware file system handling"""
    
    def __init__(self, config: Dict[str, Any] = None, project: Optional[Project] = None, **kwargs):
        """Initialize asset manager with configuration and optional project"""
        super().__init__(config=config, project=project)
        
        # First try to use the Project instance if provided
        if self.project:
            self.source_root = self.project.paths.source
            self.output_root = self.project.paths.root
            self.backup_dir = self.project.paths.workspace / "backups"
            self.project_path = self.project.paths.root
            
            logger.info("asset_manager.using_project",
                       project_name=self.project.metadata.name,
                       root=str(self.project.paths.root),
                       workspace=str(self.project.paths.workspace))
            return
            
        # Fall back to config-based project info
        project_info = None
        if isinstance(config, dict):
            project_info = config.get('project')

        # Initialize paths based on project context
        if project_info:
            project_path = Path(project_info.get('path', '.')).resolve()
            workspace_root = project_info.get('workspace_root')
            if workspace_root:
                workspace_path = Path(workspace_root) if Path(workspace_root).is_absolute() else project_path / workspace_root
            else:
                workspace_path = project_path / 'workspaces'

            self.source_root = project_path
            self.output_root = project_path
            self.backup_dir = workspace_path / "backups"
            self.project_path = project_path

            logger.info("asset_manager.project_paths",
                       project_path=str(project_path),
                       workspace_root=str(workspace_path))
        else:
            # Legacy path handling for backward compatibility
            asset_config = locate_config(self.config, "asset_manager")
            paths = asset_config.get('paths', {})
            self.source_root = Path(paths.get('source', '.')).resolve()
            self.output_root = Path(paths.get('output', paths.get('project_root', '.'))).resolve()
            self.backup_dir = (self.output_root / paths.get('backup_dir', 'workspaces/backups')).resolve()
            self.project_path = None

        # Configure backup settings
        self.backup_enabled = kwargs.get('backup_enabled', True)
        if self.backup_enabled:
            self.backup_dir.mkdir(parents=True, exist_ok=True)
            
        # Create semantic merger with config
        self.merger = kwargs.get('merger')
        if not self.merger:
            from c4h_agents.skills.semantic_merge import SemanticMerge
            self.merger = SemanticMerge(config=self.config)

        logger.info("asset_manager.initialized",
                   backup_enabled=self.backup_enabled,
                   backup_dir=str(self.backup_dir),
                   source_root=str(self.source_root),
                   output_root=str(self.output_root),
                   project_path=str(self.project_path) if self.project_path else None)

    def _normalize_path(self, path: Union[str, Path]) -> Path:
        """Normalize path using project context if available"""
        path = Path(str(path))
        
        # If project context is available, normalize against project root
        if self.project_path:
            if path.is_absolute():
                return path
            return (self.project_path / path).resolve()
            
        # Legacy normalization
        logger.debug("asset_manager.normalize_path.legacy",
                    input_path=str(path),
                    source_root=str(self.source_root),
                    output_root=str(self.output_root))
        
        if path.is_absolute():
            logger.debug("asset_manager.normalize_path.absolute", path=str(path))
            return path
                
        normalized = (self.output_root / path).resolve()
        logger.debug("asset_manager.normalize_path.result",
                    input=str(path),
                    normalized=str(normalized))
        return normalized

    def _get_relative_path(self, path: Union[str, Path]) -> Path:
        """Get path relative to project root"""
        path = self._normalize_path(path)
        try:
            if self.project_path:
                return path.relative_to(self.project_path)
            return path.relative_to(self.output_root)
        except ValueError:
            return path

    def _get_next_backup_path(self, path: Path) -> Path:
        """Generate backup path maintaining directory structure"""
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        rel_path = self._get_relative_path(path)
        backup_path = self.backup_dir / timestamp / rel_path
        
        logger.debug("asset_manager.backup_path_generated",
                    original=str(path),
                    relative=str(rel_path),
                    backup=str(backup_path))
                    
        return backup_path

    def process_action(self, action: Dict[str, Any]) -> AssetResult:
        """Process a single asset action with project awareness"""
        try:
            # Extract file path using common keys
            file_path = None
            if isinstance(action, dict):
                for key in ['file_path', 'path', 'file', 'filename']:
                    if key in action and action[key]:
                        file_path = str(action[key])
                        break
            
            if not file_path:
                raise ValueError("No file path found in action")
            
            # Use project-aware path resolution
            path = self._normalize_path(file_path)
            logger.debug("asset.processing", 
                        input_path=file_path,
                        resolved_path=str(path),
                        project=str(self.project_path) if self.project_path else None)

            # Create backup if enabled and file exists
            backup_path = None
            if self.backup_enabled and path.exists():
                backup_path = self._get_next_backup_path(path)
                backup_path.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(path, backup_path)
                logger.info("asset.backup_created", 
                          original=str(path),
                          backup=str(backup_path))

            # Let semantic merge handle the content/diff/merge logic
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

            # Ensure parent directory exists
            path.parent.mkdir(parents=True, exist_ok=True)

            # Write the final content
            path.write_text(content)
            logger.info("asset.write_success", 
                       path=str(path),
                       relative=str(self._get_relative_path(path)),
                       project=str(self.project_path) if self.project_path else None)

            return AssetResult(
                success=True,
                path=path,
                backup_path=backup_path
            )

        except Exception as e:
            logger.error("asset.process_failed", 
                        error=str(e),
                        path=str(path) if 'path' in locals() else None,
                        project=str(self.project_path) if self.project_path else None)
            return AssetResult(
                success=False,
                path=path if 'path' in locals() else Path('.'),
                error=str(e)
            )

    def process(self, context: Dict[str, Any]) -> AgentResponse:
        """Process asset operations with standard agent interface"""
        try:
            result = self.process_action(context.get('input_data', {}))
            return AgentResponse(
                success=result.success,
                data={
                    "path": str(result.path),
                    "backup_path": str(result.backup_path) if result.backup_path else None,
                    "raw_output": context.get('raw_output', '')
                },
                error=result.error
            )
        except Exception as e:
            logger.error("asset_manager.process_failed", 
                        error=str(e),
                        project=str(self.project_path) if self.project_path else None)
            return AgentResponse(success=False, data={}, error=str(e))