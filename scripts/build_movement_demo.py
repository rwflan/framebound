"""Build a matched movement comparison from a private JSON brief.

Originals, prompts, assessments and receipts are retained under --root. A send
marker is written before each POST; unresolved sends are never retried. Both
lanes share initial pixels, extraction, registration canvas and playback. Only
the framework lane receives assessment-driven replacement generations.
"""
import argparse
import hashlib
import io
import json
from pathlib import Path
import sys

import numpy as np
from PIL import Image

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from framebound.v3.campaign.specialists import MuseResponses, extract_image, extract_text, wire
from framebound.v3.intake import keyed, framing
from framebound.v3.guidance import PRINCIPLES
from framebound.v3.campaign.features import extract


def save(path, value):
    import uuid
    temporary = path.with_name(path.name+'.'+uuid.uuid4().hex+'.tmp')
    temporary.write_text(json.dumps(value, indent=2) + '\n')
    temporary.replace(path)


_COST_CACHE = {}


def refresh_costs(root):
    config=Path(root)/'config.json'
    try:
        if not config.exists() or not json.loads(config.read_text()).get('cost_lineage_roots'):return
        from scripts.update_demo_costs import update
        update(Path(root),cache=_COST_CACHE)
    except Exception as error:
        # A receipt/commitment remains durable even if the optional live sidecar
        # cannot refresh. Do not hide a provider error or resend its operation.
        try:save(Path(root)/'private'/'cost-refresh-error.json',dict(error=type(error).__name__,detail=str(error)))
        except OSError:pass
        print('Cost sidecar requires reconciliation:',type(error).__name__,flush=True)


def send(root, name, model, prompt, images, *, image_size="1536x1024"):
    folder = root / 'private' / name
    folder.mkdir(parents=True, exist_ok=True)
    response = folder / 'response.json'
    successor=folder/'successor.json'
    if successor.exists():
        child=json.loads(successor.read_text())['operation']
        link=json.loads((root/'private'/child/'recovery.json').read_text())
        if link['recovery_of']!=name:raise ValueError('Recovery successor linkage mismatch')
        return send(root,child,model,prompt,images,image_size=image_size)
    if response.exists():
        if not (folder/'receipt.json').exists() and (folder/'request.json').exists():
            from scripts.provider_operation import run
            frozen=json.loads((folder/'request.json').read_text());quote=frozen['committed_microdollars']
            try:run(folder,dict(payload=dict(wire=frozen['wire'],quote=quote),quote=quote),MuseResponses(),timeout=300)
            finally:refresh_costs(root)
        retained = response.read_bytes()
        body = json.loads(retained)
        if model == 'muse-spark-1.3' and body.get('status') == 'incomplete' and body.get('incomplete_details', {}).get('reason') == 'max_output_tokens':
            # Known terminal failure, retained separately; never retry an unknown send.
            if name.endswith('-expanded'):
                raise ValueError('Expanded assessment also exhausted its output bound')
            return send(root, name + '-expanded', model, prompt, images, image_size=image_size)
        return retained
    config_path=root/'config.json'
    config=json.loads(config_path.read_text()) if config_path.exists() else {}
    body = wire(model, prompt, images, max_output_tokens=8192 if model == 'muse-spark-1.3' else None)
    if model == 'muse-spark-1.3':
        body['reasoning'] = dict(effort='low')
    if model == 'muse-image-1.0':
        body['tools'] = [dict(type='image_generation', size=image_size, output_format='png', enable_image_search=False, enable_web_search=False)]
    if config.get('durable_provider_transport')=='stream':
        from scripts.provider_operation import run
        # Freeze the identity on first send; resuming an accepted operation must
        # use its original wire, even if defaults later change.
        retained=folder/'request.json'
        if retained.exists():
            frozen=json.loads(retained.read_text())['wire']
            if any(frozen.get(k)!=body.get(k) for k in ('model','input','tools','reasoning','max_output_tokens')):raise ValueError('Frozen operation input changed')
            body=frozen
        else:
            body.update(stream=True,store=True,metadata=dict(framebound_operation=hashlib.sha256(name.encode()).hexdigest()))
        adapter=MuseResponses();quoted=10000 if model=='muse-image-1.0' else 100000
        request=dict(payload=dict(wire=body,quote=quoted,images=1 if model=='muse-image-1.0' else 0),quote=quoted)
        adapter.preflight(request)
        try:
            with (folder/'job.json').open('x') as registration:json.dump(dict(active=True,operation=name,transport='retained-sse'),registration)
        except FileExistsError:pass
        try:return run(folder,request,adapter,timeout=300)
        except Exception as error:
            policy=config.get('provider_recovery_policy',{})
            if (not policy.get('authorization') or not (folder/'request.json').exists() or
                    (folder/'acceptance.json').exists() or response.exists() or getattr(error,'code',None) in (401,403)):
                raise
            from scripts.provider_operation import authorize_recovery
            child=name+'-recovery-1'
            authorize_recovery(root,name,child,authorization=policy['authorization'],max_recoveries=policy.get('max_successors_per_parent',2),max_recovery_microdollars=policy.get('max_recovery_microdollars',1_000_000))
            save(successor,dict(operation=child,original_acceptance='unknown',commitment_retained=True))
            return send(root,child,model,prompt,images,image_size=image_size)
        finally:refresh_costs(root)
    marker = folder / 'request.json'
    if marker.exists():raise FileExistsError('Unresolved provider operation; reconcile without resending')
    adapter = MuseResponses()
    quoted = 10000 if model == 'muse-image-1.0' else 100000
    request = dict(payload=dict(wire=body, quote=quoted, images=1 if model == 'muse-image-1.0' else 0), quote=quoted)
    adapter.preflight(request)
    # Exclusive creation makes restarts fail closed after possible acceptance.
    with marker.open('x') as stream:
        json.dump(dict(wire=body, committed_microdollars=quoted), stream)
    try:
        result = adapter.execute(request, timeout=300)
        response.write_bytes(result.raw)
        save(folder / 'receipt.json', dict(incurred_microdollars=result.incurred, receipt=result.receipt, response_sha256=hashlib.sha256(result.raw).hexdigest()))
    finally:
        refresh_costs(root)
    print(name, 'received', flush=True)
    return result.raw


