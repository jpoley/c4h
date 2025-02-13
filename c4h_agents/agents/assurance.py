"""
Assurance agent implementation for validation checks.
Path: src/agents/assurance.py
"""

from typing import Dict, Any, Optional, List
import structlog
from pathlib import Path
import subprocess
import sys

from dataclasses import dataclass
import shutil
import os
from config import locate_config
from c4h_agents.agents.base_agent import BaseAgent, AgentResponse 


logger = structlog.get_logger()

@dataclass
class ValidationResult:
    """Result of a validation run"""
    success: bool
    output: str
    error: Optional[str] = None
    validation_type: str = "test"  # "test" or "script"

class AssuranceAgent(BaseAgent):
    """Agent responsible for executing and validating test cases"""
    
    def __init__(self, config: Dict[str, Any] = None):
        """Initialize assurance agent."""
        super().__init__(config=config)
        
        # Get agent-specific config
        assurance_config = locate_config(self.config or {}, self._get_agent_name())
        
        # Initialize workspace path from config
        workspace_root = Path(self.config.get('project', {}).get('workspace_root', 'workspaces'))
        self.workspace_root = workspace_root / "validation"
        self.workspace_root.mkdir(parents=True, exist_ok=True)
            
        logger.info("workspace.created", path=str(self.workspace_root))

    def _get_agent_name(self) -> str:
        """Get agent name for config lookup"""
        return "assurance"

    def _get_system_message(self) -> str:
        """Get system message for LLM interactions"""
        return """You are a validation expert that analyzes test results.
        When given test output:
        1. Extract key success/failure indicators
        2. Identify specific test failures
        3. Extract relevant error messages
        4. Determine overall validation status
        5. Provide clear validation summary
        """

    def __del__(self):
        """Cleanup workspace on destruction"""
        try:
            if hasattr(self, 'workspace_root') and self.workspace_root.exists():
                shutil.rmtree(self.workspace_root)
                logger.info("workspace.cleaned", path=str(self.workspace_root))
        except Exception as e:
            logger.error("workspace.cleanup_failed", error=str(e))

    def _run_pytest(self, test_content: str) -> ValidationResult:
        """Run pytest validation"""
        try:
            # Create test file
            test_file = self.workspace_root / "test_validation.py"
            test_file.write_text(test_content)
            
            logger.info("pytest.file_created", path=str(test_file))
            
            # Capture output
            result = subprocess.run(
                [sys.executable, "-m", "pytest", "-v", "--no-header", str(test_file)],
                capture_output=True,
                text=True,
                check=False
            )
            
            success = result.returncode == 0
            output = result.stdout + result.stderr

            if success:
                logger.info("pytest.passed", output=output)
            else:
                logger.warning("pytest.failed", output=output)
            
            return ValidationResult(
                success=success,
                output=output,
                validation_type="test",
                error=None if success else "Tests failed"
            )

        except Exception as e:
            logger.error("pytest.execution_failed", error=str(e))
            return ValidationResult(
                success=False,
                output="",
                error=str(e),
                validation_type="test"
            )

    def _run_script(self, script_content: str) -> ValidationResult:
        """Run validation script"""
        try:
            script_file = (self.workspace_root / "validate.py").resolve()
            script_file.write_text(script_content)
            script_file.chmod(0o755)
            
            logger.info("script.created", path=str(script_file))
            
            result = subprocess.run(
                [sys.executable, str(script_file)],
                capture_output=True,
                text=True,
                cwd=str(script_file.parent),
                env=os.environ.copy()
            )
            
            success = result.returncode == 0
            output = result.stdout + result.stderr
            
            if success:
                logger.info("script.passed", output=output)
            else:
                logger.warning("script.failed", output=output)
            
            return ValidationResult(
                success=success,
                output=output,
                validation_type="script"
            )

        except Exception as e:
            logger.error("script.execution_failed", error=str(e))
            return ValidationResult(
                success=False,
                output="",
                error=str(e),
                validation_type="script"
            )

    def process(self, context: Dict[str, Any]) -> AgentResponse:
        """Process validation request"""
        try:
            # Extract changes and intent
            changes = context.get("changes", [])
            intent = context.get("intent")
            
            if not changes:
                return AgentResponse(
                    success=False,
                    data={},
                    error="No changes provided for validation"
                )

            # For now, return success stub
            # TODO: Implement actual validation
            return AgentResponse(
                success=True,
                data={
                    "validation_type": "stub",
                    "changes_checked": len(changes),
                    "status": "completed"
                },
                error=None
            )

        except Exception as e:
            logger.error("assurance.failed", error=str(e))
            return AgentResponse(
                success=False,
                data={},
                error=str(e)
            )