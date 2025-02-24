"""
Configuration handling with robust dictionary access and path resolution.
Path: c4h_agents/config.py
"""
import yaml
from typing import Dict, Any, Optional, List, Tuple, Union
from pathlib import Path
import structlog
from copy import deepcopy
import collections.abc
import json

logger = structlog.get_logger()

def get_by_path(data: Dict[str, Any], path: List[str]) -> Any:
    """
    Access dictionary data using a path list.
    
    Args:
        data: Dictionary to traverse
        path: List of keys forming the path
        
    Returns:
        Value at path or None if not found
    """
    try:
        current = data
        for key in path:
            if isinstance(current, dict):
                if key not in current:
                    return None
                current = current[key]
            elif isinstance(current, str):
                try:
                    parsed = json.loads(current)
                    if isinstance(parsed, dict) and key in parsed:
                        current = parsed[key]
                    else:
                        return None
                except json.JSONDecodeError:
                    return None
            else:
                return None
        return current
    except Exception as e:
        logger.error("config.path_access_failed", path=path, error=str(e))
        return None

def get_value(data: Dict[str, Any], path_str: str) -> Any:
    """
    Access dictionary data using a hierarchical path string (e.g. "system/runid").
    
    Args:
        data: Dictionary to traverse
        path_str: Slash-delimited key path
        
    Returns:
        Value at the specified path or None if not found.
    """
    path_list = path_str.split("/")
    return get_by_path(data, path_list)

def locate_keys(data: Dict[str, Any], target_keys: List[str], current_path: List[str] = None) -> Dict[str, Tuple[Any, List[str]]]:
    """
    Locate multiple keys in dictionary using hierarchy tracking.
    
    Args:
        data: Dictionary to search
        target_keys: List of keys to find
        current_path: Path for logging (internal use)
        
    Returns:
        Dict mapping found keys to (value, path) tuples
    """
    try:
        results = {}
        current_path = current_path or []
        if isinstance(data, dict):
            for key in target_keys:
                if key in data:
                    value = data[key]
                    path = current_path + [key]
                    if isinstance(value, str):
                        try:
                            parsed = json.loads(value)
                            value = parsed
                        except json.JSONDecodeError:
                            pass
                    results[key] = (value, path)
                    logger.debug("config.key_located", key=key, path=path, found_type=type(value).__name__)
            for k, v in data.items():
                if isinstance(v, (dict, list)):
                    child_results = locate_keys(v, [k for k in target_keys if k not in results], current_path + [k])
                    results.update(child_results)
        elif isinstance(data, list):
            for i, item in enumerate(data):
                if isinstance(item, (dict, list)):
                    child_results = locate_keys(item, [k for k in target_keys if k not in results], current_path + [str(i)])
                    results.update(child_results)
        found_keys = set(results.keys())
        missing_keys = set(target_keys) - found_keys
        if missing_keys:
            logger.debug("config.keys_not_found", keys=list(missing_keys), searched_path=current_path)
        return results
    except Exception as e:
        logger.error("config.locate_keys_failed", target_keys=target_keys, current_path=current_path, error=str(e))
        return {}

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
        standard_path = ['llm_config', 'agents', target_name]
        result = get_by_path(config, standard_path)
        if result is not None:
            if isinstance(result, dict):
                logger.debug("config.located_in_hierarchy", target=target_name, path=standard_path, found_keys=list(result.keys()))
                return result
        logger.warning("config.not_found_in_hierarchy", target=target_name, searched_path=standard_path)
        return {}
    except Exception as e:
        logger.error("config.locate_failed", target=target_name, error=str(e))
        return {}

def deep_merge(base: Dict[str, Any], override: Dict[str, Any]) -> Dict[str, Any]:
    """
    Deep merge dictionaries preserving hierarchical structure.
    
    Rules:
    1. Preserve llm_config.agents hierarchy.
    2. Override values take precedence.
    3. Dictionaries merged recursively.
    4. Lists from override replace lists from base.
    5. None values in override delete keys from base.
    6. Runtime values merged into agent configs.
    
    Args:
        base: Base configuration dictionary
        override: Override configuration dictionary
        
    Returns:
        Merged configuration dictionary
    """
    result = deepcopy(base)
    try:
        logger.debug("config.merge.starting", base_keys=list(base.keys()), override_keys=list(override.keys()), project_settings=override.get('project', {}))
        if 'llm_config' in result or 'llm_config' in override:
            system_keys = {'providers', 'llm_config', 'project', 'backup', 'logging', 'system'}
            runtime_keys = {k for k in override.keys() if k not in system_keys}
            if runtime_keys and 'llm_config' in result:
                agent_configs = result['llm_config'].get('agents', {})
                for agent_name, agent_config in agent_configs.items():
                    for key in runtime_keys:
                        if key not in agent_config:
                            logger.debug("config.merge.runtime_value", agent=agent_name, key=key, value=override[key])
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
        logger.debug("config.merge.complete", result_keys=list(result.keys()), project_path=result.get('project', {}).get('path'))
        return result
    except Exception as e:
        logger.error("config.merge.failed", error=str(e), keys_processed=list(override.keys()))
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
        logger.info("config.load.success", path=str(path), keys=list(config.keys()), size=len(str(config)))
        return config
    except yaml.YAMLError as e:
        logger.error("config.load.yaml_error", path=str(path), error=str(e), line=getattr(e, 'line', None), column=getattr(e, 'column', None))
        return {}
    except Exception as e:
        logger.error("config.load.failed", path=str(path), error=str(e), error_type=type(e).__name__)
        return {}

def load_with_app_config(system_path: Path, app_path: Path) -> Dict[str, Any]:
    """Load and merge system config with app config with full logging"""
    try:
        logger.info("config.merge.starting", system_path=str(system_path), app_path=str(app_path))
        system_config = load_config(system_path)
        app_config = load_config(app_path)
        result = deep_merge(system_config, app_config)
        logger.info("config.merge.complete", total_keys=len(result), system_keys=len(system_config), app_keys=len(app_config))
        return result
    except Exception as e:
        logger.error("config.merge.failed", error=str(e), error_type=type(e).__name__)
        return {}
