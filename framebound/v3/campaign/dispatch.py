"""Specialist protocol. Adapters receive an immutable request, never authority."""
from dataclasses import dataclass
import time
from typing import Protocol

from .ledger import Ledger


@dataclass(frozen=True)
class Response:
    raw: bytes
    incurred: int
    successful_images: int
    receipt: dict


class Specialist(Protocol):
    def execute(self, request: dict, *, timeout: int) -> Response: ...


def dispatch(ledger: Ledger, request_id: str, specialist: Specialist):
    permit = ledger.claim(request_id)
    request = ledger.start_wire(request_id, permit)
    start = time.monotonic()
    try:
        response = specialist.execute(request, timeout=ledger.config(request['campaign']).limits.request_timeout)
        return ledger.receive(request_id, response.raw, incurred=response.incurred,
                              successful_images=response.successful_images, provider_receipt=response.receipt)
    except BaseException:
        # Includes process cancellation. Reserve remains held after possible acceptance.
        ledger.unknown(request_id, 'execution interrupted or response unavailable; reconcile with provider')
        raise
    finally:
        ledger.add_active_time(request['campaign'], request['case_id'], time.monotonic()-start)
