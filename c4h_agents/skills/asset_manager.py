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
from .semantic_merge import SemanticMerge
from ..agents.base import BaseAgent, AgentResponse
from ..core.project import Project
from ..config import locate_config

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
        
        # Get asset manager specific config
        asset_config = locate_config(self.config, "asset_manager")
        
        # Initialize paths based on project or config
        if self.project:
            self.source_root = self.project.paths.source
            self.output_root = self.project.paths.output
            self.backup_dir = self.project.paths.workspace / "backups"
        else:
            # Legacy path handling for backward compatibility
            paths = asset_config.get('paths', {})
            self.source_root = Path(paths.get('source', '.')).resolve()
            self.output_root = Path(paths.get('output', paths.get('project_root', '.'))).resolve()
            backup_path = asset_config.get('backup_dir', 'workspaces/backups')
            self.backup_dir = (self.output_root / backup_path).resolve()

        # Configure backup settings
        self.backup_enabled = asset_config.get('backup_enabled', kwargs.get('backup_enabled', True))
        if self.backup_enabled:
            self.backup_dir.mkdir(parents=True, exist_ok=True)
            
        # Create semantic merger with config
        self.merger = kwargs.get('merger') or SemanticMerge(config=self.config, project=self.project)

        logger.info("asset_manager.initialized",
                   backup_enabled=self.backup_enabled,
                   backup_dir=str(self.backup_dir),
                   source_root=str(self.source_root),
                   output_root=str(self.output_root),
                   project_name=self.project.metadata.name if self.project else None)

    def _normalize_path(self, path: Union[str, Path]) -> Path:
        """Normalize path using project context if available"""
        if self.project:
            return self.project.resolve_path(path)
            
        # Legacy normalization for backward compatibility
        logger.debug("asset_manager.normalize_path.legacy",
                    input_path=str(path),
                    source_root=str(self.source_root),
                    output_root=str(self.output_root))
        
        path = Path(str(path).replace('//', '/'))
        
        if path.is_absolute():
            logger.debug("asset_manager.normalize_path.absolute", path=str(path))
            return path
                
        # Try output path first since that's where we're writing
        normalized = (self.output_root / path).resolve()
        logger.debug("asset_manager.normalize_path.result",
                    input=str(path),
                    normalized=str(normalized))
        return normalized

    def _get_relative_path(self, path: Union[str, Path]) -> Path:
        """Get path relative to project root using project if available"""
        if self.project:
            return self.project.get_relative_path(path)
            
        # Legacy relative path handling
        path = self._normalize_path(path)
        try:
            return path.relative_to(self.output_root)
        except ValueError:
            return path

    def _get_next_backup_path(self, path: Path) -> Path:
        """Generate backup path maintaining directory structure"""
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        
        # Get normalized relative path
        rel_path = self._get_relative_path(path)
        
        # Create backup path maintaining structure
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
                        project=self.project.metadata.name if self.project else None)

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
                       project=self.project.metadata.name if self.project else None)

            return AssetResult(
                success=True,
                path=path,
                backup_path=backup_path
            )

        except Exception as e:
            logger.error("asset.process_failed", 
                        error=str(e),
                        path=str(path) if 'path' in locals() else None,
                        project=self.project.metadata.name if self.project else None)
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
                        project=self.project.metadata.name if self.project else None)
            return AgentResponse(success=False, data={}, error=str(e))