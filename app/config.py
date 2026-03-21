"""
App-level config re-export. Import `get_settings` from here or from `app.core.config`.
"""

from app.core.config import Settings, get_settings

__all__ = ("Settings", "get_settings")
