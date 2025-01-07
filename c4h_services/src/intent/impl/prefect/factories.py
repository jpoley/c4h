"""
Task factory functions for creating agent task configurations.
Path: c4h_services/src/intent/impl/prefect/factories.py
"""

from typing import Dict, Any
from pathlib import Path
import structlog

from .models import AgentTaskConfig
from c4h_agents.agents.discovery import DiscoveryAgent
from c4h_agents.agents.solution_designer import SolutionDesigner 
from c4h_agents.agents.coder import Coder
from c4h_agents.agents.assurance import AssuranceAgent
from c4h_agents.core.project import Project, ProjectPaths

logger = structlog.get_logger()

def get_project_dict(project: Project) -> Dict[str, str]:
    """Convert Project instance paths to dictionary format"""
    return {
        'path': str(project.paths.root),
        'workspace_root': str(project.paths.workspace)
    }

def create_discovery_task(config: Dict[str, Any]) -> AgentTaskConfig:
    """Create discovery agent task configuration."""
    # Get discovery-specific config
    discovery_config = config.get("llm_config", {}).get("agents", {}).get("discovery", {})
    
    agent_config = {
        "llm_config": config.get("llm_config", {}),
        "logging": config.get("logging", {}),
        "providers": config.get("providers", {}),
        "tartxt_config": discovery_config.get("tartxt_config", {})  # Pass through TarTXT config
    }

    # Handle project configuration
    if 'project' in config:
        project_config = config['project']
        if isinstance(project_config, Project):
            agent_config['project'] = get_project_dict(project_config)
        else:
            agent_config['project'] = project_config

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
    agent_config = {
        "llm_config": config.get("llm_config", {}),
        "logging": config.get("logging", {}),
        "providers": config.get("providers", {})
    }
    
    # Handle project configuration
    if 'project' in config:
        project_config = config['project']
        if isinstance(project_config, Project):
            agent_config['project'] = get_project_dict(project_config)
        else:
            agent_config['project'] = project_config

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
    agent_config = {
        "llm_config": config.get("llm_config", {}),
        "logging": config.get("logging", {}),
        "providers": config.get("providers", {}),
        "backup": config.get("backup", {"enabled": True})  # Always enable backups for safety
    }

    # Create Project instance if project config exists
    project = None
    try:
        if 'project' in config:
            project_config = config['project']
            if isinstance(project_config, Project):
                project = project_config
                agent_config['project'] = get_project_dict(project)
            else:
                # Create new Project instance from config
                project = Project.from_config(config)
                agent_config['project'] = get_project_dict(project)
                
            logger.info("coder_factory.project_initialized",
                       project_path=str(project.paths.root),
                       workspace_root=str(project.paths.workspace))
    except Exception as e:
        logger.error("coder_factory.project_creation_failed", error=str(e))

    return AgentTaskConfig(
        agent_class=Coder,
        config=agent_config,
        task_name="coder",
        requires_approval=True,  # Code changes should be reviewed
        max_retries=1,  # Be conservative with retries for code changes
        retry_delay_seconds=60,
        project=project  # Pass Project instance if available
    )

def create_assurance_task(config: Dict[str, Any]) -> AgentTaskConfig:
    """Create assurance agent task configuration."""
    agent_config = {
        "llm_config": config.get("llm_config", {}),
        "logging": config.get("logging", {}),
        "providers": config.get("providers", {})
    }
    
    # Handle project configuration
    if 'project' in config:
        project_config = config['project']
        if isinstance(project_config, Project):
            agent_config['project'] = get_project_dict(project_config)
        else:
            agent_config['project'] = project_config

    return AgentTaskConfig(
        agent_class=AssuranceAgent,
        config=agent_config,
        task_name="assurance",
        requires_approval=False,
        max_retries=2,
        retry_delay_seconds=30
    )