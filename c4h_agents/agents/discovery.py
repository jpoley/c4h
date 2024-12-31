"""
Discovery agent implementation.
Path: src/agents/discovery.py
"""

from typing import Dict, Any, Optional, List
import structlog
import subprocess
import sys
from pathlib import Path
from datetime import datetime
from dataclasses import dataclass, field
from .base import BaseAgent, AgentResponse
from config import locate_config

logger = structlog.get_logger()

@dataclass
class DiscoveryResult:
    """Result of project discovery operation"""
    success: bool
    files: Dict[str, bool]
    raw_output: str
    project_path: str
    error: Optional[str] = None
    timestamp: str = field(default_factory=lambda: datetime.utcnow().isoformat())

class DiscoveryAgent(BaseAgent):
    """Agent responsible for project discovery using tartxt"""
    
    def __init__(self, config: Dict[str, Any] = None):
        """Initialize discovery agent."""
        super().__init__(config=config)
        
        # Get agent-specific config
        discovery_config = locate_config(self.config or {}, self._get_agent_name())
        
        # Get workspace path from config
        workspace_root = self.config.get('project', {}).get('workspace_root', 'workspaces')
        self.workspace_root = Path(workspace_root)
        self.workspace_root.mkdir(parents=True, exist_ok=True)
        
        # Get tartxt config
        self.tartxt_config = discovery_config.get('tartxt_config', {})
        
        logger.info("discovery.initialized",
                   workspace_root=str(self.workspace_root),
                   tartxt_config=self.tartxt_config)

    def _get_agent_name(self) -> str:
        """Get agent name for config lookup."""
        return "discovery"

    def _parse_manifest(self, output: str) -> Dict[str, bool]:
        """Parse manifest section from tartxt output to get file list"""
        files = {}
        manifest_section = False
        
        for line in output.split('\n'):
            line = line.strip()
            
            if line == "== Manifest ==":
                manifest_section = True
                continue
            elif line.startswith("== Content =="):
                break
                
            if manifest_section and line:
                if not line.startswith('=='):
                    norm_path = line.replace('\\', '/')
                    files[norm_path] = True
                    
        return files

    def _resolve_input_paths(self, project_path: Path) -> List[str]:
        """Resolve input paths against project root"""
        input_paths = self.tartxt_config.get('input_paths', [])
        resolved_paths = []
        
        for path in input_paths:
            # If path is absolute, use it directly
            if Path(path).is_absolute():
                resolved_paths.append(str(Path(path)))
            else:
                # Resolve relative path against project root
                full_path = (project_path / path).resolve()
                resolved_paths.append(str(full_path))
                
        logger.debug("discovery.resolved_paths",
                    project_path=str(project_path),
                    input_paths=input_paths,
                    resolved_paths=resolved_paths)
                    
        return resolved_paths

    def _run_tartxt(self, project_path: str) -> DiscoveryResult:
        try:
            # Convert to Path and resolve
            base_path = Path(project_path).resolve()
            
            # Get resolved input paths
            input_paths = self._resolve_input_paths(base_path)
            
            # Build tartxt command
            cmd = [sys.executable, "src/skills/tartxt.py"]
            
            # Add exclusions
            for exclude in self.tartxt_config.get('exclusions', []):
                cmd.extend(['-x', exclude])
            
            # Add output options
            if self.tartxt_config.get('output_type') == "file":
                cmd.extend(['-f', self.tartxt_config.get('output_file', 'tartxt_output.txt')])
            else:
                cmd.append('-o')

            # Add input paths last
            cmd.extend(input_paths)

            logger.debug("discovery.tartxt_command",
                        cmd=cmd,
                        paths=input_paths,
                        project_path=str(base_path))

            # Run tartxt with stdout capture  
            result = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                check=True
            )

            return DiscoveryResult(
                success=True,
                files=self._parse_manifest(result.stdout),
                raw_output=result.stdout,
                project_path=str(base_path)
            )

        except subprocess.CalledProcessError as e:
            logger.error("discovery.tartxt_failed", 
                        error=str(e),
                        stderr=e.stderr)
            return DiscoveryResult(
                success=False,
                files={},
                raw_output=e.stderr,
                project_path=str(base_path),
                error=str(e)
            )
    
    def process(self, context: Dict[str, Any]) -> AgentResponse:
        """Process a project discovery request."""
        try:
            # Get and validate project path
            project_path = context.get("project_path")
            if not project_path:
                return AgentResponse(
                    success=False,
                    data={},
                    error="No project path provided"
                )
            
            path = Path(project_path)
            if not path.exists():
                return AgentResponse(
                    success=False,
                    data={},
                    error=f"Project path does not exist: {project_path}"
                )

            # Run discovery
            result = self._run_tartxt(str(project_path))
            
            return AgentResponse(
                success=result.success,
                data={
                    "files": result.files,
                    "raw_output": result.raw_output,
                    "project_path": result.project_path,
                    "timestamp": result.timestamp
                },
                error=result.error
            )

        except Exception as e:
            logger.error("discovery.failed", error=str(e))
            return AgentResponse(
                success=False,
                data={},
                error=str(e)
            )