"""
Project domain model for code refactoring system.
Path: c4h_agents/core/project.py
"""

from dataclasses import dataclass
from pathlib import Path
from typing import Optional, Dict, Any

@dataclass
class ProjectPaths:
    """Standard project path definitions"""
    root: Path           # Project root directory (all paths relative to this)
    workspace: Path      # Directory for working files/backups
    source: Path         # Source code directory
    output: Path        # Output directory for changes
    config: Path        # Configuration files location
    
    @classmethod
    def from_config(cls, config: Dict[str, Any]) -> 'ProjectPaths':
        """Create paths from configuration dictionary"""
        # Get project root first
        root = Path(config.get('project', {}).get('path', '.'))
        if not root.is_absolute():
            root = Path.cwd() / root
        root = root.resolve()
        
        # Other paths relative to root
        workspace = root / config.get('project', {}).get('workspace_root', 'workspaces')
        source = root / config.get('project', {}).get('source_root', '.')
        output = root / config.get('project', {}).get('output_root', '.')
        config_dir = root / config.get('project', {}).get('config_root', 'config')
        
        return cls(
            root=root,
            workspace=workspace,
            source=source,
            output=output,
            config=config_dir
        )

@dataclass 
class ProjectMetadata:
    """Project metadata and settings"""
    name: str
    description: Optional[str] = None
    version: Optional[str] = None
    settings: Dict[str, Any] = None

@dataclass
class Project:
    """Core project domain model"""
    paths: ProjectPaths
    metadata: ProjectMetadata
    config: Dict[str, Any]    # Complete project configuration
    
    @classmethod
    def from_config(cls, config: Dict[str, Any]) -> 'Project':
        """Create project from configuration"""
        paths = ProjectPaths.from_config(config)
        
        # Extract metadata
        project_config = config.get('project', {})
        metadata = ProjectMetadata(
            name=project_config.get('name', paths.root.name),
            description=project_config.get('description'),
            version=project_config.get('version'),
            settings=project_config.get('settings', {})
        )
        
        return cls(
            paths=paths,
            metadata=metadata,
            config=config
        )

    def resolve_path(self, path: Path) -> Path:
        """Resolve a path relative to project root"""
        if path.is_absolute():
            return path
        return (self.paths.root / path).resolve()

    def get_agent_config(self, agent_name: str) -> Dict[str, Any]:
        """Get agent-specific configuration with project context"""
        agent_config = self.config.get('llm_config', {}).get('agents', {}).get(agent_name, {})
        return {
            'project': self,  # Provide project context
            **agent_config
        }