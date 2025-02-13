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
from c4h_agents.agents.base_agent import BaseAgent, AgentResponse 
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

    """Update to _run_tartxt method in discovery.py"""

    def _run_tartxt(self, project_path: str) -> DiscoveryResult:
        """Run tartxt discovery tool to analyze project files.
        
        Args:
            project_path: Path to project root
            
        Returns:
            DiscoveryResult containing file manifest and output
            
        The function handles tartxt configuration including:
        - Input path resolution against project root  
        - Exclusion pattern handling
        - Output format selection
        """
        try:
            # Convert to Path and resolve
            base_path = Path(project_path).resolve()
            
            # Get resolved input paths
            input_paths = self._resolve_input_paths(base_path)
            if not input_paths:
                raise ValueError("No input paths configured or resolved")
            
            # Get tartxt script path - fail fast if not configured
            script_path = self.tartxt_config.get('script_path')
            if not script_path:
                raise ValueError("tartxt_config must include 'script_path'")
                
            script_path = Path(script_path)
            if not script_path.is_file():
                raise ValueError(f"tartxt script not found at: {script_path}")

            # Start building command with python interpreter and script
            cmd = [sys.executable, str(script_path.resolve())]
                
            # Process exclusions - normalize to list
            exclusions = self.tartxt_config.get('exclusions', [])
            if isinstance(exclusions, str):
                exclusion_list = [x.strip() for x in exclusions.split(',') if x.strip()]
            elif isinstance(exclusions, (list, tuple)):
                exclusion_list = [str(x).strip() for x in exclusions if x]
            else:
                logger.warning("discovery.invalid_exclusions",
                            type=type(exclusions).__name__,
                            using="default empty list")
                exclusion_list = []

            # Add exclusions as a single -x argument with comma-separated patterns
            if exclusion_list:
                cmd.extend(['-x', ','.join(exclusion_list)])
                logger.debug("discovery.tartxt_command.exclusions",
                            patterns=exclusion_list)

            # Configure output
            if self.tartxt_config.get('output_type') == "file":
                output_file = self.tartxt_config.get('output_file', 'tartxt_output.txt')
                cmd.extend(['-f', output_file])
            else:
                cmd.append('-o')  # stdout output

            # Add input paths last
            cmd.extend(input_paths)

            # Log complete command
            logger.debug("discovery.tartxt_command",
                        cmd=cmd,
                        input_paths=input_paths,
                        project_path=str(base_path),
                        script_path=str(script_path))

            # Run tartxt with output capture
            try:
                result = subprocess.run(
                    cmd,
                    capture_output=True,
                    text=True,
                    check=True,
                    cwd=str(base_path)  # Run from project root
                )
            except subprocess.CalledProcessError as e:
                logger.error("discovery.tartxt_execution_failed", 
                            error=str(e),
                            stderr=e.stderr,
                            returncode=e.returncode)
                return DiscoveryResult(
                    success=False,
                    files={},
                    raw_output=e.stderr,
                    project_path=str(base_path),
                    error=f"tartxt failed with exit code {e.returncode}: {e.stderr}"
                )

            # Parse output and return result
            files = self._parse_manifest(result.stdout)
            logger.info("discovery.complete",
                    file_count=len(files),
                    project_path=str(base_path))

            return DiscoveryResult(
                success=True,
                files=files,
                raw_output=result.stdout,
                project_path=str(base_path)
            )

        except ValueError as e:
            # Configuration/validation errors
            logger.error("discovery.config_error",
                        error=str(e),
                        project_path=project_path)
            return DiscoveryResult(
                success=False,
                files={},
                raw_output="",
                project_path=str(project_path),
                error=str(e)
            )
            
        except Exception as e:
            # Unexpected errors
            logger.error("discovery.unexpected_error",
                        error=str(e),
                        error_type=type(e).__name__,
                        project_path=project_path)
            return DiscoveryResult(
                success=False,
                files={},
                raw_output="",
                project_path=str(project_path),
                error=f"Unexpected error: {str(e)}"
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