"""Packaged animation principles, independent of private studies and model fitting.

These are generation instructions, never measurements or approval authority.
The complete task and original references remain authoritative.
"""
from .campaign.contracts import digest

VERSION = 'animation-principles-v1'
PRINCIPLES = (
    ('identity', 'Keep the same silhouette, proportions, facial features, palette and costume details across all poses. Preserve original identity references throughout repairs.'),
    ('parts', 'Keep anatomy and object topology consistent: no missing, duplicated or detached parts. Allow intentional articulation and declared occlusion without changing body volume.'),
    ('prop', 'Keep each held prop identical in shape and scale, attached to the intended hand or support. Preserve its trajectory through occlusion; never invent an extra prop.'),
    ('entities', 'Draw only the declared subjects. One complete instance of each intended subject per pose; no ghost copies, labels, scenery or effects-only substitutes.'),
    ('contact', 'Show weight and support coherently. Hold planted contacts through their authored interval; keep grips and interactions continuous. Do not infer contact annotations from color.'),
    ('temporal', 'Use a fixed camera, common canvas, common scale and stable registration. Do not independently crop or fit each pose. Preserve authored holds and verify the last-to-first transition when looping.'),
    ('action_order', 'Arrange distinct consecutive poses in the requested reading order. Preserve anticipation, action and recovery where requested; do not substitute repeated reference poses for newly generated motion.'),
    ('artifacts', 'Keep line weight, fill, palette and edge treatment consistent. Avoid muddy edit accumulation, stray marks and texture flicker. Repair from original references rather than using an edited take as the sole identity source.'),
    ('extraction', 'Keep the complete silhouette inside its original frame with at least 2% clear margin at every edge, including cape, hair, fingers, soles and props. A tiny clipped extremity fails framing even if the rest of the border is clear. Do not hide clipping with padding or independent per-pose fitting. Use an individual full-resolution pose image when a sheet would sacrifice required subject detail. Use genuine alpha for delivery. Technical backing needs explicit segmentation or a declared extraction recipe; never erase white subject pixels by guessing.'),
)


def compile_guidance(spec: dict) -> dict:
    """Deterministic, hash-bound instructions; no provider I/O or learned claims."""
    rules = [dict(id='principle-'+category, category=category, instruction=text)
             for category, text in PRINCIPLES]
    count = len(spec['timing']['holds'])
    columns = next((n for n in (3, 4, 6, 2, 1) if count % n == 0 and count // n <= 24), 1)
    layout = dict(columns=columns, rows=count // columns, reading_order='row_major')
    prompt = '\n'.join([
        'Create an isolated 2D animation of '+spec['subjects']+'.',
        'Action: '+spec['intent'],
        'Appearance: '+spec.get('appearance', ''),
        f"Generate {count} consecutive poses on one full pose screen with exactly {columns} columns and {layout['rows']} rows, in left-to-right then top-to-bottom reading order. A separately declared submission layout takes precedence.",
        f"Native frame canvas: {spec['canvas']['width']}×{spec['canvas']['height']}. Holds: {spec['timing']['holds']}; ticks per second: {spec['timing']['ticks_per_second']}; looping: {spec['loop']}.",
        'Camera: '+spec.get('scene_camera', 'fixed canvas, controlled view'),
        'Interactions: '+spec.get('interactions', ''),
        'Preserve: '+ '; '.join(spec.get('preserve', [])),
        'Allowed changes: '+ '; '.join(spec.get('allowed_changes', [])),
        *[r['instruction'] for r in rules],
        'The task, timing, original references and declared edit scope take precedence. Guidance does not grant additional edit permission.',
    ])
    result = dict(version=VERSION, authority='advisory_only', source='packaged_principles',
                  training_required=False, private_evidence_included=False,
                  model_improvement_established=False, rules=rules, prompt=prompt, sheet_layout=layout,
                  identity_anchor_prompt='Create one neutral isolated 2D identity pose of '+spec['subjects']+'. '+spec.get('appearance','')+' One complete subject; no animation sheet, labels or scenery.',
                  review=['Check original identity and all delivered native frames.',
                          'Evaluate the actual authored playback including the loop boundary.',
                          'Retain unmeasured or unsupported quality claims as unknown.'])
    result['sha256'] = digest(result)
    return result
