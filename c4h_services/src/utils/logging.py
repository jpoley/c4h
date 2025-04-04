"""
Logging utilities for c4h_services.
Path: c4h_services/src/utils/logging.py
"""

from typing import Any, Dict, Optional
import structlog
# Import directly from c4h_agents logging utility
from c4h_agents.utils.logging import get_logger, truncate_log_string, initialize_logging_config

# Re-export the functions to maintain API compatibility
__all__ = ['get_logger', 'truncate_log_string', 'initialize_logging_config']