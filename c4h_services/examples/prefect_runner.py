"""
Extended Prefect runner supporting both individual agents and full workflow execution.
Path: c4h_services/examples/prefect_runner.py
"""

import sys
from pathlib import Path
from typing import Dict, Any, Optional, Literal
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

from c4h_services.src.intent.impl.prefect.tasks import AgentTaskConfig, run_agent_task
from c4h_services.src.intent.impl.prefect.workflows import run_basic_workflow
from c4h_services.src.intent.impl.prefect.factories import (
    create_discovery_task,
    create_solution_task,
    create_coder_task,
    create_assurance_task
)

logger = structlog.get_logger()

class RunMode(str, Enum):
    """Execution modes supported by runner"""
    AGENT = "agent"     # Run single agent/skill
    WORKFLOW = "workflow"  # Run full workflow

class LogMode(str, Enum):
    """Logging modes supported by runner"""
    DEBUG = "debug"     
    NORMAL = "normal"   

# Agent registry for individual runs
AGENT_REGISTRY = {
    # Core Agents
    "discovery": lambda config: create_discovery_task(config),
    "solution_designer": lambda config: create_solution_task(config),
    "coder": lambda config: create_coder_task(config),
    "assurance": lambda config: create_assurance_task(config),
    
    # Semantic Skills
    "semantic_iterator": lambda config: AgentTaskConfig(
        agent_class=SemanticIterator,
        config={
            **config,  # Base config
            "instruction": config.get('instruction', ''),
            "format": config.get('format', 'json'),
        },
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

def format_output(data: Dict[str, Any], mode: RunMode) -> None:
    """Format task output for display"""
    print("\n=== Results ===\n")
    
    def print_value(value: Any, indent: int = 0) -> None:
        """Print a value, preserving formatting"""
        spaces = " " * indent
        if isinstance(value, dict):
            for k, v in value.items():
                print(f"{spaces}{k}:")
                print_value(v, indent + 4)
        elif isinstance(value, list):
            for item in value:
                print_value(item, indent + 4)
        else:
            # Print string with original formatting
            print(f"{spaces}{value}")
    
    try:
        if data.get("success", False):
            # Print all result data with consistent indentation
            result_data = data.get("result_data", {})
            print_value(result_data)
        else:
            print(f"Error: {data.get('error', 'Unknown error')}")
            
    except Exception as e:
        logger.error("output.format_failed", error=str(e))
        print(str(data))

@flow(name="prefect_runner")
def run_flow(
    mode: RunMode,
    config: Dict[str, Any],
    agent_type: Optional[str] = None,
    extra_params: Optional[Dict[str, Any]] = None
) -> Dict[str, Any]:
    """Main flow for running agents or workflows"""
    try:
        if mode == RunMode.AGENT:
            if not agent_type or agent_type not in AGENT_REGISTRY:
                raise ValueError(f"Invalid agent type: {agent_type}")
                
            # Run single agent
            task_config = AGENT_REGISTRY[agent_type](config)
            context = {"input_data": config.get("input_data", {})}
            if extra_params:
                context.update(extra_params)
                
            return run_agent_task(
                agent_config=task_config,
                context=context,
                task_name=f"test_{agent_type}"
            )
        else:
            # Run full workflow
            return run_basic_workflow(
                project_path=Path(config.get("project_path", ".")),
                intent_desc=config.get("intent", {}),
                config=config
            )
            
    except Exception as e:
        logger.error("runner.failed", error=str(e))
        return {
            "success": False,
            "error": str(e),
            "result_data": {}
        }

def main():
    parser = argparse.ArgumentParser(
        description="Prefect runner for agents and workflows"
    )
    parser.add_argument(
        "mode",
        type=RunMode,
        choices=list(RunMode),
        help="Run mode (agent or workflow)"
    )
    # Define agent groups for better help display
    agent_choices = list(AGENT_REGISTRY.keys())
    parser.add_argument(
        "--agent",
        choices=agent_choices,
        metavar="AGENT",
        help=f"""Agent type (required for agent mode). Available agents:
                Core Agents: {', '.join(a for a in agent_choices if not a.startswith('semantic_'))}
                Semantic Skills: {', '.join(a for a in agent_choices if a.startswith('semantic_'))}
                Other Skills: {', '.join(a for a in agent_choices if not a.startswith('semantic_') and a not in ['discovery', 'solution_designer', 'coder', 'assurance'])}"""
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
        if args.mode == RunMode.AGENT and not args.agent:
            parser.error("Agent type is required for agent mode")
            
        # Parse additional parameters
        extra_params = {}
        for param in args.param:
            key, value = param.split("=", 1)
            extra_params[key.strip()] = value.strip()

        # Load config
        config = load_configs(args.config)

        # Run flow
        result = run_flow(
            mode=args.mode,
            config=config,
            agent_type=args.agent,
            extra_params=extra_params
        )
        
        # Display results
        format_output(result, args.mode)
        
        if not result.get("success", False):
            sys.exit(1)
            
    except Exception as e:
        logger.error("runner.failed", error=str(e))
        sys.exit(1)

if __name__ == "__main__":
    main()