"""Full-native individual-pose variant of the matched movement demo builder."""
import hashlib
import io
import json
from pathlib import Path

from PIL import Image

from framebound.v3.intake import framing, keyed
from framebound.v3.guidance import PRINCIPLES
from scripts.build_movement_demo import send, save, extract_image, extract_text


def decode(raw, minimum_span):
    source = Image.open(io.BytesIO(extract_image(raw))).convert('RGBA')
    if min(source.size) < 1200 or max(source.size) < 1800:
        raise ValueError('Provider returned insufficient native image resolution')
    rgba, extraction = keyed(source)
    return rgba, dict(framing=framing(rgba, minimum_subject_span=minimum_span), extraction=extraction, source_dimensions=list(source.size))


def review(root, name, brief, refs, raw, gate):
    rubric = '''Inspect ONE animation pose against the supplied identity and costume references and the exact requested brief. Return only JSON {"score":0-100,"issues":["specific observed defect"],"repair":"bounded correction instructions","wardrobe_matches":true,"complete_silhouette":true}. Check every requested garment, excluded garment, colour and construction detail; do not invent extra cloth panels or accessories. Inspect full cape, braid, fingers, limbs, soles and entire whip, including small clipped tips. Judge requested pose and right-facing view, adult identity, costume, anatomy, native detail and fixed scale. Extra figures or copied reference layouts are errors. Assess the actual pixels critically, not just presence of a figure. Automated assessment is not human approval.'''
    result = extract_text(send(root, name, 'muse-spark-1.3', rubric+'\nRequested pose: '+brief+'\nMeasured original-image framing: '+json.dumps(gate), [*refs, extract_image(raw)]))
    if (not isinstance(result, dict) or not isinstance(result.get('score'), (float,int)) or not 0 <= result['score'] <= 100
            or not isinstance(result.get('issues'), list) or not isinstance(result.get('repair'), str)
            or type(result.get('wardrobe_matches')) is not bool or type(result.get('complete_silhouette')) is not bool):
        raise ValueError('Invalid pose review')
    if not result['wardrobe_matches']:
        result['issues'].append('Costume differs from the supplied reference or requested exclusions')
    if not result['complete_silhouette']:
        result['issues'].append('Semantic review found missing or cut-off artwork')
    result['issues'].extend(gate['framing']['reasons'])
    result['repair'] += '\n'+'; '.join(gate['framing']['reasons'])
    return result


def acceptable(reviewed, gate):
    return gate['framing']['eligible'] and reviewed['wardrobe_matches'] and reviewed['complete_silhouette']


