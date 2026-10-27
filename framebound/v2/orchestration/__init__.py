"""Bounded Spark runtime controller: budgets and state in app code, never in prompts."""
from .loop import BoundedLoop, LoopConfig
__all__ = ["BoundedLoop", "LoopConfig"]
