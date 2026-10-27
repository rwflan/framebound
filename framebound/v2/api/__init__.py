"""HTTP API + event stream over the same application services (read-only transports for models)."""
from .app import create_app
__all__ = ["create_app"]
