"""
Asset management with file system operations and backup management.
Path: c4h_agents/skills/asset_manager.py
"""

from pathlib import Path
from typing import Optional, Dict, Any, Union, List
from dataclasses import dataclass
import structlog
import shutil
from datetime import datetime
from skills.semantic_merge import SemanticMerge
from agents.base import AgentResponse
from config import locate_config
from agents.base import BaseAgent

logger = structlog.get_logger()

@dataclass
class AssetResult:
    """Result of an asset operation"""
    success: bool
    path: Path
    backup_path: Optional[Path] = None
    error: Optional[str] = None

class AssetManager(BaseAgent):
    """Manages asset operations with file system handling"""
    
    def __init__(self, config: Dict[str, Any] = None, **kwargs):  # Add **kwargs to accept legacy params
        """Initialize asset manager with configuration"""
        super().__init__(config=config)
        
        # Get asset manager specific config
        asset_config = locate_config(self.config, "asset_manager")
        paths = asset_config.get('paths', {})
        
        # Get paths from config
        self.source_root = Path(paths.get('source', '.')).resolve()
        self.output_root = Path(paths.get('output', paths.get('project_root', '.'))).resolve()
        
        # Handle backup directory - relative to output path
        backup_path = asset_config.get('backup_dir', 'workspaces/backups')
        self.backup_dir = (self.output_root / backup_path).resolve()
        
        # Use config value, fall back to kwargs for backward compatibility
        self.backup_enabled = asset_config.get('backup_enabled', kwargs.get('backup_enabled', True))
        if self.backup_enabled:
            self.backup_dir.mkdir(parents=True, exist_ok=True)
            
        # Create semantic merger with config
        self.merger = kwargs.get('merger') or SemanticMerge(config=self.config)

        logger.info("asset_manager.initialized",
                   backup_enabled=self.backup_enabled,
                   backup_dir=str(self.backup_dir),
                   source_root=str(self.source_root),
                   output_root=str(self.output_root))

    def _normalize_path(self, path: Union[str, Path]) -> Path:
        """Normalize an input path"""
        logger.debug("asset_manager.normalize_path.input",
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

    def _get_absolute_path(self, path: Union[str, Path]) -> Path:
        """Convert path to absolute output path"""
        path = Path(str(path))
        
        if path.is_absolute():
            return path
        
        # Use output root for new paths
        return (self.output_root / path).resolve()

    def _get_relative_path(self, path: Union[str, Path]) -> Path:
        """Get path relative to project root"""
        path = self._normalize_path(path)
        try:
            return path.relative_to(self.output_root)
        except ValueError:
            return path

    def _get_next_backup_path(self, path: Path) -> Path:
        """Generate backup path for specific file"""
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        
        # Get normalized relative path
        rel_path = self._get_relative_path(path)
        
        # Create backup path maintaining only necessary structure
        backup_path = self.backup_dir / timestamp / rel_path
        
        logger.debug("asset_manager.backup_path_generated",
                    original=str(path),
                    relative=str(rel_path),
                    backup=str(backup_path))
                    
        return backup_path

    def process_action(self, action: Dict[str, Any]) -> AssetResult:
        """Process a single asset action using state matrix logic"""
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
            
            # Convert to absolute path with proper resolution
            path = self._get_absolute_path(file_path)
            logger.debug("asset.processing", 
                        input_path=file_path,
                        resolved_path=str(path))

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
                       relative=str(self._get_relative_path(path)))

            return AssetResult(
                success=True,
                path=path,
                backup_path=backup_path
            )

        except Exception as e:
            logger.error("asset.process_failed", 
                        error=str(e),
                        path=str(path) if 'path' in locals() else None)
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
            logger.error("asset_manager.process_failed", error=str(e))
            return AgentResponse(success=False, data={}, error=str(e))