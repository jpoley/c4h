"""
Task factory functions for creating agent task configurations.
Path: c4h_services/src/intent/impl/prefect/factories.py
"""

from typing import Dict, Any
from .models import AgentTaskConfig
from c4h_agents.agents.discovery import DiscoveryAgent
from c4h_agents.agents.solution_designer import SolutionDesigner
from c4h_agents.agents.coder import Coder
from c4h_agents.agents.assurance import AssuranceAgent

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
    
    return AgentTaskConfig(
        agent_class=Coder,
        config=agent_config,
        task_name="coder",
        requires_approval=True,  # Code changes should be reviewed
        max_retries=1,  # Be conservative with retries for code changes
        retry_delay_seconds=60
    )

def create_assurance_task(config: Dict[str, Any]) -> AgentTaskConfig:
    """Create assurance agent task configuration."""
    agent_config = {
        "llm_config": config.get("llm_config", {}),
        "logging": config.get("logging", {}),
        "providers": config.get("providers", {})
    }
    
    return AgentTaskConfig(
        agent_class=AssuranceAgent,
        config=agent_config,
        task_name="assurance",
        requires_approval=False,
        max_retries=2,
        retry_delay_seconds=30
    )