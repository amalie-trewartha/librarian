"""Shelly dash (web viewer) backend."""

from pathlib import Path


def create_app_from_env():
    """App factory for uvicorn --reload (needs an import string)."""
    from shelly_web.env import getenv
    from shelly_web.server import create_app

    root = Path(getenv("SHELLY_WEB_ROOT", ".")).resolve()
    static = getenv("SHELLY_WEB_STATIC")
    read_only = getenv("SHELLY_WEB_READONLY", "") not in ("", "0")
    return create_app(root, Path(static) if static else None, read_only=read_only)


__all__ = ["create_app_from_env"]
