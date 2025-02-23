"""
Path: c4h_services/src/intent/impl/prefect/factories.py
Task factory functions with enhanced configuration handling.
"""

from typing import Dict, Any
from pathlib import Path
import structlog

from .models import AgentTaskConfig
from c4h_agents.agents.discovery import DiscoveryAgent
from c4h_agents.agents.solution_designer import SolutionDesigner 
from c4h_agents.agents.coder import Coder
from c4h_agents.core.project import Project

logger = structlog.get_logger()

def prepare_agent_config(config: Dict[str, Any], agent_section: str) -> Dict[str, Any]:
    """
    Prepare standard agent configuration following hierarchy.
    
    Args:
        config: Complete configuration dictionary
        agent_section: Name of agent section in llm_config.agents
        
    Returns:
        Dictionary with agent configuration
    """
    # Get agent-specific config
    agent_config = config.get("llm_config", {}).get("agents", {}).get(agent_section, {})
    
    # Build complete config
    return {
        "llm_config": config.get("llm_config", {}),
        "logging": config.get("logging", {}),
        "providers": config.get("providers", {}),
        "runtime": config.get("runtime", {}),
        **agent_config  # Agent-specific overrides last
    }

def create_discovery_task(config: Dict[str, Any]) -> AgentTaskConfig:
    """Create discovery agent task configuration."""
    agent_config = prepare_agent_config(config, "discovery")
    
    # Add tartxt config if present
    discovery_config = config.get("llm_config", {}).get("agents", {}).get("discovery", {})
    if "tartxt_config" in discovery_config:
        agent_config["tartxt_config"] = discovery_config["tartxt_config"]

    return AgentTaskConfig(
        agent_class=DiscoveryAgent,
        config=agent_config,
        task_name="discovery",
        requires_approval=False,
        max_retries=2,
        retry_delay_seconds=30
    )

def create_solution_task(config: Dict[str, Any]) -> AgentTaskConfig:
    """Create solution designer task configuration."""
    agent_config = prepare_agent_config(config, "solution_designer")

    return AgentTaskConfig(
        agent_class=SolutionDesigner,
        config=agent_config,
        task_name="solution_designer",
        requires_approval=True,  # Solution design might need human review
        max_retries=2,
        retry_delay_seconds=30
    )

def create_coder_task(config: Dict[str, Any]) -> AgentTaskConfig:
    """Create coder agent task configuration."""
    agent_config = prepare_agent_config(config, "coder")
    
    # Add backup config if present
    if "backup" in config:
        agent_config["backup"] = config["backup"]
    else:
        agent_config["backup"] = {"enabled": True}

    # Project handling needs its own scope
    project = None
    try:
        if 'project' in config:
            project_config = config['project']
            if isinstance(project_config, Project):
                project = project_config
            else:
                project = Project.from_config(config)
                
            logger.info("coder_factory.project_initialized",
                       project_path=str(project.paths.root),
                       workspace_root=str(project.paths.workspace))
    except Exception as e:
        logger.error("coder_factory.project_creation_failed", error=str(e))

    return AgentTaskConfig(
        agent_class=Coder,
        config=agent_config,
        task_name="coder",
        requires_approval=True,
        max_retries=1,
        retry_delay_seconds=60,
        project=project  # Project properly scoped and passed
    )