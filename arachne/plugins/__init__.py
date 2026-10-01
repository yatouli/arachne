"""Plugin system package."""

from .base import SitePlugin, plugin
from .registry import (
    PluginRegistry,
    default_registry,
    discover_directory,
    discover_entry_points,
    load_all,
)

__all__ = [
    "SitePlugin",
    "plugin",
    "PluginRegistry",
    "default_registry",
    "discover_directory",
    "discover_entry_points",
    "load_all",
]
