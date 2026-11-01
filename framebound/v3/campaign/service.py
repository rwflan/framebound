"""One service shared by CLI, HTTP and MCP; all data stays in the local root."""
import json
from pathlib import Path
import subprocess

from .contracts import canonical, local_path, parse_campaign
from .curriculum import mvp_curriculum
from .dispatch import Response, dispatch
from .ledger import Ledger, ProviderPending, Stopped


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


def operate(root, action, *, campaign='animation-mvp-v2-keyed', config=None, request=None, specialist=None):
    ledger = Ledger(root)
    if action == 'plan-upskill':
        from .curriculum import upskill_curriculum
        return ledger.plan(upskill_curriculum(campaign))
    if action in {'upskill-plan','upskill-step'}:
        from . import continuation
        if action=='upskill-plan':return continuation.plan(root,campaign)
        if not request:raise ValueError('explicit fixed batch and allocation request required')
        return continuation.step(root,campaign,request,specialist)
    if action == 'isolate-unknown':
        if not request:raise ValueError('explicit unknown request and isolation evidence required')
        return ledger.isolate_unknown(campaign,request['request_id'],request['evidence'])
    if action == 'plan':
        if config is not None:frozen=parse_campaign(config)
        else:
            try:frozen=ledger.config(campaign)
            except ValueError:frozen=mvp_curriculum(campaign)
        return ledger.plan(frozen)
    if action == 'inventory':
        from .inventory import inspect
        return inspect(root,(request or {}).get('campaign'))
    if action == 'readiness':
        from .progression import readiness
        return readiness(root,campaign)
    if action == 'quarantine':
        from .progression import quarantine
        if not request:raise ValueError('saved acquisition failure report required')
        return quarantine(root,campaign,request)
    if action == 'release':
        from .progression import release
        if not request:raise ValueError('explicit stage and evidence request required')
        return release(root,campaign,request)
    if action == 'fund':
        if not request:raise ValueError('explicit allocation and account evidence required')
        ledger.fund(campaign,request['subsystem'],request['microdollars'],evidence=request['evidence'])
        return ledger.status(campaign)
    if action == 'api-budget':
        if not request:raise ValueError('explicit API ceiling and operator authorization required')
        return ledger.authorize_api_budget(campaign,request['microdollars'],evidence=request['evidence'])
    if action in {'baseline','profile','ablation','final-report','compute-plan'}:
        from . import study
        if not request:raise ValueError('explicit local study request required')
        function={'final-report':study.final_report,'compute-plan':study.compute_plan}.get(action) or getattr(study,action)
        return function(root,campaign,request)
    if action == 'advisory-set':
        from .advisory import select
        if not request:raise ValueError('explicit advisory selection required')
        return select(root,campaign,request)
    if action in {'knowledge-build','knowledge-query'}:
        from . import knowledge
        if not request:raise ValueError('explicit dataset version required')
        if action=='knowledge-build':return knowledge.build(root,campaign,version=request['version'],dataset_version=request.get('dataset_version'))
        return knowledge.retrieve(root,campaign,version=request['version'],categories=request['categories'],
            exclude_families=request.get('exclude_families',()),limit=request.get('limit',3))
    if action == 'audit':
        from .corroboration import replay
        return replay(root,campaign)
    if action == 'status':
        return ledger.status(campaign)
    if action == 'stop':
        return ledger.stop(campaign)
    if action == 'resume':
        return ledger.resume(campaign)
    if action == 'modal':
        from .remote import Job,submit
        from .modal_worker import ModalTransport
        if not request:raise ValueError('explicit feature file, quoted job and case required')
        raw=local_path(root,request['feature_file']).read_bytes()
        return submit(ledger,campaign,request['case_id'],raw,Job.model_validate(request['job']),ModalTransport(),study=request.get('study'))
    if action == 'features':
        from .features import collect
        return collect(root,campaign,version=(request or {}).get('version','1'),
            extractor=(request or {}).get('extractor','native-geometry-v2' if ledger.config(campaign).schema_version=='2.0' else 'native-numeric-v1'),
            include_test=(request or {}).get('include_test',False),dataset_version=(request or {}).get('dataset_version'),
            scoped=ledger.config(campaign).schema_version=='2.0')
    if action == 'train':
        from .transfer import inspect_payload
        from .learning import experiment
        if not request:raise ValueError('feature file and categories required')
        shard=inspect_payload(local_path(root,request['feature_file']).read_bytes())
        return experiment(root,campaign,shard,categories=request['categories'])
    if action == 'reserve':
        if request is None:
            raise ValueError('frozen executable request required')
        return ledger.reserve(campaign, **request)
    if action == 'run':
        if specialist is None:
            raise ValueError('an explicitly configured specialist is required')
        from .runner import Runner
        return Runner(root,campaign,specialist).run(max_cases=(request or {}).get('max_cases'),case_ids=(request or {}).get('case_ids'))
    if action == 'outbox':
        if specialist is None:
            raise ValueError('an explicitly configured specialist is required; no generation is inferred')
        config = ledger.config(campaign)
        if ledger.status(campaign)['stopped']:
            raise Stopped('campaign stopped')
        completed = []
        # Single coordinator, bounded serial admission. Parallel adapters can claim
        # the same outbox safely; initial configured concurrency is an upper bound.
        for row in ledger.status(campaign)['requests']:
            if row['state'] in {'reserved','provider_pending'}:
                try:
                    completed.append(dispatch(ledger,row['id'],specialist))
                except ProviderPending:
                    return dict(completed=completed,pending=row['id'],status=ledger.status(campaign))
                except Exception as exc:
                    ledger.stop(campaign)
                    return dict(completed=completed, stopped=True, reason=type(exc).__name__,
                                limitation='Inspect the local receipt; request shape failures stop admission before another send.')
        return dict(completed=completed,status=ledger.status(campaign))
    if action == 'export':
        from .export import export_campaign
        return export_campaign(root,campaign,version=(request or {}).get('version','1'))
    if action == 'report':
        from .report import build
        report = build(root,campaign)
        report['evidence_scope'] = 'durable execution and cost evidence; structural validity does not establish artistic quality'
        report['unknown_outcomes'] = sum(r['state'] in {'unknown_provider_outcome','wire_started'} for r in report['execution']['requests'])
        path = local_path(root,f'campaigns/{campaign}/reports/status.json')
        path.parent.mkdir(parents=True,exist_ok=True)
        path.write_bytes(canonical(report))
        return report
    raise ValueError('unknown campaign action')


