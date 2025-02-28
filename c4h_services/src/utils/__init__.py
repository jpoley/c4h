"""
Utility functions for c4h_services.
Path: c4h_services/src/utils/__init__.py
"""

from c4h_services.src.utils.logging import get_logger
from c4h_services.src.utils.string_utils import truncate_log_string

__all__ = ["get_logger", "truncate_log_string"]