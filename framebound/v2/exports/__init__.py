"""Portable training snapshots: honest labels, standard loaders, split/rights policies."""
from .snapshot import build_snapshot
from .validate import validate_snapshot
__all__ = ["build_snapshot", "validate_snapshot"]
