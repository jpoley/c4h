"""
Asset management with minimal processing and LLM-first design.
Path: c4h_agents/skills/asset_manager.py
"""

from pathlib import Path
from typing import Optional, Dict, Any, Union
from dataclasses import dataclass
import structlog
import shutil
import os
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
                workspace_root = project_config.get('workspace_root', 'workspaces')
                if not Path(workspace_root).is_absolute():
                    workspace_root = str(self.project_path / workspace_root)
                self.backup_dir = Path(workspace_root) / "backups"
            else:
                # Handle Project instance
                self.project_path = project_config.paths.root
                self.backup_dir = project_config.paths.workspace / "backups"
        else:
            # Fallback for no project config
            self.backup_dir = Path(kwargs.get('backup_dir', 'workspaces/backups')).resolve()

        # Configure backup and create merger
        self.backup_enabled = kwargs.get('backup_enabled', True)
        if self.backup_enabled:
            self.backup_dir.mkdir(parents=True, exist_ok=True)
            logger.info("asset_manager.backup_enabled", backup_dir=str(self.backup_dir))
        else:
            logger.info("asset_manager.backup_disabled")
        
        # Get semantic merger
        self.merger = kwargs.get('merger')
        if not self.merger:
            self.merger = SemanticMerge(config=config)

        logger.info("asset_manager.initialized",
                   backup_enabled=self.backup_enabled,
                   backup_dir=str(self.backup_dir),
                   project_path=str(self.project_path) if self.project_path else None,
                   cwd=os.getcwd())

    def _resolve_file_path(self, file_path: str) -> Path:
        """
        Single source of truth for resolving file paths.
        Used consistently for all file operations (read/write/backup).
        """
        original_path = Path(file_path)
        
        # Absolute paths are used as-is
        if original_path.is_absolute():
            resolved_path = original_path
            logger.debug("asset_manager.path_absolute", path=str(resolved_path))
            return resolved_path
            
        # We need a project path for relative resolution
        if not self.project_path:
            # No project path, use CWD
            resolved_path = (Path.cwd() / original_path).resolve()
            logger.debug("asset_manager.path_cwd_relative", 
                        original=file_path, 
                        resolved=str(resolved_path))
            return resolved_path
            
        # Handle special case for tests/test_projects paths
        if str(original_path).startswith('tests/test_projects/'):
            # Extract relative part after tests/test_projects
            path_parts = original_path.parts
            if len(path_parts) > 2:
                relative_path = Path(*path_parts[2:])
                resolved_path = (self.project_path / relative_path).resolve()
                logger.debug("asset_manager.path_special_case", 
                           original=file_path, 
                           relative=str(relative_path), 
                           resolved=str(resolved_path))
                return resolved_path
        
        # Standard project-relative path
        resolved_path = (self.project_path / original_path).resolve()
        logger.debug("asset_manager.path_project_relative", 
                   original=file_path, 
                   project=str(self.project_path), 
                   resolved=str(resolved_path))
        return resolved_path

    def _create_backup(self, file_path: Path) -> Optional[Path]:
        """
        Create a backup of a file if it exists and backups are enabled.
        
        Args:
            file_path: The resolved path to backup
            
        Returns:
            Path to backup file or None if no backup was created
        """
        if not self.backup_enabled or not file_path.exists():
            return None
            
        try:
            # Create timestamped backup directory
            timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            backup_dir = self.backup_dir / timestamp
            
            # Determine relative structure for backup
            if self.project_path and str(file_path).startswith(str(self.project_path)):
                try:
                    # Get path relative to project
                    rel_path = file_path.relative_to(self.project_path)
                    backup_path = backup_dir / rel_path
                except ValueError:
                    # Fallback if not relative to project
                    backup_path = backup_dir / file_path.name
            else:
                # Not in project, just use filename
                backup_path = backup_dir / file_path.name
                
            # Ensure backup directory exists
            backup_path.parent.mkdir(parents=True, exist_ok=True)
            
            # Copy the file
            shutil.copy2(file_path, backup_path)
            logger.info("asset_manager.backup_created",
                       original=str(file_path),
                       backup=str(backup_path))
                       
            return backup_path
            
        except Exception as e:
            logger.error("asset_manager.backup_failed", 
                       file=str(file_path), 
                       error=str(e))
            return None

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

            # Resolve file path using consistent resolution logic
            resolved_path = self._resolve_file_path(file_path)
            logger.info("asset_manager.file_resolved",
                       original=file_path,
                       resolved=str(resolved_path),
                       exists=resolved_path.exists())

            # Create a backup if the file exists
            backup_path = self._create_backup(resolved_path)

            # Prepare merged content - ensure original content is available
            action_copy = dict(action)
            if resolved_path.exists() and 'original' not in action_copy:
                action_copy['original'] = resolved_path.read_text()
                
            # Let merger handle content merging/creation
            merge_result = self.merger.process(action_copy)
            if not merge_result.success:
                logger.error("asset_manager.merge_failed", error=merge_result.error)
                return AssetResult(
                    success=False,
                    path=resolved_path,
                    backup_path=backup_path,
                    error=merge_result.error
                )
                
            # Get merged content
            content = merge_result.data.get('response')
            if not content:
                logger.error("asset_manager.no_content")
                return AssetResult(
                    success=False,
                    path=resolved_path,
                    backup_path=backup_path,
                    error="No content after merge"
                )

            # Write final content to the resolved path
            resolved_path.parent.mkdir(parents=True, exist_ok=True)
            resolved_path.write_text(content)
            logger.info("asset_manager.content_written", path=str(resolved_path))
            
            return AssetResult(
                success=True, 
                path=resolved_path, 
                backup_path=backup_path
            )

        except Exception as e:
            logger.error("asset.process_failed", 
                error=str(e),
                path=str(resolved_path) if 'resolved_path' in locals() else None,
                file_path=file_path if 'file_path' in locals() else None,
                project=str(self.project_path) if self.project_path else None
            )
            return AssetResult(
                success=False,
                path=resolved_path if 'resolved_path' in locals() else Path('.'),
                backup_path=None,
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