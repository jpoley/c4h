"""
Prefect-enabled test runner for individual agent execution.
Path: c4h_services/examples/prefect_runner.py
"""

import sys
from pathlib import Path
from typing import Dict, Any, Optional
import structlog
import argparse
from prefect import flow
from rich.console import Console
import yaml
from enum import Enum

# Add source directories to path
root_dir = Path(__file__).parent.parent.parent
sys.path.append(str(root_dir))

from c4h_agents.agents.discovery import DiscoveryAgent
from c4h_agents.agents.solution_designer import SolutionDesigner
from c4h_agents.agents.coder import Coder
from c4h_agents.agents.assurance import AssuranceAgent
from c4h_agents.skills.semantic_iterator import SemanticIterator
from c4h_agents.skills.semantic_merge import SemanticMerge
from c4h_agents.skills.semantic_extract import SemanticExtract
from c4h_agents.skills.asset_manager import AssetManager
from c4h_agents.config import deep_merge

from c4h_services.src.intent.impl.prefect.tasks import (
    AgentTaskConfig,
    run_agent_task,
    create_discovery_task,
    create_solution_task,
    create_coder_task,
    create_assurance_task
)

logger = structlog.get_logger()

# Agent registry with task creation functions
AGENT_REGISTRY = {
    "discovery": create_discovery_task,
    "solution_designer": create_solution_task,
    "coder": create_coder_task,
    "assurance": create_assurance_task,
    # Add custom configs for skills
    "semantic_iterator": lambda config: AgentTaskConfig(
        agent_class=SemanticIterator,
        config=config,
        task_name="semantic_iterator"
    ),
    "semantic_merge": lambda config: AgentTaskConfig(
        agent_class=SemanticMerge,
        config=config,
        task_name="semantic_merge"
    ),
    "semantic_extract": lambda config: AgentTaskConfig(
        agent_class=SemanticExtract,
        config=config,
        task_name="semantic_extract"
    ),
    "asset_manager": lambda config: AgentTaskConfig(
        agent_class=AssetManager,
        config=config,
        task_name="asset_manager"
    )
}

class LogMode(str, Enum):
    """Logging modes supported by runner"""
    DEBUG = "debug"     
    NORMAL = "normal"   

def load_configs(config_path: str) -> Dict[str, Any]:
    """Load and merge configurations"""
    try:
        # Find system config
        sys_paths = [
            Path("config/system_config.yml"),
            Path("../config/system_config.yml"),
            root_dir / "config" / "system_config.yml"
        ]
        
        sys_config_path = next((p for p in sys_paths if p.exists()), None)
        if not sys_config_path:
            raise FileNotFoundError("system_config.yml not found")
            
        # Load configs
        with open(sys_config_path) as f:
            system_config = yaml.safe_load(f)
            
        with open(config_path) as f:
            test_config = yaml.safe_load(f)

        return deep_merge(system_config, test_config)

    except Exception as e:
        logger.error("config.load_failed", error=str(e))
        raise

def format_output(data: Dict[str, Any]) -> None:
    """Format task output for display"""
    print("\n=== Results ===\n")
    
    try:
        if data.get("success"):
            result_data = data.get("result_data", {})
            
            # Handle array results
            if "results" in result_data:
                for item in result_data["results"]:
                    if isinstance(item, dict):
                        for key in ["file_path", "type", "description"]:
                            if key in item:
                                print(f"{key.title()}: {item[key]}")
                        if "content" in item:
                            print("\nContent:")
                            print(item["content"])
                        print("-" * 80)
                    else:
                        print(item)
                        print("-" * 80)
            else:
                # Handle single result
                print(result_data)
        else:
            print(f"Error: {data.get('error', 'Unknown error')}")
            
    except Exception as e:
        logger.error("output.format_failed", error=str(e))
        print(str(data))

@flow(name="agent_test")
def run_test_flow(
    agent_type: str,
    config_path: str,
    extra_params: Optional[Dict[str, Any]] = None
) -> Dict[str, Any]:
    """Test flow for running individual agents"""
    try:
        # Load config
        config = load_configs(config_path)
        
        # Get agent task config
        if agent_type not in AGENT_REGISTRY:
            raise ValueError(f"Unsupported agent type: {agent_type}")
            
        task_config = AGENT_REGISTRY[agent_type](config)
        
        # Build context
        context = {"input_data": config.get("input_data", {})}
        if extra_params:
            context.update(extra_params)
            
        # Run agent task
        result = run_agent_task(
            agent_config=task_config,
            context=context,
            task_name=f"test_{agent_type}"
        )
        
        # Display result
        format_output(result)
        
        return result
        
    except Exception as e:
        logger.error("test_flow.failed", error=str(e))
        return {
            "success": False,
            "error": str(e),
            "result_data": {}
        }

def main():
    parser = argparse.ArgumentParser(
        description="Prefect test runner for agents/skills"
    )
    parser.add_argument(
        "agent_type",
        choices=AGENT_REGISTRY.keys(),
        help="Type of agent/skill to test"
    )
    parser.add_argument(
        "--config",
        required=True,
        help="Path to YAML config file"
    )
    parser.add_argument(
        "--log",
        type=LogMode,
        choices=list(LogMode),
        default=LogMode.NORMAL,
        help="Logging mode"
    )
    parser.add_argument(
        "--param",
        action="append",
        help="Additional parameters in key=value format",
        default=[]
    )
    
    args = parser.parse_args()
    
    try:
        # Parse additional parameters
        extra_params = {}
        for param in args.param:
            key, value = param.split("=", 1)
            extra_params[key.strip()] = value.strip()

        # Run test flow
        result = run_test_flow(
            agent_type=args.agent_type,
            config_path=args.config,
            extra_params=extra_params
        )
        
        if not result["success"]:
            sys.exit(1)
            
    except Exception as e:
        logger.error("runner.failed", error=str(e))
        sys.exit(1)

if __name__ == "__main__":
    main()