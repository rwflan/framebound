"""Blind Modal VLM benchmark of paid raw and framework-guided Muse outputs.

This compares existing generations only. It does not create another image or
retry any unresolved provider request.
"""
import base64
from pathlib import Path
import hashlib
import io
import json
import re
import sys
import time

import modal
import numpy as np
from PIL import Image

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

RAW_CAMPAIGN = 'direct-muse-control-20261103-v2'
GUIDED_CAMPAIGN = 'animation-upskill-v13-20261102'
CONTROL_CASES = (
    'u6-3e1914ca09-t00-c0-f0-locomotion',
    'u6-3e1914ca09-t01-c0-f0-acting',
    'u6-3e1914ca09-t02-c0-f0-interaction',
    'u6-3e1914ca09-t03-c1-f0-locomotion',
    'u6-3e1914ca09-t04-c0-f0-locomotion',
    'u6-3e1914ca09-t05-c0-f0-acting',
    'u6-3e1914ca09-t06-c0-f0-interaction',
)
MODEL_ID = 'Qwen/Qwen2.5-VL-32B-Instruct'
MODEL_REVISION = '7cfb30d71a1f4f49a57592323337a4a4727301da'
CRITERIA = ('identity', 'continuity', 'action_order', 'artifact_absence', 'usability')

app = modal.App('framebound-direct-vs-guided')
hf_cache = modal.Volume.from_name('framebound-hf-cache', create_if_missing=True)
runtime = (
    modal.Image.debian_slim(python_version='3.11')
    .pip_install(
        'torch>=2.5,<3',
        'torchvision>=0.20,<1',
        'transformers>=4.52,<5',
        'qwen-vl-utils>=0.0.8,<1',
        'accelerate>=1.6,<2',
        'pillow>=11,<12',
        'num2words>=0.5,<1',
    )
    .env({'HF_HOME': '/cache/huggingface'})
)


def _png(image):
    stream = io.BytesIO()
    image.convert('RGBA').save(stream, format='PNG')
    return stream.getvalue()


def _normalize_frames(images, size=256):
    arrays = [np.asarray(image.convert('RGBA')) for image in images]
    transparent = float(np.mean([np.mean(array[:, :, 3] <= 8) for array in arrays]))
    if transparent >= 0.05:
        masks = [array[:, :, 3] > 8 for array in arrays]
    else:
        masks = []
        for array in arrays:
            border = np.concatenate((array[:2, :, :3].reshape(-1, 3),
                                     array[-2:, :, :3].reshape(-1, 3),
                                     array[:, :2, :3].reshape(-1, 3),
                                     array[:, -2:, :3].reshape(-1, 3)))
            background = np.median(border, axis=0)
            masks.append(np.max(np.abs(array[:, :, :3].astype(float) - background), axis=2) > 22)
    union = np.logical_or.reduce(masks)
    ys, xs = np.nonzero(union)
    if not len(xs):
        raise ValueError('pose strip has no measurable foreground')
    left, right = int(xs.min()), int(xs.max()) + 1
    top, bottom = int(ys.min()), int(ys.max()) + 1
    padding = max(4, round(max(right - left, bottom - top) * 0.12))
    side = max(right - left, bottom - top) + 2 * padding
    cx, cy = (left + right) / 2, (top + bottom) / 2
    box = (round(cx - side / 2), round(cy - side / 2),
           round(cx + side / 2), round(cy + side / 2))
    output = []
    for image in images:
        rgba = image.convert('RGBA')
        white = Image.new('RGBA', rgba.size, (255, 255, 255, 255))
        white.alpha_composite(rgba)
        output.append(white.crop(box).resize((size, size), Image.Resampling.LANCZOS).convert('RGB'))
    return output