def publish(config, root, direct, refined, reports, states):
    width, height = config.get('native_canvas', [2048,2048])
    if any(im.width > width or im.height > height for im in direct+refined):
        raise ValueError('Shared native canvas would crop an original')
    for image in refined:
        check = framing(image, minimum_subject_span=config.get('minimum_subject_span', 1100))
        if not check['eligible']:
            raise ValueError('Framework publication withheld by final original-image framing check: '+'; '.join(check['reasons']))
    digest = hashlib.sha256(json.dumps(dict(version='movement-native-density-v1',reports=reports,canvas=[width,height],states=states),sort_keys=True).encode())
    for im in direct+refined:
        digest.update(json.dumps(im.size).encode())
        digest.update(im.tobytes())
    revision = digest.hexdigest()[:16]
    public = Path(config.get('publish_root', root/'published'))
    output = public/revision
    output.mkdir(parents=True, exist_ok=True)
    bounds = []
    density = {}
    first_box = direct[0].getbbox()
    ground_y = height-direct[0].height+first_box[3]
    reference_height = direct[0].height
    for lane, images in [('direct',direct),('framework',refined)]:
        density[lane] = []
        for i, im in enumerate(images):
            canvas = Image.new('RGBA',(width,height))
            # Rigid letterboxing only. No pose is upscaled, squeezed or cropped.
            offset = ((width-im.width)//2,height-im.height)
            box = im.getbbox()
            # One format-level density calibration, shared by both lanes.
            # Landscape and portrait requests have different source heights;
            # this is not silhouette fitting and never changes stored pixels.
            factor = reference_height / im.height
            density[lane].append(factor)
            bounds.append([width/2+(box[0]+offset[0]-width/2)*factor,
                           ground_y+(box[1]+offset[1]-ground_y)*factor,
                           width/2+(box[2]+offset[0]-width/2)*factor,
                           ground_y+(box[3]+offset[1]-ground_y)*factor])
            canvas.alpha_composite(im,offset)
            canvas.save(output/f'{lane}-{i}.png')
    manifest = dict(schema=2,canvas=[width,height],ground_y=ground_y,states=states,source_pixel_scales=density,
                    actor_bounds=[min(b[0] for b in bounds),min(b[1] for b in bounds),max(b[2] for b in bounds),max(b[3] for b in bounds)],
                    frame_count=len(direct),revision=revision,automated_review=True,
                    repairs_selected=sum(r['selected']!='initial' for r in reports),
                    source_mode='one-full-native-image-per-pose',
                    source_dimensions=sorted({tuple(im.size) for im in direct+refined}),
                    framework_framing_pass=True,
                    comparison='Same initial one-pose Muse images and references; identical extraction and native letterboxing; framework-only measured repairs.')
    save(public/'manifest.json',manifest)
    save(root/'private'/'published-manifest.json',manifest)
    print('published',public,revision,flush=True)


def build(config, root):
    root = Path(root)
    refs = [Path(p).read_bytes() for p in config['references']]
    direct, refined, reports, states = [], [], [], {}
    minimum_span = config.get('minimum_subject_span',1100)
    for pose in config['poses']:
        brief = config['brief']+pose['instruction']
        raw = send(root,pose['id']+'-initial','muse-image-1.0',brief,refs,image_size=pose['image_size'])
        initial, gate = decode(raw,minimum_span)
        checked = review(root,pose['id']+'-assessment',brief,refs,raw,gate)
        chosen, best_raw, best_review, best_gate = initial,raw,checked,gate
        report = dict(pose=pose['id'],initial=checked,initial_gate=gate,selected='initial',attempts=[])
        feedback = checked['repair']
        for attempt in range(config.get('max_repairs',3)):
            if acceptable(best_review,best_gate) and best_review['score'] >= 90 and not best_review['issues']:
                break
            repair_brief = (brief+'\nFramebound repair constraints:\n'+'\n'.join(text for _,text in PRINCIPLES)
                +'\nOriginal full native image must retain at least 2% clear margin around EVERY extremity. Do not repair clipping by adding padding or erasing the cape: redraw the missing pixels inside a wider composition. Preserve native detail and the exact requested costume.\nCorrect: '+feedback)
            repair_size = pose['image_size']
            horizontal = set(best_gate['framing'].get('unsafe_edges', [])) & {'left', 'right'}
            dimensions = best_gate.get('source_dimensions', [0, 1])
            already_wide = dimensions[0] > dimensions[1]
            wide = bool((horizontal or already_wide) and repair_size == '1024x1536')
            if wide:
                repair_size = '1536x1024'
                repair_brief += '\nAUTHORITATIVE FRAMING FIX: use the wider landscape canvas for this pose so the complete trailing cape, braid and forward limb fit. This supersedes portrait height/placement instructions above. Keep maximum native drawing detail and generous empty margin; no inset panels or padding-only fix.'
            suffix = f'-wide-{attempt}' if wide else f'-{attempt}'
            proposal = send(root,pose['id']+'-repair'+suffix,'muse-image-1.0',repair_brief,[*refs,extract_image(best_raw)],image_size=repair_size)
            try:
                candidate, candidate_gate = decode(proposal,minimum_span)
                candidate_review = review(root,pose['id']+'-recheck'+suffix,brief,refs,proposal,candidate_gate)
            except ValueError as error:
                report['attempts'].append(dict(rejected=str(error)))
                feedback += '\nPrevious proposal could not pass extraction or native resolution: '+str(error)
                continue
            report['attempts'].append(dict(review=candidate_review,gate=candidate_gate))
            feedback = candidate_review['repair']+'\nPrevious attempt issues: '+'; '.join(candidate_review['issues'])
            # Safe composition and correct wardrobe take precedence over a high
            # score on clipped/incorrect artwork. Never publish an unsafe best.
            if acceptable(candidate_review,candidate_gate) and (not acceptable(best_review,best_gate) or candidate_review['score'] > best_review['score']):
                chosen,best_raw,best_review,best_gate = candidate,proposal,candidate_review,candidate_gate
                report['selected'] = f'repair-{attempt}'
        report['selected_gate'] = best_gate
        report['selected_review'] = best_review
        reports.append(report)
        save(root/'private'/'assessment-summary.json',reports)
        if not acceptable(best_review,best_gate):
            raise ValueError('Framework publication withheld: '+pose['id']+' still fails framing or wardrobe checks; original and all receipts retained')
        slot = len(direct)
        direct.append(initial)
        refined.append(chosen)
        for state in pose['states']:
            spec = states.setdefault(state,dict(frames=[],duration_ticks=[],loop=state in ('idle','run')))
            spec['frames'].append(slot)
            spec['duration_ticks'].append(90 if state=='idle' else 6)
        print(pose['id'],report['selected'],'native',list(chosen.size),'framing passed',flush=True)
    publish(config,root,direct,refined,reports,states)
