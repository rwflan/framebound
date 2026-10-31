"""Import actual Muse sheets as native clips; never generates or invents pixels/labels."""
import hashlib
import io
import json
import re
from pathlib import Path

from PIL import Image

from ..v2 import storage as S
from ..v2.domain import Asset
from ..v2.services.assets import import_asset
from ..v2.services.projects import create_project
from ..v2.services.provenance import write_derived
from ..v2.services.errors import InvalidInput
from .evaluate import digest
from .services import loop, tasks


def _path(root, relative):
    if not isinstance(relative, str):
        raise InvalidInput('corpus artifact path must be a string')
    path = (root / relative).resolve()
    if not path.is_file() and relative.startswith(root.name+'/'):
        path = (root.parent / relative).resolve()
    if not path.is_file() and relative.startswith('muse-corpus-pilot/'):
        path = (root / relative.removeprefix('muse-corpus-pilot/')).resolve()
    if not path.is_relative_to(root) or not path.is_file():
        raise InvalidInput('missing or out-of-corpus artifact: ' + relative)
    return path


def _write(path, raw):
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.exists():
        if path.read_bytes() != raw:
            raise S.ConflictError('immutable corpus artifact differs: ' + str(path))
    else:
        with path.open('xb') as output:
            output.write(raw)


def _png(image):
    output = io.BytesIO()
    image.convert('RGBA').save(output, format='PNG')
    return output.getvalue()