def _raw_frames(ledger, case_id):
    from framebound.v3.campaign.ledger import Ledger
    with ledger.db() as db:
        row = db.execute(
            "SELECT id FROM requests WHERE campaign=? AND case_id=? "
            "AND operation='generate' AND state='received' ORDER BY rowid LIMIT 1",
            (RAW_CAMPAIGN, case_id),
        ).fetchone()
    if not row:
        raise ValueError(f'raw generation receipt missing for {case_id}')
    response, _ = ledger.artifact(row['id'])
    body = json.loads(response)
    encoded = body.get('data', [{}])[0].get('b64_json')
    if not encoded:
        raise ValueError(f'raw generation response has no image: {case_id}')
    image = Image.open(io.BytesIO(base64.b64decode(encoded, validate=True))).convert('RGBA')
    if image.width % 3 or image.height % 2:
        raise ValueError(f'raw output is not a 3 by 2 pose sheet: {case_id}')
    width, height = image.width // 3, image.height // 2
    frames = [
        image.crop((index % 3 * width, index // 3 * height,
                    (index % 3 + 1) * width, (index // 3 + 1) * height))
        for index in range(6)
    ]
    return _normalize_frames(frames), row['id']


def _guided_frames(root, case_id):
    from framebound.v2 import storage as S
    from framebound.v3.campaign.ledger import Ledger
    from framebound.v3.services import loop
    ledger = Ledger(root)
    progress = ledger.progress(GUIDED_CAMPAIGN, case_id)
    result = progress.get('result') or {}
    revision_id = result.get('base_revision_id')
    if not revision_id:
        raise ValueError(f'guided revision missing for {case_id}')
    project = root / f'campaigns/{GUIDED_CAMPAIGN}/project'
    revision = loop.revision_get(str(project), revision_id)['revision']
    frames = []
    eligible = 0
    con = S.connect(str(project))
    try:
        for asset_id in revision['frame_asset_ids']:
            asset, _ = S.get(con, 'assets', asset_id)
            path = S.blob_path(str(project), asset['byte_sha256'])
            if hashlib.sha256(path.read_bytes()).hexdigest() != asset['byte_sha256']:
                raise ValueError('guided frame hash mismatch')
            with Image.open(path) as image:
                image.load()
                rgba = image.convert('RGBA')
                frames.append(rgba.copy())
                from framebound.v3.intake import inspect
                eligible += int(inspect(rgba)['eligible'])
    finally:
        con.close()
    if len(frames) != 6:
        raise ValueError(f'guided output needs six poses: {case_id}')
    return _normalize_frames(frames), revision_id, eligible


def _strip(frames):
    output = Image.new('RGB', (256 * len(frames), 256), 'white')
    for index, frame in enumerate(frames):
        output.paste(frame, (index * 256, 0))
    return output


def _prompt(request):
    return (
        'You are an independent visual reviewer evaluating one ordered six-pose '
        'animation strip. Frames run left to right. Judge only the visible '
        'images; do not infer an intended arm.\n'
        'Original request:\n' + request + '\n'
        'Compare identity preservation, continuity between poses, readable '
        'action order, absence of detached or duplicated anatomy and props, and '
        'usability as six isolated poses. Legitimate holds and intentional '
        'deformation are not defects. Do not default to a perfect score: use 2 '
        'for ordinary work, 3 for a clear but imperfect result, and 4 only when '
        'all six poses pass every criterion. Cite the most consequential visible '
        'difference in the reason.\n'
        'Answer with exactly two lines: '
        'SCORES=<identity>,<continuity>,<action_order>,<artifact_absence>,<usability>; '
        'REASON=<one concise sentence>. Scores are numbers from 0 to 4. Do not '
        'repeat these instructions or return a schema.'
    )


@app.function(
    image=runtime,
    gpu='A100-80GB',
    timeout=1800,
    volumes={'/cache': hf_cache},
    retries=0,
)
def review(payloads):
    import torch
    from qwen_vl_utils import process_vision_info
    from transformers import AutoProcessor, Qwen2_5_VLForConditionalGeneration

    processor = AutoProcessor.from_pretrained(
        MODEL_ID,
        revision=MODEL_REVISION,
        trust_remote_code=True,
    )
    model = Qwen2_5_VLForConditionalGeneration.from_pretrained(
        MODEL_ID,
        revision=MODEL_REVISION,
        dtype=torch.bfloat16,
        device_map='auto',
        trust_remote_code=True,
    )
    model.eval()
    results = []
    for payload in payloads:
        image = Image.open(io.BytesIO(base64.b64decode(payload['image']))).convert('RGB')
        messages = [{
            'role': 'user',
            'content': [
                {'type': 'image', 'image': image},
                {'type': 'text', 'text': payload['prompt']},
            ],
        }]
        started = time.monotonic()
        text = processor.apply_chat_template(
            messages,
            add_generation_prompt=True,
            tokenize=False,
        )
        image_inputs, _ = process_vision_info(messages)
        inputs = processor(
            text=[text],
            images=image_inputs,
            padding=True,
            return_tensors='pt',
        ).to(model.device)
        input_length = inputs['input_ids'].shape[1]
        with torch.inference_mode():
            generated = model.generate(
                **inputs,
                do_sample=False,
                max_new_tokens=256,
            )
        text = processor.batch_decode(
            generated[:, input_length:],
            skip_special_tokens=True,
        )[0]
        results.append(dict(
            case_id=payload['case_id'],
            arm=payload['arm'],
            generated_text=text,
            elapsed_seconds=time.monotonic() - started,
        ))
    hf_cache.commit()
    return results


def _parse(text):
    match = re.search(r'SCORES\s*[=:]?\s*([^\n]+)', text, re.IGNORECASE)
    if not match:
        raise ValueError('reviewer returned no scores')
    values = [float(item) for item in re.findall(r'\b(?:[0-4](?:\.\d+)?)\b', match.group(1))][:5]
    if len(values) != 5:
        raise ValueError('reviewer returned the wrong score count')
    reason_match = re.search(r'REASON\s*[=:]?\s*(.+)', text, re.IGNORECASE)
    return dict(
        scores={key: value for key, value in zip(CRITERIA, values, strict=True)},
        reason=(reason_match.group(1).strip() if reason_match else text.strip()),
    )


@app.local_entrypoint()
def main(root: str, output: str):
    from framebound.v3.campaign.contracts import canonical
    from framebound.v3.campaign.ledger import Ledger
    root_path = Path(root).resolve()
    output_path = Path(output).resolve()
    repository = Path(__file__).resolve().parents[1]
    if output_path.is_relative_to(repository):
        raise ValueError('benchmark output must stay outside the repository')
    ledger = Ledger(root_path)
    payloads = []
    case_metadata = []
    specs = {case.id: case for case in ledger.config(RAW_CAMPAIGN).cases}
    for case_id in CONTROL_CASES:
        raw_frames, raw_request_id = _raw_frames(ledger, case_id)
        guided_frames, guided_revision_id, guided_eligible = _guided_frames(root_path, case_id)
        for arm, frames in (('raw', raw_frames), ('guided', guided_frames)):
            payloads.append(dict(
                case_id=case_id,
                arm=arm,
                prompt=_prompt(specs[case_id].request),
                image=base64.b64encode(_png(_strip(frames))).decode('ascii'),
            ))
            case_metadata.append(dict(
                case_id=case_id,
                arm=arm,
                raw_request_id=raw_request_id,
                guided_revision_id=guided_revision_id,
                guided_eligible=guided_eligible,
                guided_frames=6,
                raw_frames=0,
            ))

    reviewed = review.remote(payloads)
    results = []
    for metadata, response in zip(case_metadata, reviewed):
        record = dict(metadata, **response)
        try:
            record['review'] = _parse(response['generated_text'])
        except (ValueError, TypeError, json.JSONDecodeError) as error:
            record['review'] = dict(
                reason='Reviewer response failed the frozen output contract.',
                parse_error=f'{type(error).__name__}: {error}',
            )
        results.append(record)

    by_case = {}
    for row in results:
        by_case.setdefault(row['case_id'], {})[row['arm']] = row['review']
    outcome = {key: 0 for key in ('raw', 'guided', 'tie', 'insufficient')}
    comparisons = []
    for case_id, arms in by_case.items():
        raw = arms.get('raw', {})
        guided = arms.get('guided', {})
        if not raw.get('scores') or not guided.get('scores'):
            winner = 'insufficient'
            raw_mean = guided_mean = delta = None
        else:
            raw_mean = sum(raw['scores'].values()) / len(CRITERIA)
            guided_mean = sum(guided['scores'].values()) / len(CRITERIA)
            delta = guided_mean - raw_mean
            winner = 'guided' if delta > 0.1 else 'raw' if delta < -0.1 else 'tie'
        outcome[winner] += 1
        comparisons.append(dict(
            case_id=case_id,
            winner=winner,
            raw_mean=raw_mean,
            guided_mean=guided_mean,
            guided_minus_raw=delta,
        ))
    average_scores = {}
    for arm in ('raw', 'guided'):
        values = [
            row['review']['scores']
            for row in results
            if row['arm'] == arm and row['review'].get('scores')
        ]
        average_scores[arm] = (
            {criterion: float(sum(item[criterion] for item in values) / len(values))
             for criterion in CRITERIA}
            if values else None
        )
    numeric_scores = [
        value
        for row in results
        if row['review'].get('scores')
        for value in row['review']['scores'].values()
    ]
    reviewer_saturated = bool(
        numeric_scores and all(value == 4.0 for value in numeric_scores)
    )
    report = dict(
        schema_version='direct-vs-guided-modal-v2',
        source_campaigns=dict(raw=RAW_CAMPAIGN, guided=GUIDED_CAMPAIGN),
        cases=CONTROL_CASES,
        reviewer=dict(
            model=MODEL_ID,
            revision=MODEL_REVISION,
            license='Apache-2.0',
            runtime='Modal A100-80GB, transformers, deterministic generation',
            independence='separate multimodal reviewer scoring each six-pose strip independently',
            human_review=False,
        ),
        results=results,
        summary=dict(
            status='inconclusive_reviewer_saturation' if reviewer_saturated else 'measured',
            usable_quality_comparison=not reviewer_saturated,
            case_count=len(CONTROL_CASES),
            outcome=outcome,
            comparisons=comparisons,
            mean_scores=average_scores,
            preference_rule='Guided wins when its independent mean score exceeds raw by more than 0.1 on the 0-4 scale.',
            technical_delivery=dict(
                raw_opaque_sheets=len(CONTROL_CASES),
                raw_isolated_frames=0,
                guided_isolated_frames=sum(row['guided_eligible'] for row in case_metadata if row['arm'] == 'guided'),
                guided_frame_total=sum(row['guided_frames'] for row in case_metadata if row['arm'] == 'guided'),
            ),
        ),
        limitation=(
            'Seven matched cases are a pilot. The reviewer is an open model, not '
            'human acceptance. Raw and guided generations are existing paid outputs '
            'from the same frozen case IDs and prompts; this benchmark does not '
            'claim generalization beyond those cases.'
        ),
    )
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_bytes(canonical(report))
    print(json.dumps(dict(output=str(output_path), summary=report['summary']), indent=2))