def register_cli(sub):
    parser = sub.add_parser('campaign', help='v3 local animation campaign controller')
    parser.add_argument('action',choices=['plan','plan-upskill','upskill-plan','upskill-step','isolate-unknown','run','resume','status','stop','report','reserve','outbox','replay','export','train','features','modal','audit','inventory','readiness','release','fund','api-budget','baseline','profile','ablation','knowledge-build','knowledge-query','final-report','advisory-set','compute-plan','quarantine'])
    parser.add_argument('--root',required=True)
    parser.add_argument('--campaign',default='animation-mvp-v2-keyed')
    parser.add_argument('--config',help='Frozen config JSON file for plan')
    parser.add_argument('--request',help='Local JSON request for the selected operation')
    parser.add_argument('--snapshot',help='Validated historical snapshot for assessment-only replay')
    parser.add_argument('--muse',action='store_true',help='Use bounded Muse Responses with MODEL_API_KEY')
    parser.add_argument('--specialist',help='JSON array of pinned external specialist argv')


def from_cli(args):
    if args.action=='replay':
        from .replay import replay
        if not args.snapshot: raise ValueError('--snapshot is required')
        return replay(args.root,args.snapshot,name=args.campaign)
    from .specialists import MuseResponses
    return operate(args.root,args.action,campaign=args.campaign,
        config=json.loads(Path(args.config).read_text()) if args.config else None,
        request=json.loads(Path(args.request).read_text()) if args.request else None,
        specialist=MuseResponses() if args.muse else CommandSpecialist(json.loads(args.specialist)) if args.specialist else None)