def prepare(manifest_path, project, *, review_path=None, native_size=256):
    """Import a frozen external batch, retaining byte ancestry and model labels.

    The generated benchmark is portable relative to its source directory. All
    generation remains external; only crops and declared resampling occur here.
    """
    path = Path(manifest_path).resolve(); root = path.parent
    manifest = json.loads(path.read_text())
    if manifest.get('schema_version') == '2.0':
        from .campaign.sequence import import_manifest
        return import_manifest(path, project, review_path=review_path, native_size=native_size)
    if not isinstance(native_size, int) or not 16 <= native_size <= 512:
        raise InvalidInput('native size must be an integer between 16 and 512')
    raw_cases = manifest.get('cases', [])
    if not raw_cases or len(raw_cases) > 96 or len({c['id'] for c in raw_cases}) != len(raw_cases):
        raise InvalidInput('corpus needs 1–96 uniquely identified cases')
    reviews = {}
    if review_path:
        review = json.loads(Path(review_path).read_text())
        reviews = {row['id']: row for row in review['cases']}
        if len(reviews) != len(review['cases']):
            raise InvalidInput('duplicate model review identities')
    split_by_board = {}; benchmarks = []; imported = []; pending = []; imported_by_id = {}
    sources_by_id={c['id']:c for c in raw_cases}
    roots={}; variant_counts={}
    for case in raw_cases:
        cursor=case;seen=set()
        while cursor.get('repair_of'):
            if cursor['id'] in seen or cursor['repair_of'] not in sources_by_id: raise InvalidInput('missing or cyclic repair ancestry')
            seen.add(cursor['id']);parent=sources_by_id[cursor['repair_of']]
            if (parent['board_id'],parent['split'],parent['holds'])!=(case['board_id'],case['split'],case['holds']):
                raise InvalidInput('repair must retain its board, split and frozen authored timing')
            cursor=parent
        roots[case['id']]=cursor['id']
        if case.get('repair_of'):
            variant_counts[cursor['id']]=variant_counts.get(cursor['id'],0)+1
            if variant_counts[cursor['id']]>2: raise InvalidInput('at most two model variants per base')
    create_project(project, {'id': 'muse-corpus', 'name': 'Muse game-led animation corpus'})
    # Find the actual frozen style card bytes by hash, not by a guessed filename.
    json_files = {hashlib.sha256(p.read_bytes()).hexdigest(): p
                  for p in root.rglob('*.json') if p.is_file() and not p.is_symlink()}
    for case in raw_cases:
        cid = case['id']; board = case['board_id']; split = case['split']
        if not isinstance(cid,str) or not re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9._-]{0,63}',cid):
            raise InvalidInput('corpus case ID must be a safe immutable identifier')
        if type(case.get('loop')) is not bool: raise InvalidInput('loop must be an explicit boolean')
        if split not in {'development', 'held_out'}:
            raise InvalidInput('unknown frozen corpus split')
        if board in split_by_board and split_by_board[board] != split:
            raise InvalidInput('board identity family crosses frozen splits')
        split_by_board[board] = split
        if case.get('status') not in {'succeeded', 'completed'}:
            pending.append({'id': cid, 'status': case.get('status', 'unknown')}); continue
        holds = case['holds']; columns = case.get('columns', 3); rows = case.get('rows', 2)
        if (columns != 3 or rows != 2 or len(holds) != 6 or
                any(type(h) is not int or h <= 0 for h in holds) or sum(holds) > 720):
            raise InvalidInput('six positive authored holds and a bounded 3 by 2 sheet are required')
        sheet_path = _path(root, case['sheet_file']); receipt_path = _path(root, case['receipt_file'])
        receipt = json.loads(receipt_path.read_text())
        raw = sheet_path.read_bytes(); sheet_sha = hashlib.sha256(raw).hexdigest()
        if (receipt.get('status') != 'completed' or receipt.get('output_sha256') != sheet_sha or
                not str(receipt.get('model_requested', '')).startswith('muse-image-') or
                receipt.get('model_observed') not in {None, receipt.get('model_requested')}):
            raise InvalidInput('case does not match an actual successful Muse receipt: ' + cid)
        style_sha = case.get('style_card_sha256')
        if style_sha not in json_files:
            raise InvalidInput('frozen style card bytes are unavailable: ' + cid)
        style_raw = json_files[style_sha].read_bytes()
        style = dict(id=board, name=case.get('board_title', board), content_sha256=style_sha)
        sheet_relative=str(sheet_path.relative_to(root)); receipt_relative=str(receipt_path.relative_to(root))
        artifacts = {sheet_sha: sheet_relative, hashlib.sha256(receipt_path.read_bytes()).hexdigest(): receipt_relative,
                     style_sha: str(json_files[style_sha].relative_to(root))}
        for sha, relative in artifacts.items(): S.store_blob(project, _path(root, relative).read_bytes())
        prefix = 'muse-' + digest(cid)[:18]
        sheet_id = prefix + '-sheet'
        import_asset(project, str(sheet_path), sheet_id, source_kind='generated', rights='original')
        assets = {sheet_id: sheet_relative}; references = []
        for index, binding in enumerate(receipt.get('conditioning_ordered', [])):
            reference_path = _path(root, binding['source_file'])
            sha = hashlib.sha256(reference_path.read_bytes()).hexdigest()
            if sha != binding['sha256']:
                raise InvalidInput('supplied conditioning bytes changed')
            # Require a successful Muse receipt for each supplied original anchor.
            anchor_receipt = reference_path.with_suffix('.receipt.json')
            if not anchor_receipt.is_file(): raise InvalidInput('original anchor lacks its Muse receipt')
            anchor_evidence = json.loads(anchor_receipt.read_text())
            anchor_receipt_sha = S.store_blob(project, anchor_receipt.read_bytes())
            artifacts[anchor_receipt_sha] = str(anchor_receipt.relative_to(root))
            if anchor_evidence.get('status') != 'completed' or anchor_evidence.get('output_sha256') != sha:
                raise InvalidInput('original anchor differs from generation evidence')
            aid = prefix + f'-reference-{index}'
            import_asset(project, str(reference_path), aid, source_kind='generated', rights='original')
            assets[aid] = str(reference_path.relative_to(root))
            references.append(dict(asset_id=aid, byte_sha256=sha, role=binding.get('kind', 'identity'),
                conditioning_eligibility='original', eligibility_basis='Original Muse-generated anchor with retained generation receipt'))
        frames = []; transforms = []
        targets=case.get('target_slots',list(range(6)))
        if any(type(slot) is not int or not 0<=slot<6 for slot in targets): raise InvalidInput('repair slots must be native slot indices')
        with Image.open(sheet_path) as image:
            image.load()
            if (image.width % columns or image.height % rows or image.width//columns != image.height//rows
                    or image.width*image.height > 16777216):
                raise InvalidInput('sheet cannot be evenly cropped within frozen pixel budget')
            for slot in range(6):
                left = (slot % columns) * (image.width // columns)
                top = (slot // columns) * (image.height // rows)
                bounds = [left, top, left + image.width//columns, top + image.height//rows]
                protected_parent=None;source_sha=sheet_sha;crop_operation='crop '+json.dumps(bounds)
                if case.get('repair_of') and slot not in targets:
                    if case['repair_of'] not in imported_by_id: raise InvalidInput('repair parent must precede child')
                    parent_aid=imported_by_id[case['repair_of']]['frames'][slot]
                    con=S.connect(project)
                    try: protected_parent=S.get(con,'assets',parent_aid)[0]
                    finally: con.close()
                    with Image.open(S.blob_path(project,protected_parent['byte_sha256'])) as parent_image: crop=parent_image.convert('RGBA')
                    source_sha=protected_parent['byte_sha256'];crop_operation='preserve edit-parent frame '+parent_aid
                    assets[parent_aid]=f"native/{case['repair_of']}/frame-{slot}.png"
                else: crop = image.crop(tuple(bounds)).convert('RGBA')
                cropped = _png(crop); crop_sha = S.store_blob(project, cropped)
                crop_file = f'native/{cid}/crop-{slot}.png'; _write(root/crop_file, cropped); artifacts[crop_sha] = crop_file
                method = Image.Resampling.NEAREST if any(x in board for x in ('pixel', 'arcade', 'platform')) else Image.Resampling.LANCZOS
                frame = crop.resize((native_size, native_size), method)
                aid = prefix + f'-frame-{slot}'
                if protected_parent:
                    aid=parent_aid;output=Asset.model_validate(protected_parent)
                else:
                    output = write_derived(project, aid, frame, [sheet_id] + [ref['asset_id'] for ref in references],
                        dict(operator='muse-corpus-crop-resize-v1', crop=bounds, canvas=[native_size,native_size], resampling=method.name,
                            target_slots=targets))
                if protected_parent and output.pixel_sha256!=protected_parent['pixel_sha256']:
                    raise InvalidInput('protected edit-parent frame pixels changed')
                frame_raw = S.blob_path(project, output.byte_sha256).read_bytes()
                relative = f'native/{cid}/frame-{slot}.png'; _write(root/relative, frame_raw)
                assets[aid] = relative; frames.append(aid)
                transforms.extend([dict(operation=crop_operation, input_sha256=source_sha, output_sha256=crop_sha),
                    dict(operation='resize '+method.name, input_sha256=crop_sha, output_sha256=output.byte_sha256)])
                artifacts[output.byte_sha256] = relative
        event = dict(id=cid,edit_parent_event_id=case.get('repair_of'), provider='meta', requested_model=receipt['model_requested'],
            observed_model=receipt.get('model_observed'), observed_version=receipt.get('version_observed'),
            evidence_source='external_assertion', response_id=receipt.get('response_id'), outcome='succeeded',
            prompt_sha256=receipt['prompt_sha256'], conditioning=references, original_output_sha256=[sheet_sha],
            output_asset_ids=frames, receipt_sha256=[sha for sha,relative in artifacts.items() if relative.endswith('.receipt.json')], transformations=transforms)
        metadata = dict(provenance=dict(schema_version='1.0', parent=dict(provider='meta',
            requested_model=manifest.get('parent_requested', 'muse-spark-1.3-contributor'),
            observed_model=manifest.get('parent_observed'), harness='Muse Code', harness_version='1.4.13',
            contributor_requested=manifest.get('contributor_requested', 'on'),
            contributor_effective=manifest.get('contributor_effective', 'unknown'), evidence_source='external_assertion'),
            style_board=style, generations=[event]))
        label = reviews.get(cid)
        if label:
            label=dict(label,reviewer=review.get('reviewer',{'evidence_source':'unknown'}),
                source_review_sha256=hashlib.sha256(Path(review_path).read_bytes()).hexdigest())
            metadata['model_review'] = label
        spec = dict(id=prefix+'-task', project_id='muse-corpus', animation_id=roots[cid],
            intent=case['intent'], subjects='Original Muse-designed subjects; see the frozen brief and style card.',
            canvas=dict(width=native_size,height=native_size), timing=dict(holds=holds,ticks_per_second=case.get('ticks_per_second',12)),
            loop=case['loop'], profile='structural-v1', style_board=style,
            inputs=[dict(asset_id=r['asset_id'], role='keyframe' if case.get('repair_of') else 'identity', byte_sha256=r['byte_sha256'],
                provenance=r['eligibility_basis'],designated_by='Muse generation receipt',basis='Actual supplied image; not a known-good motion lane') for r in references],
            requirements=[dict(id='generated-art-quality',check='animation_quality',required=False,
                desired_outcome='Learn and assess anatomy, action, style and legitimate animation counterexamples; no exact-colour reliability claim.')],
            limits=dict(max_submissions=3), completion=dict(id='technical-unreviewed-v1'))
        run_id='muse-'+digest(roots[cid])[:18]+'-run'
        parent_revision=None; feedback_id=None
        if case.get('repair_of'):
            if case['repair_of'] not in imported_by_id: raise InvalidInput('repair parent must precede child in the import manifest')
            parent=imported_by_id[case['repair_of']];parent_revision=parent['revision_id']
            current=loop.get(project,run_id)
            try: replay=loop.revision_get(project,prefix+'-base')['revision']
            except InvalidInput: replay=None
            if replay:
                spec=tasks.get(project,spec['id'])['spec'];feedback_id=replay['targeted_feedback_id']
            elif current['task_id']!=spec['id']:
                spec['supersedes']=current['task_id']
                spec['change_reason']=case.get('repair_reason','Apply the recorded automated model correction while retaining frozen timing, identity and budgets.')
                tasks.create(project,spec);loop.revise_task(project,run_id,spec['id'],current['version'])
                feedback_id=loop.get(project,run_id).get('feedback_id')
            else:
                spec=tasks.get(project,spec['id'])['spec'];feedback_id=current.get('feedback_id')
        else:
            tasks.create(project,spec)
            try: existing_run=loop.get(project,run_id)
            except InvalidInput: existing_run=None
            if existing_run is None:loop.start(project,spec['id'],run_id)
            elif existing_run['animation_id']!=roots[cid]:raise S.ConflictError('corpus family run differs')
        feedback = loop.submit(project,run_id,prefix+'-base',frames,generation_metadata=metadata,
            parent_revision_id=parent_revision,feedback_id=feedback_id)
        spec=tasks.get(project,spec['id'])['spec']
        benchmarks.append(dict(id=cid,repair_of=case.get('repair_of'),spec=spec,assets=assets,frame_asset_ids=frames,board_id=board,identity_family=board,
            origin='image_generated',label_source='model_review' if label else 'unreviewed',
            label_provenance=json.dumps(label,sort_keys=True) if label else 'Awaiting separate Muse multimodal annotation.',
            complete_labels=bool(label and label.get('complete_labels',False)),expected_defects=label.get('expected_defects',[]) if label else [],
            generation_provenance='Actual Muse Image receipt '+hashlib.sha256(receipt_path.read_bytes()).hexdigest(),
            generation_metadata=metadata,provenance_blobs=artifacts,split=split))
        entry=dict(id=cid,run_id=run_id,revision_id=prefix+'-base',feedback_id=feedback['id'],
            frames=frames,technical_status=feedback['technical_status'],coverage=feedback['coverage'])
        imported.append(entry);imported_by_id[cid]=entry
    benchmark = dict(id='muse-game-led-v1',schema_version='1.0',cases=benchmarks,
        methodology='Actual Muse Image originals, deterministic recorded crops/resampling, frozen board-family splits. Separate Muse labels are model evidence. Structural checks cannot establish arbitrary animation quality; retain unmeasured coverage. Human review is optional.')
    _write(root/'benchmark.json', (json.dumps(benchmark,indent=2)+'\n').encode())
    return dict(imported=imported,pending=pending,benchmark=str(root/'benchmark.json'),project=str(Path(project).resolve()))


def normalize_model_review(source_path, destination):
    """Separate the requested check matrix from explicitly observed defect labels.

    This is a schema transformation only. Observations, slots and confidence are
    copied from the external model; the original review remains immutable.
    """
    path=Path(source_path);review=json.loads(path.read_text())
    normalized=dict(review,normalization=dict(operator='explicit-defect-labels-v1',
        source_sha256=hashlib.sha256(path.read_bytes()).hexdigest(),
        note='Requested checks are not positive defect labels. Only explicit observed defect records populate expected_defects.'))
    cases=[]
    for case in review['cases']:
        if 'defects' not in case: cases.append(case);continue
        labels={}
        for defect in case['defects']:
            family=defect['family'];slots=defect['slots']
            if not isinstance(family,str) or not family or any(type(s) is not int or not 0<=s<6 for s in slots):
                raise InvalidInput('model defect family and localized slots must be explicit')
            check_id=family if family.startswith('quality:') else 'quality:'+family
            labels.setdefault(check_id,set()).update(slots)
        cases.append(dict(case,requested_checks=case.get('expected_defects',[]),
            expected_defects=[dict(check_id=key,slots=sorted(slots),roi=None) for key,slots in labels.items()]))
    normalized['cases']=cases
    _write(Path(destination),(json.dumps(normalized,indent=2)+'\n').encode())
    return normalized
