"""Meta provider adapters: recording first, honesty always, generation outside playback."""
from .base import Capability, discover, retry_transient
from . import image, spark, sam, ledger
__all__ = ["Capability", "discover", "retry_transient", "image", "spark", "sam", "ledger"]
