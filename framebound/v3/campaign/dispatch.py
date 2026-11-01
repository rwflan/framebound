"""One paid send; durable acceptance permits only receipt retrieval after a restart."""
from dataclasses import dataclass
import json
import time
from typing import Protocol

from filelock import FileLock

from .contracts import local_path
from .ledger import Ledger, ProviderPending, Stopped


@dataclass(frozen=True)
class Response:
    raw: bytes
    incurred: int
    successful_images: int
    receipt: dict


class ProviderRejected(Exception):
    """Actual documented pre-inference validation response; never a timeout."""
    def __init__(self,response):
        self.response=response
        super().__init__('Provider rejected the request before inference')


class Specialist(Protocol):
    def execute(self, request: dict, *, timeout: int) -> Response: ...


def dispatch(ledger: Ledger, request_id: str, specialist: Specialist):
    # Covers the original POST and subsequent GETs. A dead process releases this
    # lock; the database still refuses a second paid send.
    with FileLock(str(local_path(ledger.root,f'campaigns/dispatch-{request_id}.lock')),timeout=0):
        row=ledger.request(request_id)
        if row['state']=='received':return json.loads(row['receipt'])
        request=json.loads(row['request'])
        timeout=ledger.config(request['campaign']).limits.request_timeout
        acceptance=json.loads(row['acceptance']) if row['acceptance'] else None
        if acceptance:
            if not hasattr(specialist,'retrieve'):raise Stopped('specialist cannot retrieve accepted response')
        else:
            if hasattr(specialist,'preflight'):specialist.preflight(request)
            if request.get('payload',{}).get('wire',{}).get('background') and not hasattr(specialist,'execute_with_acceptance'):
                raise ValueError('specialist lacks durable background acceptance support; no send performed')
            permit=ledger.claim(request_id)
            request=ledger.start_wire(request_id,permit)
        start=time.monotonic()
        try:
            if acceptance:
                response=specialist.retrieve(request,acceptance,timeout=timeout)
            elif request.get('payload',{}).get('wire',{}).get('background'):
                if not hasattr(specialist,'execute_with_acceptance'):
                    raise ValueError('specialist lacks durable background acceptance support')
                response=specialist.execute_with_acceptance(request,timeout=timeout,
                    on_acceptance=lambda body:ledger.record_acceptance(request_id,body))
            else:
                response=specialist.execute(request,timeout=timeout)
            accepted=ledger.request(request_id)['acceptance']
            if accepted and response.receipt.get('response_id')!=json.loads(accepted)['id']:
                raise ValueError('final receipt does not match durable provider acceptance')
            return ledger.receive(request_id,response.raw,incurred=response.incurred,
                successful_images=response.successful_images,provider_receipt=response.receipt)
        except ProviderRejected as rejection:
            response=rejection.response
            return ledger.receive(request_id,response.raw,incurred=response.incurred,
                successful_images=response.successful_images,provider_receipt=response.receipt)
        except BaseException as error:
            known=ledger.request(request_id)['acceptance']
            if known and isinstance(error,(ProviderPending,OSError,TimeoutError)):
                ledger.pending(request_id,'Accepted response awaits retrieval: '+type(error).__name__)
                raise ProviderPending('Accepted response retained; resume by GET, never POST') from error
            ledger.unknown(request_id,'execution interrupted or response unavailable; reconcile with provider')
            raise
        finally:
            ledger.add_active_time(request['campaign'],request['case_id'],time.monotonic()-start)
