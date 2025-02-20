"""
Extended Prefect runner supporting both individual agents and full workflow execution.
Path: c4h_services/examples/prefect_runner.py
"""

import sys
from pathlib import Path
from typing import Dict, Any, Optional, Literal, List
import structlog
import argparse
from prefect import flow
from rich.console import Console
import yaml
from enum import Enum

# Add source directories to path BEFORE any c4h imports
root_dir = Path(__file__).parent.parent.parent
sys.path.append(str(root_dir))

# Now import c4h packages
from c4h_agents.config import deep_merge
from c4h_agents.agents.discovery import DiscoveryAgent
from c4h_agents.agents.solution_designer import SolutionDesigner
from c4h_agents.agents.coder import Coder
from c4h_agents.agents.assurance import AssuranceAgent
from c4h_agents.skills.semantic_iterator import SemanticIterator
from c4h_agents.skills.semantic_merge import SemanticMerge
from c4h_agents.skills.semantic_extract import SemanticExtract
from c4h_agents.skills.asset_manager import AssetManager
from c4h_services.src.intent.impl.prefect.workflows import run_basic_workflow  # Added missing import
from c4h_services.src.intent.impl.prefect.tasks import run_agent_task, AgentTaskConfig

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
    "discovery": lambda config: AgentTaskConfig(
        agent_class=DiscoveryAgent,
        config=config,
        task_name="discovery"
    ),
    "solution_designer": lambda config: AgentTaskConfig(
        agent_class=SolutionDesigner,
        config=config,
        task_name="solution_designer"
    ),
    "coder": lambda config: AgentTaskConfig(
        agent_class=Coder,
        config=config,
        task_name="coder"
    ),
    "assurance": lambda config: AgentTaskConfig(
        agent_class=AssuranceAgent,
        config=config,
        task_name="assurance"
    ),
    
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

def load_configs(app_config_path: str, system_config_paths: Optional[List[str]] = None) -> Dict[str, Any]:
    """Load and merge configurations in proper order"""
    try:
        # Load application config first
        with open(app_config_path) as f:
            app_config = yaml.safe_load(f) or {}
            
        logger.info("config.content.loaded",
                   app_config_keys=list(app_config.keys()),
                   project_path=app_config.get('project', {}).get('path'))
        
        # Start with empty base config
        merged_config = {}
        
        # Process system configs in order if provided
        if system_config_paths:
            for sys_path in system_config_paths:
                path = Path(sys_path)
                if not path.exists():
                    logger.warning("config.system_config.not_found", path=str(path))
                    continue
                    
                with open(path) as f:
                    sys_config = yaml.safe_load(f) or {}
                    logger.debug("config.merge.system_config",
                               path=str(path),
                               config_keys=list(sys_config.keys()))
                    merged_config = deep_merge(merged_config, sys_config)
                    
        # If no system configs provided or found, check default locations
        elif not merged_config:
            default_paths = [
                Path("config/system_config.yml"),
                Path("../config/system_config.yml"),
                root_dir / "config" / "system_config.yml"
            ]
            
            logger.info("config.paths.search", 
                cwd=str(Path.cwd()),
                root_dir=str(root_dir),
                sys_paths=[str(p) for p in default_paths],
                config_path=app_config_path
            )
            
            for path in default_paths:
                if path.exists():
                    with open(path) as f:
                        sys_config = yaml.safe_load(f) or {}
                        logger.debug("config.merge.default_system",
                                   path=str(path),
                                   config_keys=list(sys_config.keys()))
                        merged_config = deep_merge(merged_config, sys_config)
                    break
                    
        # Finally merge application config
        final_config = deep_merge(merged_config, app_config)
        
        # Ensure llm_config exists at root
        if 'llm_config' not in final_config:
            logger.warning("config.no_llm_config_found",
                         final_keys=list(final_config.keys()))
            final_config['llm_config'] = {}
            
        return final_config

    except Exception as e:
        logger.error("config.load_failed", error=str(e))
        raise

"""
Path: c4h_services/examples/prefect_runner.py
Update to ensure lineage configuration is properly propagated in the run_flow function
"""

