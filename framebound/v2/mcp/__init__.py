"""MCP adapter: same schemas/service functions as HTTP (official SDK, stdio)."""
from .server import build_server, TOOLS
__all__ = ["build_server", "TOOLS"]
