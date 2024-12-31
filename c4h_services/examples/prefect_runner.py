"""
Prefect-enabled test runner for agents and skills.
Path: c4h_services/examples/prefect_runner.py
"""

import sys
from pathlib import Path
from typing import Dict, Any, Optional, List
import structlog
import argparse
from prefect import task, flow, get_run_logger
from rich.console import Console
import yaml
from enum import Enum

# Add source directories to path
from agents.base import BaseAgent
from agents.coder import Coder
from agents.discovery import DiscoveryAgent
from agents.solution_designer import SolutionDesigner
from agents.assurance import AssuranceAgent
from skills.semantic_iterator import SemanticIterator
from skills.semantic_merge import SemanticMerge
from skills.semantic_extract import SemanticExtract
from skills.asset_manager import AssetManager
from skills.shared.types import ExtractConfig
from config import deep_merge

logger = structlog.get_logger()

# Agent registry
AGENT_TYPES = {
    "coder": Coder,
    "semantic_iterator": SemanticIterator,
    "semantic_merge": SemanticMerge,
    "semantic_extract": SemanticExtract,
    "discovery": DiscoveryAgent,
    "solution_designer": SolutionDesigner,
    "asset_manager": AssetManager
}

class LogMode(str, Enum):
    """Logging modes supported by harness"""
    DEBUG = "debug"     
    NORMAL = "normal"   

def find_system_config() -> Path:
    """Locate system config file"""
    paths = [
        Path("config/system_config.yml"),
        Path("../config/system_config.yml"),
        Path(__file__).parent.parent.parent / "config" / "system_config.yml"
    ]
    
    for path in paths:
        if path.exists():
            return path
            
    raise FileNotFoundError("system_config.yml not found")

def load_config(config_path: str) -> Dict[str, Any]:
    """Load and merge configurations"""
    try:
        # Load system config first
        sys_config_path = find_system_config()
        with open(sys_config_path) as f:
            system_config = yaml.safe_load(f)
            logger.info("config.system_loaded", path=str(sys_config_path))
            
        # Load test-specific config
        with open(config_path) as f:
            test_config = yaml.safe_load(f)
            logger.info("config.test_loaded", path=config_path)

        # Merge configs, test config takes precedence
        config = deep_merge(system_config, test_config)
        
        return config

    except Exception as e:
        logger.error("config.load_failed", error=str(e))
        raise

def parse_param(param_str: str) -> tuple[str, Any]:
    """Parse a parameter string in format key=value"""
    try:
        key, value = param_str.split('=', 1)
        try:
            import ast
            value = ast.literal_eval(value)
        except (ValueError, SyntaxError):
            pass
        return key.strip(), value
    except ValueError:
        raise ValueError(f"Invalid parameter format: {param_str}. Use key=value format")

def format_llm_content(data: Any) -> str:
    """Format LLM response content for display.
    
    Handles:
    - ModelResponse objects
    - Raw text
    - Dictionary with nested content
    - Escaped multiline strings
    """
    try:
        # Handle ModelResponse objects
        if hasattr(data, 'choices') and data.choices:
            data = data.choices[0].message.content
            
        # Handle dictionary responses
        if isinstance(data, dict):
            # Look for common content fields
            for key in ['content', 'response', 'text', 'result']:
                if key in data:
                    data = data[key]
                    break
        
        # Convert to string
        content = str(data)
        
        # Handle escaped newlines and indentation
        content = content.replace('\\n', '\n')
        content = content.replace('\\t', '\t')
        content = content.replace('\\"', '"')
        
        # Strip any markdown code block markers
        if content.startswith('```') and content.endswith('```'):
            content = '\n'.join(content.split('\n')[1:-1])
            
        return content
        
    except Exception as e:
        logger.error("display.format_failed", error=str(e))
        return str(data)

def display_output(output: Dict[str, Any]) -> None:
    """Display formatted output with robust type handling"""
    print("\n=== Results ===\n")
    
    try:
        # For lists of results
        if isinstance(output, dict) and 'results' in output:
            for item in output['results']:
                # Format each item's content
                if isinstance(item, dict):
                    for key in ['file_path', 'type', 'description']:
                        if key in item:
                            print(f"{key.replace('_', ' ').title()}: {item[key]}\n")
                    
                    if 'content' in item:
                        print("Content:")
                        print(format_llm_content(item['content']))
                    print("-" * 80)
                else:
                    print(format_llm_content(item))
        else:
            # Format top-level output
            print(format_llm_content(output))
                    
    except Exception as e:
        logger.error("display.output_failed", error=str(e))
        print(str(output))

@task(retries=2, retry_delay_seconds=10)
def run_agent_task(
    agent_type: str,
    config: Dict[str, Any],
    extra_args: Optional[Dict[str, Any]] = None
) -> Dict[str, Any]:
    """Execute agent/skill as Prefect task"""
    prefect_logger = get_run_logger()
    
    try:
        # Initialize agent with config
        agent_class = AGENT_TYPES[agent_type]
        agent = agent_class(config=config)

        # Handle iterator types specially
        if isinstance(agent, SemanticIterator):
            # Configure iterator
            agent.configure(
                content=config.get('input_data'),
                config=ExtractConfig(
                    instruction=config.get('instruction'),
                    format=config.get('format', 'json')
                )
            )
            
            # Collect all items
            results = []
            for item in agent:
                results.append(item)

            return {
                'success': True,
                'data': {'results': results},  # Match testharness structure
                'error': None
            }
        
        # For non-iterator agents, use standard processing
        context = {'input_data': config.get('input_data', {})}
        if extra_args:
            context.update(extra_args)

        result = agent.process(context)
        return {
            'success': result.success,
            'data': result.data,
            'error': result.error
        }
        
    except Exception as e:
        logger.error("agent_task.failed", 
                    agent_type=agent_type,
                    error=str(e))
        raise

@flow(name="agent_test")
def run_test_flow(
    agent_type: str,
    config_path: str,
    extra_params: Optional[Dict[str, Any]] = None,
    log_mode: LogMode = LogMode.NORMAL
) -> Dict[str, Any]:
    """Main test flow"""
    try:
        # Load merged config
        config = load_config(config_path)
        
        # Execute agent task
        result = run_agent_task(
            agent_type=agent_type,
            config=config,
            extra_args=extra_params
        )
        
        # Display output using same formatting as testharness
        if result['success']:
            display_output(result['data'])
        else:
            print(f"\nError: {result['error']}")
        
        return result
        
    except Exception as e:
        logger.error("test_flow.failed", error=str(e))
        raise

def main():
    parser = argparse.ArgumentParser(
        description="Prefect-enabled test runner for agents/skills"
    )
    parser.add_argument(
        "agent_type",
        choices=AGENT_TYPES.keys(),
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
        for param_str in args.param:
            key, value = parse_param(param_str)
            extra_params[key] = value

        # Run the flow
        result = run_test_flow(
            agent_type=args.agent_type,
            config_path=args.config,
            extra_params=extra_params,
            log_mode=args.log
        )
        
        # Exit with status
        if not result['success']:
            sys.exit(1)
            
    except Exception as e:
        logger.error("runner.failed", error=str(e))
        sys.exit(1)

if __name__ == "__main__":
    main()