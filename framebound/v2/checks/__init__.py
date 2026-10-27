"""v2 deterministic check registry. Measured evidence only; guesses stay advisory elsewhere."""
from .registry import CHECKS, CheckSpec, get_check, register
__all__ = ["CHECKS", "CheckSpec", "get_check", "register"]
