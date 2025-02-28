"""
Logging utilities for c4h_services.
Path: c4h_services/src/utils/logging.py
"""

from typing import Any, Dict, Optional
import structlog
from c4h_services.src.utils.string_utils import truncate_log_string

def truncate_strings_processor(config: Optional[Dict[str, Any]] = None):
    """
    Create a structlog processor that truncates string values.
    
    Args:
        config: Configuration dictionary with truncation settings
        
    Returns:
        Processor function for structlog
    """
    def processor(logger, method_name, event_dict):
        """Process event dict, truncating string values."""
        # Don't truncate the event name
        for key, value in list(event_dict.items()):
            if key != "event":
                event_dict[key] = truncate_log_string(value, config)
        return event_dict
    return processor

def get_logger(config: Optional[Dict[str, Any]] = None) -> structlog.BoundLogger:
    """
    Get a logger that truncates string values in structured logs.
    
    Args:
        config: Configuration dictionary with truncation settings
        
    Returns:
        Configured structlog logger
    """
    # Create a logger with the truncate processor
    logger = structlog.wrap_logger(
        structlog.get_logger(),
        processors=[
            truncate_strings_processor(config),
            structlog.processors.add_log_level,
        ]
    )
    return logger