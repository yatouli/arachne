"""Web UI package for Arachne.

A dependency-light (Flask) local dashboard::

    from arachne.web.server import run_server
    run_server(host="127.0.0.1", port=8000)   # opens your browser

or from the CLI::

    arachne ui
"""

from .server import create_app, run_server

__all__ = ["create_app", "run_server"]
