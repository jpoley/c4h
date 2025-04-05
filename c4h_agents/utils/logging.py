"""
Central logging utility with configurable truncation.
Path: c4h_agents/utils/logging.py
"""

from typing import Any, Dict, Optional
import structlog
from c4h_agents.config import create_config_node

# Default truncation values
DEFAULT_PREFIX_LENGTH = 50
DEFAULT_SUFFIX_LENGTH = 50

# Global configuration cache
_global_config = {}

def initialize_logging_config(config: Dict[str, Any]) -> None:
    """
    Initialize global logging configuration.
    
    Args:
        config: Complete configuration dictionary
    """
    global _global_config
    _global_config = config.copy() if config else {}

def truncate_log_string(
    value: Any, 
    config: Optional[Dict[str, Any]] = None,
    prefix_len: Optional[int] = None,
    suffix_len: Optional[int] = None
) -> Any:
    """
    Truncate a string value for logging purposes.
    
    Args:
        value: The value to truncate (if it's a string or can be converted to string)
        config: Configuration dictionary to get default lengths
        prefix_len: Length of prefix to show (overrides config)
        suffix_len: Length of suffix to show (overrides config)
        
    Returns:
        Truncated string if input is a string and longer than threshold, 
        otherwise original value
    """
    # Get config values if not provided
    if config:
        config_node = create_config_node(config)
        if prefix_len is None:
            prefix_len = config_node.get_value("logging.truncate.prefix_length") or DEFAULT_PREFIX_LENGTH
        if suffix_len is None:
            suffix_len = config_node.get_value("logging.truncate.suffix_length") or DEFAULT_SUFFIX_LENGTH
    else:
        # Use global config if available, otherwise use defaults
        global _global_config
        if _global_config:
            config_node = create_config_node(_global_config)
            if prefix_len is None:
                prefix_len = config_node.get_value("logging.truncate.prefix_length") or DEFAULT_PREFIX_LENGTH
            if suffix_len is None:
                suffix_len = config_node.get_value("logging.truncate.suffix_length") or DEFAULT_SUFFIX_LENGTH
        else:
            # Default values if no config provided
            prefix_len = prefix_len or DEFAULT_PREFIX_LENGTH
            suffix_len = suffix_len or DEFAULT_SUFFIX_LENGTH
    
    # For complex objects, convert to string first
    if not isinstance(value, str):
        # Handle complex objects that can't be converted to strings safely
        try:
            obj_str = str(value)
        except Exception:
            return value
    else:
        obj_str = value
    
    # Calculate total length
    total_len = prefix_len + suffix_len + 7  # 7 is length of " ..... "
    
    # If string is shorter than threshold, return as is
    if len(obj_str) <= total_len:
        return value  # Return the original value, not the string conversion
    
    # For complex objects, just indicate it's a complex object
    if not isinstance(value, str):
        type_name = type(value).__name__
        return f"<complex value, length={len(obj_str)}, type={type_name}>"
    
    # For actual strings, truncate normally
    return f"{obj_str[:prefix_len]} ..... {obj_str[-suffix_len:]}"

def get_logger(config: Optional[Dict[str, Any]] = None) -> structlog.BoundLogger:
    """
    Get a logger that truncates string values in structured logs.
    
    Args:
        config: Configuration dictionary with truncation settings
        
    Returns:
        Configured structlog logger
    """
    # If config provided, update global config
    if config:
        initialize_logging_config(config)
    
    # Create a processor that will truncate string values
    def truncate_processor(logger, method_name, event_dict):
        """Process event dict, truncating string values."""
        # Don't truncate the event name
        for key, value in list(event_dict.items()):
            if key != "event":
                event_dict[key] = truncate_log_string(value)
        return event_dict
    
    # Create a logger with the truncate processor
    logger = structlog.wrap_logger(
        structlog.get_logger(),
        processors=[
            truncate_processor,
            structlog.processors.add_log_level,
        ]
    )
    return logger