def frames(raw):
    image = Image.open(io.BytesIO(extract_image(raw))).convert('RGBA')
    if image.width < 1800 or image.height < 1000 or image.width % 3:
        raise ValueError(f'Expected high resolution three-column sheet, got {image.size}')
    image, extraction = keyed(image)
    result = []
    for i in range(3):
        crop = image.crop((i * image.width // 3, 0, (i + 1) * image.width // 3, image.height))
        # Shared padding preserves any provider clipping as a visible defect;
        # it never reconstructs missing pixels or fits individual poses.
        rgba = Image.new("RGBA", (crop.width + 64, crop.height + 64))
        rgba.alpha_composite(crop, (32, 32))
        box = rgba.getbbox()
        if not box or box[3] - box[1] < 450:
            raise ValueError('Insufficient native character resolution')
        result.append(rgba)
    return result


def metrics(images):
    boxes = [im.getbbox() for im in images]
    heights = [b[3] - b[1] for b in boxes]
    bottoms = [b[3] for b in boxes]
    native = extract(images, [6] * len(images), loop=False, extractor="native-geometry-v2")
    clipped = []
    for i, im in enumerate(images):
        alpha = np.asarray(im)[:, :, 3]
        if max(np.count_nonzero(edge) for edge in (alpha[32:-32, 32], alpha[32:-32, -33], alpha[32, 32:-32], alpha[-33, 32:-32])) > 6:
            clipped.append(i)
    return dict(clipped_slots=clipped, native_features=native["features"].tolist(), feature_names=native["feature_names"], proposals=native["proposals"], height_spread=float((max(heights)-min(heights))/np.median(heights)), baseline_spread=float((max(bottoms)-min(bottoms))/images[0].height))


def assess(root, name, prompt, refs, raw, measured):
    rubric = '''Review this three-pose animation sheet against the attached character references and requested poses. Return ONLY JSON: {"score":0-100,"issues":["specific visible discrepancy and affected slot"],"repair":"precise bounded correction instructions"}. Critically assess identity, face, costume, limb anatomy, pose order, meaningful motion and stable scale. Do not award a perfect score for merely having three figures. Transparent delivery is handled equally outside this review. Scores are automated assessments, never human approval.'''
    review = extract_text(send(root, name, 'muse-spark-1.3', rubric + '\nBrief: ' + prompt + '\nMeasured geometry: ' + json.dumps(measured), [*refs, extract_image(raw)]))
    if not isinstance(review, dict) or not isinstance(review.get('score'), (int, float)) or not 0 <= review['score'] <= 100 or not isinstance(review.get('issues'), list) or not isinstance(review.get('repair'), str):
        raise ValueError('Invalid bounded assessment; no selection permitted')
    if measured['clipped_slots']:
        issue = 'Subject touches a cell boundary in slots ' + str(measured['clipped_slots'])
        review['issues'].append(issue)
        review['repair'] += '\n' + issue + '. Fit ALL characters INCLUDING cape, hair, limbs and whip fully INSIDE their own column with at least 40px magenta margin on every side. Reduce the common scale if needed, keeping identical head size in every cell. Do not add figures or ground shadows.'
    return review


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--config', type=Path, required=True)
    parser.add_argument('--root', type=Path, required=True)
    parser.add_argument('--publish-received', action='store_true', help='Rebuild individual-pose playback from retained selected responses without sending')
    args = parser.parse_args()
    config = json.loads(args.config.read_text())
    root = args.root
    if config.get('mode') == 'individual':
        from scripts.build_individual_demo import build, publish_received
        return publish_received(config, root) if args.publish_received else build(config, root)
    if args.publish_received:
        raise ValueError('Receipt-only publication requires individual mode')
    public = root / 'published'
    public.mkdir(parents=True, exist_ok=True)
    refs = [Path(p).read_bytes() for p in config['references']]
    direct, refined, reports, states = [], [], [], {}
    for batch in config['batches']:
        prompt = config['brief'] + '\n' + batch['instruction']
        raw = send(root, batch['id'] + '-initial', 'muse-image-1.0', prompt, refs)
        initial = frames(raw)
        chosen = initial
        review = assess(root, batch['id'] + '-assessment', prompt, refs, raw, metrics(initial))
        report = dict(batch=batch['id'], initial=review, initial_geometry=metrics(initial), selected='initial')
        # At most two bounded repair proposals. Initial pixels stay frozen in control.
        best = float(review['score'])
        for attempt in range(2):
            if not review.get('issues') and best >= 90:
                break
            repaired = send(root, batch['id'] + f'-repair-{attempt}', 'muse-image-1.0', prompt + '\nFramebound repair constraints:\n' + '\n'.join(text for _, text in PRINCIPLES) + '\nCorrect these observed defects while preserving all other requirements: ' + str(review['repair']), [*refs, extract_image(raw)])
            try:
                candidate = frames(repaired)
                candidate_metrics = metrics(candidate)
                checked = assess(root, batch['id'] + f'-recheck-{attempt}', prompt, refs, repaired, candidate_metrics)
            except ValueError as error:
                report.setdefault('rejected', []).append(str(error))
                continue
            report.setdefault('attempts', []).append(dict(review=checked, geometry=candidate_metrics))
            # Geometry regressions cannot be hidden by a semantic score increase.
            previous_metrics = metrics(chosen)
            clip_count = len(candidate_metrics['clipped_slots'])
            old_clip_count = len(previous_metrics['clipped_slots'])
            improves = float(checked['score']) > best or (clip_count < old_clip_count and float(checked['score']) >= best - 5)
            safe = (clip_count <= old_clip_count
                    and candidate_metrics['height_spread'] <= previous_metrics['height_spread'] + .03
                    and candidate_metrics['baseline_spread'] <= previous_metrics['baseline_spread'] + .03)
            if improves and safe:
                chosen, best, raw, review = candidate, float(checked['score']), repaired, checked
                report['selected'] = f'repair-{attempt}'
        start = len(direct)
        direct.extend(initial)
        refined.extend(chosen)
        for state, indices in batch['states'].items():
            spec = states.setdefault(state, dict(frames=[], duration_ticks=[], loop=state in ('idle','run')))
            spec['frames'].extend(start+i for i in indices)
            spec['duration_ticks'].extend([30 if state == 'idle' else 6]*len(indices))
        reports.append(report)
        save(root / 'private' / 'assessment-summary.json', reports)
        print(batch['id'], report['selected'], flush=True)
    for image in refined:
        gate = framing(image, source_box=(32,32,image.width-32,image.height-32))
        if not gate['eligible']:
            raise ValueError('Framework publication withheld: original cell framing failed: '+'; '.join(gate['reasons']))
    # One shared canvas and scale for every frame in both lanes; no per-frame fitting.
    width = max(im.width for im in direct + refined)
    height = max(im.height for im in direct + refined)
    revision_hash = hashlib.sha256(json.dumps(reports,sort_keys=True).encode())
    for image in direct + refined:
        revision_hash.update(image.tobytes())
    revision = revision_hash.hexdigest()[:16]
    output = public / revision
    output.mkdir(exist_ok=True)
    for lane, images in [('direct', direct), ('framework', refined)]:
        for i, image in enumerate(images):
            canvas = Image.new('RGBA', (width,height))
            canvas.alpha_composite(image, ((width-image.width)//2,height-image.height))
            canvas.save(output / f'{lane}-{i}.png')
    save(public / 'manifest.json', dict(schema=2, canvas=[width,height], states=states, frame_count=len(direct), revision=revision, automated_review=True, repairs_selected=sum(r['selected']!='initial' for r in reports), comparison='Shared initial generation; identical extraction and playback; framework-only assessed repairs.'))
    print('published', public, flush=True)


if __name__ == '__main__':
    main()
