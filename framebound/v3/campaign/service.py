"""One service shared by CLI, HTTP and MCP; all data stays in the local root."""
import json
from pathlib import Path
import subprocess

from .contracts import Campaign, canonical, curriculum, local_path
from .dispatch import Response, dispatch
from .ledger import Ledger, Stopped


class CommandSpecialist:
    """External v3 bridge, without legacy guide/reviewer dependencies.

    The pinned argv command reads one immutable JSON request on stdin and returns
    JSON {raw_base64, incurred, successful_images, receipt}. It must disable its
    own paid-call retries. No shell is involved. Hosted image generation must
    never be invoked from a replayable Modal worker.
    """
    def __init__(self, argv):
        if not argv or any(not isinstance(a,str) for a in argv):
            raise ValueError('explicit specialist argv required')
        self.argv = argv

    def execute(self, request, *, timeout):
        import base64
        result = subprocess.run(self.argv, input=canonical(request), capture_output=True, timeout=timeout, check=True)
        if len(result.stdout) > 64 * 1024**2:
            raise ValueError('specialist response exceeds output bound')
        body = json.loads(result.stdout)
        return Response(base64.b64decode(body['raw_base64'],validate=True),body['incurred'],body['successful_images'],body['receipt'])


def operate(root, action, *, campaign='animation-v1', config=None, request=None, specialist=None):
    ledger = Ledger(root)
    if action == 'plan':
        frozen = Campaign.model_validate(config) if config is not None else curriculum(campaign)
        return ledger.plan(frozen)
    if action == 'status':
        return ledger.status(campaign)
    if action == 'stop':
        return ledger.stop(campaign)
    if action == 'resume':
        return ledger.resume(campaign)
    if action == 'reserve':
        if request is None:
            raise ValueError('frozen executable request required')
        return ledger.reserve(campaign, **request)
    if action == 'run':
        if specialist is None:
            raise ValueError('an explicitly configured specialist is required; no generation is inferred')
        config = ledger.config(campaign)
        if ledger.status(campaign)['stopped']:
            raise Stopped('campaign stopped')
        completed = []
        # Single coordinator, bounded serial admission. Parallel adapters can claim
        # the same outbox safely; initial configured concurrency is an upper bound.
        for row in ledger.status(campaign)['requests']:
            if row['state'] == 'reserved':
                try:
                    completed.append(dispatch(ledger,row['id'],specialist))
                except Exception as exc:
                    ledger.stop(campaign)
                    return dict(completed=completed, stopped=True, reason=type(exc).__name__,
                                limitation='Inspect the local receipt; request shape failures stop admission before another send.')
        return dict(completed=completed,status=ledger.status(campaign))
    if action == 'report':
        report = ledger.status(campaign)
        report['evidence_scope'] = 'durable execution and cost evidence; structural validity does not establish artistic quality'
        report['unknown_outcomes'] = sum(r['state'] in {'unknown_provider_outcome','wire_started'} for r in report['requests'])
        path = local_path(root,f'campaigns/{campaign}/reports/status.json')
        path.parent.mkdir(parents=True,exist_ok=True)
        path.write_bytes(canonical(report))
        return report
    raise ValueError('unknown campaign action')


def register_cli(sub):
    parser = sub.add_parser('campaign', help='v3 local animation campaign controller')
    parser.add_argument('action',choices=['plan','run','resume','status','stop','report','reserve'])
    parser.add_argument('--root',required=True)
    parser.add_argument('--campaign',default='animation-v1')
    parser.add_argument('--config',help='Frozen config JSON file for plan')
    parser.add_argument('--request',help='Executable request JSON file for reserve')
    parser.add_argument('--specialist',help='JSON array of pinned external specialist argv')


def from_cli(args):
    return operate(args.root,args.action,campaign=args.campaign,
        config=json.loads(Path(args.config).read_text()) if args.config else None,
        request=json.loads(Path(args.request).read_text()) if args.request else None,
        specialist=CommandSpecialist(json.loads(args.specialist)) if args.specialist else None)