@flow(name="prefect_runner")
def run_flow(
    mode: RunMode,
    config: Dict[str, Any],
    agent_type: Optional[str] = None,
    extra_params: Optional[Dict[str, Any]] = None
) -> Dict[str, Any]:
    """Main flow for running agents or workflows"""
    try:
        # Resolve project paths first
        if 'project' in config:
            project_config = config['project']
            if 'path' in project_config:
                project_path = Path(project_config['path']).resolve()
                project_config['path'] = str(project_path)
                
                # Resolve workspace root relative to project path if not absolute
                workspace_root = project_config.get('workspace_root')
                if workspace_root and not Path(workspace_root).is_absolute():
                    project_config['workspace_root'] = str(project_path / workspace_root)
                    
                logger.info("runner.project.paths",
                    project_path=str(project_path),
                    workspace_root=project_config.get('workspace_root'))
        
        # Prepare context with workflow run ID for lineage tracking
        context = {"input_data": config.get("input_data", {})}
        
        # Add project context if available
        if 'project' in config:
            context['project'] = config['project']
            
        # Ensure runtime configuration is properly set
        if 'runtime' in config:
            runtime_config = config['runtime']
            if 'lineage' in runtime_config:
                lineage_config = runtime_config['lineage']
                # If lineage is enabled but no workflow_id is specified, use flow_run_id
                if lineage_config.get('enabled', False):
                    flow_id = None
                    try:
                        from prefect.runtime import flow_run
                        flow_id = flow_run.get_id()
                    except Exception:
                        # Fallback if prefect runtime not available
                        pass
                        
                    if flow_id:
                        context['workflow_run_id'] = str(flow_id)
                        logger.info("lineage.context_enhanced",
                                  workflow_run_id=context['workflow_run_id'])
            
        # Add any extra parameters
        if extra_params:
            context.update(extra_params)

        if mode == RunMode.AGENT:
            if not agent_type or agent_type not in AGENT_REGISTRY:
                raise ValueError(f"Invalid agent type: {agent_type}")
                
            # Run single agent
            task_config = AGENT_REGISTRY[agent_type](config)
                
            result = run_agent_task(
                agent_config=task_config,
                context=context,
                task_name=f"test_{agent_type}"
            )
            return {
                "success": True,
                "result": result.result() if hasattr(result, "result") else result
            }
        else:
            # Run workflow using project path from config if available
            project_path = config.get('project', {}).get('path')
            if not project_path:
                project_path = config.get("project_path", ".")
            
            result = run_basic_workflow(
                project_path=Path(project_path),
                intent_desc=config.get("intent", {}),
                config=config
            )
            
            # Extract result from Prefect State
            if hasattr(result, "result"):
                workflow_result = result.result()
            else:
                workflow_result = result
                
            return {
                "success": True,
                "result": workflow_result
            }
            
    except Exception as e:
        logger.error("runner.failed", error=str(e))
        return {
            "success": False,
            "error": str(e),
            "result": {}
        }

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
        # Handle successful workflow completion
        if mode == RunMode.WORKFLOW:
            if isinstance(data, str):
                print(data)
                return
                
            result = data.result() if hasattr(data, 'result') else data
            if isinstance(result, dict) and 'result' in result:
                result_data = result['result']
            elif isinstance(result, dict) and 'stages' in result:
                result_data = {
                    'status': 'success',
                    'changes': result.get('changes', []),
                    'stages': result.get('stages', {})
                }
            else:
                result_data = result
                
        else:  # Agent mode
            # Extract result data handling different formats
            if isinstance(data, dict):
                if 'success' in data and data['success']:
                    # Handle semantic iterator specific results
                    if 'result' in data and isinstance(data['result'], dict):
                        agent_data = data['result']
                        if 'result_data' in agent_data:
                            # Standard agent format
                            result_data = agent_data['result_data']
                        else:
                            # Direct result data
                            result_data = agent_data
                    else:
                        # Direct result format
                        result_data = data.get('result_data', data.get('result', {}))
                else:
                    result_data = {'error': data.get('error', 'Unknown error')}
            else:
                result_data = data

        # Print all result data with consistent indentation
        print_value(result_data)
            
    except Exception as e:
        logger.error("output.format_failed", error=str(e))
        print(f"Error formatting output: {str(e)}")
        print("Raw data:")
        print(str(data))

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
        help="Path to application config file"
    )
    parser.add_argument(
        "--system-configs",
        nargs="+",
        help="Optional system config files in merge order"
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

        # Load config with new system config handling
        config = load_configs(
            app_config_path=args.config,
            system_config_paths=args.system_configs
        )

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