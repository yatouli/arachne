"""The Arachne engine: auto-match a plugin by URL and scrape."""

import os

from arachne.engine import Arachne

# `plugins/` holds the example site plugins; load them all.
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
engine = Arachne(plugin_dirs=[os.path.join(ROOT, "plugins")])

print("Registered plugins:")
for plugin in engine.plugins:
    print(f"  {plugin.name:16s} domains={plugin.domains}")

# A URL that matches HackerNewsPlugin will be parsed automatically.
items = engine.scrape("https://news.ycombinator.com")
print("\nScraped items:")
print(items if isinstance(items, list) else type(items).__name__)
