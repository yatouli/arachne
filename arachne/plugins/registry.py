"""Plugin registry & discovery."""

from __future__ import annotations

from typing import Iterable, Optional, Type

from ..exceptions import PluginError
from ..log import get_logger
from .base import SitePlugin

logger = get_logger("plugins")


class PluginRegistry:
    """Holds registered site plugins and selects the best one for a URL."""

    def __init__(self):
        self._plugins: dict[str, Type[SitePlugin]] = {}

    def register(self, plugin_cls: Type[SitePlugin], name: Optional[str] = None) -> Type[SitePlugin]:
        if not isinstance(plugin_cls, type) or not issubclass(plugin_cls, SitePlugin):
            raise PluginError(f"{plugin_cls!r} is not a SitePlugin subclass")
        key = name or plugin_cls.name or plugin_cls.__name__
        if not key:
            raise PluginError("plugin has no name")
        self._plugins[key] = plugin_cls
        logger.debug("registered plugin %r", key)
        return plugin_cls

    def unregister(self, name: str) -> None:
        self._plugins.pop(name, None)

    def get(self, name: str) -> Optional[Type[SitePlugin]]:
        return self._plugins.get(name)

    def all(self) -> list[Type[SitePlugin]]:
        return sorted(self._plugins.values(), key=lambda p: (-p.priority, p.name))

    def names(self) -> list[str]:
        return sorted(self._plugins.keys())

    def match(self, url: str) -> Optional[Type[SitePlugin]]:
        """Return the highest-priority plugin whose ``match(url)`` is true."""
        best: Optional[Type[SitePlugin]] = None
        for plugin_cls in self._plugins.values():
            try:
                matched = plugin_cls.match(url)
            except Exception:  # noqa: BLE001
                matched = False
            if matched and (best is None or plugin_cls.priority > best.priority):
                best = plugin_cls
        return best

    def __len__(self) -> int:
        return len(self._plugins)

    def __iter__(self):
        return iter(self.all())


#: The process-wide default registry used by the ``@plugin`` decorator and
#: the ``Arachne`` engine unless a custom registry is supplied.
default_registry = PluginRegistry()


def discover_entry_points(group: str = "arachne.plugins") -> list[Type[SitePlugin]]:
    """Import plugins registered via ``pyproject.toml`` entry points."""
    found: list[Type[SitePlugin]] = []
    try:
        from importlib.metadata import entry_points
    except ImportError:  # pragma: no cover
        return found
    try:
        eps = entry_points(group=group)
    except TypeError:  # pragma: no cover - Python 3.9 compat
        eps = entry_points().get(group, [])
    for ep in eps:
        try:
            module = ep.load()
        except Exception as exc:  # noqa: BLE001
            logger.warning("failed to load entry point %s: %s", ep.name, exc)
            continue
        found.extend(_collect(module))
    return found


def discover_directory(path: str) -> list[Type[SitePlugin]]:
    """Import every ``*.py`` file under ``path`` and collect SitePlugins."""
    import importlib.util
    import os
    import sys

    found: list[Type[SitePlugin]] = []
    path = os.path.abspath(path)
    if not os.path.isdir(path):
        return found
    for filename in sorted(os.listdir(path)):
        if not filename.endswith(".py") or filename.startswith("_"):
            continue
        module_path = os.path.join(path, filename)
        module_name = f"_arachne_plugin_{os.path.splitext(filename)[0]}"
        try:
            spec = importlib.util.spec_from_file_location(module_name, module_path)
            if spec is None or spec.loader is None:
                continue
            module = importlib.util.module_from_spec(spec)
            sys.modules[module_name] = module
            spec.loader.exec_module(module)
        except Exception as exc:  # noqa: BLE001
            logger.warning("failed to import plugin file %s: %s", filename, exc)
            continue
        found.extend(_collect(module))
    return found


def _collect(module) -> list[Type[SitePlugin]]:
    found: list[Type[SitePlugin]] = []
    for attr in vars(module).values():
        if isinstance(attr, type) and issubclass(attr, SitePlugin) and attr is not SitePlugin:
            if attr.__module__ == module.__name__:
                found.append(attr)
    return found


def load_all(
    registry: Optional[PluginRegistry] = None,
    *,
    directories: Optional[Iterable[str]] = None,
    group: str = "arachne.plugins",
) -> PluginRegistry:
    """Load plugins from entry points + directories into ``registry``."""
    registry = default_registry if registry is None else registry
    for plugin_cls in discover_entry_points(group):
        registry.register(plugin_cls)
    for directory in directories or []:
        for plugin_cls in discover_directory(directory):
            registry.register(plugin_cls)
    return registry
