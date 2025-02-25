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
from c4h_agents.config import create_config_node

logger = structlog.get_logger()

def prepare_agent_config(config: Dict[str, Any], agent_section: str) -> Dict[str, Any]:
    """
    Prepare standard agent configuration following hierarchy.
    Now uses path-based configuration access.
    
    Args:
        config: Complete configuration dictionary
        agent_section: Name of agent section in llm_config.agents
        
    Returns:
        Dictionary with agent configuration
    """
    # Create a configuration node for path-based access
    config_node = create_config_node(config)
    
    # Get workflow run ID from hierarchical path queries
    workflow_run_id = (
        config_node.get_value("workflow_run_id") or
        config_node.get_value("system.runid") or
        config_node.get_value("runtime.workflow_run_id") or
        config_node.get_value("runtime.run_id") or
        config_node.get_value("runtime.workflow.id")
    )
    
    # Pass through the full configuration, but ensure critical elements exist
    complete_config = config.copy()
    
    # Ensure system namespace exists
    if "system" not in complete_config:
        complete_config["system"] = {}
        
    # Ensure workflow run ID is set in system namespace
    if workflow_run_id:
        complete_config["system"]["runid"] = workflow_run_id
        # Also set at top level for direct access
        complete_config["workflow_run_id"] = workflow_run_id
    
    # Log the configuration preparation
    agent_node = config_node.get_node(f"llm_config.agents.{agent_section}")
    logger.debug(f"{agent_section}.config_prepared", 
                has_system=bool(complete_config.get("system")),
                system_runid=complete_config.get("system", {}).get("runid"),
                workflow_run_id=workflow_run_id,
                agent_config_keys=list(agent_node.data.keys()) if agent_node.data else [])
    
    return complete_config

def create_discovery_task(config: Dict[str, Any]) -> AgentTaskConfig:
    """Create discovery agent task configuration."""
    agent_config = prepare_agent_config(config, "discovery")
    
    # Create config node for path-based access
    config_node = create_config_node(config)
    discovery_config = config_node.get_node("llm_config.agents.discovery")
    
    # Add tartxt config if present using path queries
    tartxt_config = discovery_config.get_value("tartxt_config")
    if tartxt_config:
        agent_config["tartxt_config"] = tartxt_config

    # Discovery agent doesn't need project - it will create one if needed
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

    # Solution designer doesn't need project - it will create one if needed
    return AgentTaskConfig(
        agent_class=SolutionDesigner,
        config=agent_config,
        task_name="solution_designer",
        requires_approval=True,
        max_retries=2,
        retry_delay_seconds=30
    )

def create_coder_task(config: Dict[str, Any]) -> AgentTaskConfig:
    """Create coder agent task configuration."""
    agent_config = prepare_agent_config(config, "coder")
    
    # Create config node for path-based access
    config_node = create_config_node(config)
    
    # Add backup config if present
    backup_config = config_node.get_value("backup")
    if backup_config:
        agent_config["backup"] = backup_config
    else:
        agent_config["backup"] = {"enabled": True}

    # No Project object creation here - Coder will create it from config if needed
    return AgentTaskConfig(
        agent_class=Coder,
        config=agent_config,
        task_name="coder",
        requires_approval=True,
        max_retries=1,
        retry_delay_seconds=60
    )