"""
Configuration handling with robust dictionary merging and comprehensive logging.
Path: src/config.py
"""
import yaml
from typing import Dict, Any, Optional, List
from pathlib import Path
import structlog
from copy import deepcopy
import collections.abc

logger = structlog.get_logger()

def locate_config(config: Dict[str, Any], target_name: str) -> Dict[str, Any]:
    """
    Locate configuration using strict hierarchical path.
    Primary path is always llm_config.agents.[name]
    
    Args:
        config: Configuration dictionary
        target_name: Name of target agent/component
        
    Returns:
        Located config dictionary or empty dict if not found
    """
    try:
        # Use standard hierarchical path
        if 'llm_config' in config:
            agents_config = config['llm_config'].get('agents', {})
            if target_name in agents_config:
                agent_config = agents_config[target_name]
                logger.debug("config.located_in_hierarchy", 
                           target=target_name,
                           path=['llm_config', 'agents', target_name],
                           found_keys=list(agent_config.keys()))
                return agent_config

        logger.warning("config.not_found_in_hierarchy",
                      target=target_name,
                      searched_path=['llm_config', 'agents', target_name])
        return {}

    except Exception as e:
        logger.error("config.locate_failed",
                    target=target_name,
                    error=str(e))
        return {}

def deep_merge(base: Dict[str, Any], override: Dict[str, Any]) -> Dict[str, Any]:
    """
    Deep merge dictionaries preserving hierarchical structure.
    
    Rules:
    1. Preserve llm_config.agents hierarchy
    2. Override values take precedence
    3. Dictionaries merged recursively
    4. Lists from override replace lists from base
    5. None values in override delete keys from base
    6. Runtime values merged into agent configs
    
    Args:
        base: Base configuration dictionary
        override: Override configuration dictionary
        
    Returns:
        Merged configuration dictionary
    """
    result = deepcopy(base)
    
    try:
        # Handle root level merge
        if 'llm_config' in result or 'llm_config' in override:
            # Identify system vs runtime keys
            system_keys = {'providers', 'llm_config', 'project', 'backup', 'logging'}
            runtime_keys = {k for k in override.keys() if k not in system_keys}
            
            # Map runtime values to agent configs if llm_config exists
            if runtime_keys and 'llm_config' in result:
                agent_configs = result['llm_config'].get('agents', {})
                for agent_name, agent_config in agent_configs.items():
                    # Copy runtime values that aren't overridden
                    for key in runtime_keys:
                        if key not in agent_config:
                            logger.debug("config.merge.runtime_value",
                                       agent=agent_name,
                                       key=key,
                                       value=override[key])
                            agent_config[key] = deepcopy(override[key])

        for key, value in override.items():
            if value is None:
                result.pop(key, None)
                continue
                
            if key not in result:
                result[key] = deepcopy(value)
                continue
                
            if isinstance(value, collections.abc.Mapping):
                result[key] = deep_merge(result[key], value)
            elif isinstance(value, Path):
                result[key] = str(value)
            else:
                result[key] = deepcopy(value)
            
        return result

    except Exception as e:
        logger.error("config.merge.failed", 
                    error=str(e),
                    keys_processed=list(override.keys()))
        raise

def load_config(path: Path) -> Dict[str, Any]:
    """Load configuration from YAML file with comprehensive logging"""
    try:
        logger.info("config.load.starting", path=str(path))
        
        if not path.exists():
            logger.error("config.load.file_not_found", path=str(path))
            return {}
            
        with open(path) as f:
            config = yaml.safe_load(f) or {}
            
        logger.info("config.load.success",
                   path=str(path),
                   keys=list(config.keys()),
                   size=len(str(config)))
                   
        return config
        
    except yaml.YAMLError as e:
        logger.error("config.load.yaml_error",
                    path=str(path),
                    error=str(e),
                    line=getattr(e, 'line', None),
                    column=getattr(e, 'column', None))
        return {}
    except Exception as e:
        logger.error("config.load.failed",
                    path=str(path),
                    error=str(e),
                    error_type=type(e).__name__)
        return {}

def load_with_app_config(system_path: Path, app_path: Path) -> Dict[str, Any]:
    """Load and merge system config with app config with full logging"""
    try:
        logger.info("config.merge.starting",
                   system_path=str(system_path),
                   app_path=str(app_path))
        
        system_config = load_config(system_path)
        app_config = load_config(app_path)
        
        result = deep_merge(system_config, app_config)
        
        logger.info("config.merge.complete",
                   total_keys=len(result),
                   system_keys=len(system_config),
                   app_keys=len(app_config))
        
        return result
        
    except Exception as e:
        logger.error("config.merge.failed",
                    error=str(e),
                    error_type=type(e).__name__)
        return {}