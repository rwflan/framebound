"""MCP adapter: same schemas/service functions as HTTP (official SDK, stdio)."""
from .server import build_server
__all__ = ["build_server"]
