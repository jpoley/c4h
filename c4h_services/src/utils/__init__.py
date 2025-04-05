"""
Utility functions for c4h_services.
Path: c4h_services/src/utils/__init__.py
"""

from c4h_services.src.utils.logging import get_logger
# Import directly from c4h_agents instead of removed string_utils
from c4h_agents.utils.logging import truncate_log_string

__all__ = ["get_logger", "truncate_log_string"]