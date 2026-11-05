"""Pristine-source rendering checks and bounded recursive-edit planning.

Raster descriptors are supporting observations, never a standalone sharpness or
quality score. Model judgments and edit ancestry remain separate evidence.
"""
import hashlib
from pathlib import Path
from typing import Literal
import numpy as np
from PIL import Image,ImageFilter
from pydantic import Field,model_validator
from ..v2.domain import Strict
from .character_consistency import Feature,image_digest,digest
from .character_observations import png,ObservationInvalid
from .campaign.specialists import extract_text

VERSION='pristine-render-fidelity-v3'


class Review(Strict):
    linework: Feature
    colour_separation: Feature
    material_detail: Feature
    limitation: str = Field(min_length=1)


class Lineage(Strict):
    pristine_sha256: str = Field(pattern=r'^[0-9a-f]{64}$')
    current_sha256: str = Field(pattern=r'^[0-9a-f]{64}$')
    recursive_depth: int | None = Field(default=None,ge=0)
    scope: Literal['whole_frame','repair_region'] = 'whole_frame'
    region: list[int] | None = Field(default=None,min_length=4,max_length=4)
    untouched_source_depth: int | None = Field(default=None,ge=0)
    parent_sha256s: list[str] = Field(default_factory=list)

    @model_validator(mode='after')
    def region_scope(self):
        if self.scope=='repair_region' and (self.region is None or min(self.region)<0 or self.region[2]<=self.region[0] or self.region[3]<=self.region[1]):raise ValueError('Repair-region lineage needs its exact valid rectangle')
        if self.scope=='whole_frame' and self.region is not None:raise ValueError('Whole-frame lineage must not disguise a partial region')
        return self


def next_source(lineage,*,clarity='unmeasured',max_recursive_edits=2):
    """Depth is a prevention budget, never evidence of good or bad rendering."""
    row=Lineage.model_validate(lineage)
    if max_recursive_edits<1:raise ValueError('Positive recursive edit budget required')
    if clarity not in ('pass','fail','unmeasured'):raise ValueError('Unknown clarity result')
    if clarity=='fail':return dict(action='regenerate_from_pristine',reason='Rendering degradation detected')
    if row.recursive_depth is None:return dict(action='regenerate_from_pristine',reason='Historical edit depth unknown; never assume zero')
    if row.recursive_depth>=max_recursive_edits:return dict(action='regenerate_from_pristine',reason='Recursive edit budget exhausted')
    return dict(action='bounded_edit',reason='Within edit budget; rendering checks still required')


def descriptors(image):
    """Native raster evidence; pose, material and expression can affect values."""
    im=image.convert('RGBA');a=np.asarray(im).astype(float);rgb=a[:,:,:3];mask=Image.fromarray(((a[:,:,3]>=250)*255).astype('uint8')).filter(ImageFilter.MinFilter(5));inside=np.asarray(mask)>0
    luminance=rgb@np.array([.2126,.7152,.0722]);blur=np.asarray(Image.fromarray(luminance.astype('uint8')).filter(ImageFilter.GaussianBlur(1))).astype(float)
    high=rgb.max(axis=2);low=rgb.min(axis=2);dx=np.zeros_like(luminance);dy=dx.copy();dx[:,1:]=np.abs(np.diff(luminance,axis=1));dy[1:,:]=np.abs(np.diff(luminance,axis=0))
    if inside.sum()<100:return dict(measured=False,reason='Insufficient opaque interior pixels',scope='Supporting raster descriptors only')
    values=luminance[inside]
    return dict(measured=True,contrast_p95_p05=float(np.quantile(values,.95)-np.quantile(values,.05)),edge_gradient_p90=float(np.quantile(np.hypot(dx,dy)[inside],.9)),fine_detail_rms=float(np.sqrt(np.mean((luminance[inside]-blur[inside])**2))),mean_chroma=float(((high-low)/np.maximum(high,1))[inside].mean()),scope='Supporting native raster descriptors only; not semantic quality or acceptance')


def assess(root,pristine,candidate,description,*,dispatch,persist,regions=None):
    """Compare to the immutable clean source, never to the last edited output."""
    views=[];labels=[]
    for name,pair in (regions or {}).items():
        clean_box,current_box=pair
        clean_crop,current_crop=pristine.crop(tuple(clean_box)),candidate.crop(tuple(current_box))
        common=(min(clean_crop.width,current_crop.width),min(clean_crop.height,current_crop.height))
        views.extend([png(clean_crop.resize(common,Image.Resampling.LANCZOS)),png(current_crop.resize(common,Image.Resampling.LANCZOS))])
        labels.append(dict(region=name,pristine_box=list(clean_box),candidate_box=list(current_box),comparison_dimensions=list(common),resampling='downsample-only to common native crop resolution'))
    prompt='''Compare rendering fidelity against the ORIGINAL CLEAN ART AUTHORITY in image ONE. Image TWO is a candidate that may have been edited repeatedly. Later images are paired original/candidate crops, downsampled ONLY to the smaller native crop dimensions for a fair comparison; no crop is upscaled or sharpened. Native pixel-density minima are assessed separately. Do not confuse a smaller original sample with accumulated blur. Compare line definition and purposeful detail at this matched resolution, in the declared order. Do not use an already degraded parent as the quality baseline. Judge the artwork only, ignoring transparent or technical magenta surroundings. Pose, expression and expressly requested design changes can differ; do not penalize them as rendering degradation. Here match means preserved RENDERING FIDELITY, not the same pose, pixel outlines, finger arrangement or coil geometry. A revised grip or newly articulated fingers can be judged for crisp deliberate contours without identical original finger positions. Do not mark quality uncertain solely because a valid pose/grip/design changed. Judge whether the new lines and material detail are clear and purposeful at the matched native resolution. Actual fusion, smear or lost detail still fails; genuinely insufficient resolution remains uncertain.
Return JSON only {"linework":{"status":"match|mismatch|uncertain|occluded","observed":"specific native evidence","expected":"original rendering invariant"},"colour_separation":same feature,"material_detail":same feature,"limitation":"honest limits"}.
linework: detect accumulating mushy/muddy/muggy outlines, softened facial features or fingers, smeared edges, doubled lines, waxy simplification and lost construction. Preserve the original artist's softness where intentional; do not demand universal sharpening. colour_separation: detect washed-out/greyed colours, low local contrast, colour bleeding or flattened light/shadow separation relative to the clean source. material_detail: detect lost or melted braid, leather, fabric seams, fittings and purposeful texture replaced by generic blur/noise. Inspect repaired hands and items as well as face and torso. Artificial sharpening halos, oversaturation and invented noise do NOT restore lost detail. If resolution, pose or occlusion prevents a fair comparison, return uncertain, never match. A visible localized degradation fails even when the rest of the figure is crisp. Fields under 35 words.'''
    prompt+='\nRequested design changes: '+description+'\nPaired crop order: '+str(labels)
    pristine_sha=image_digest(pristine);candidate_sha=image_digest(candidate);key='render-fidelity-'+digest([VERSION,pristine_sha,candidate_sha,prompt])[:20]
    raw=dispatch(Path(root),key,'muse-spark-1.3',prompt,[png(pristine),png(candidate),*views])
    try:review=Review.model_validate(extract_text(raw))
    except (ValueError,TypeError,KeyError) as error:
        invalid=dict(execution_id=key,raw_sha256=hashlib.sha256(raw).hexdigest(),pristine_sha256=pristine_sha,candidate_sha256=candidate_sha,error=str(error))
        persist(Path(root)/'private'/(key+'-invalid.json'),invalid)
        # Only completed malformed replies reach this branch. Transport or
        # unknown acceptance errors propagate without another provider send.
        key+='-format-recovery'
        strict=prompt+' FORMAT RECOVERY: return EXACTLY this schema. limitation MUST be a nonempty plain string, not a feature object: '+str(Review.model_json_schema())
        raw=dispatch(Path(root),key,'muse-spark-1.3',strict,[png(pristine),png(candidate),*views])
        try:review=Review.model_validate(extract_text(raw))
        except (ValueError,TypeError,KeyError) as failure:raise ObservationInvalid(key,hashlib.sha256(raw).hexdigest(),str(failure)) from failure
    checks=review.model_dump(mode='json');statuses=[getattr(review,name).status for name in ('linework','colour_separation','material_detail')]
    status='fail' if 'mismatch' in statuses else 'pass' if all(s=='match' for s in statuses) else 'unmeasured'
    evidence=dict(version=VERSION,pristine_sha256=pristine_sha,candidate_sha256=candidate_sha,execution_id=key,raw_sha256=hashlib.sha256(raw).hexdigest(),status=status,checks=checks,crops=labels,raster=dict(pristine=descriptors(pristine),candidate=descriptors(candidate)),human_approval=False)
    persist(Path(root)/'private'/(key+'-review.json'),evidence)
    return evidence


def assess_edit(root,pristine,source,candidate,box,source_evidence,description,*,dispatch,persist):
    """Review changed pixels; inherit qualified regions only with exact proof."""
    valid=(source.size==candidate.size and source_evidence.get('candidate_sha256')==image_digest(source)
           and source_evidence.get('pristine_sha256')==image_digest(pristine) and source_evidence.get('status')=='pass')
    try:
        previous=Review.model_validate(source_evidence.get('checks',{}))
        valid=valid and all(getattr(previous,k).status=='match' for k in ('linework','colour_separation','material_detail'))
    except (ValueError,TypeError):valid=False
    x0,y0,x1,y1=box;w,h=source.size
    if not (0<=x0<x1<=w and 0<=y0<y1<=h):raise ValueError('Invalid fidelity edit region')
    outside=[(0,0,w,y0),(0,y1,w,h),(0,y0,x0,y1),(x1,y0,w,y1)]
    unchanged=all(source.crop(part).tobytes()==candidate.crop(part).tobytes() for part in outside)
    if not valid or not unchanged:return assess(root,pristine,candidate,description,dispatch=dispatch,persist=persist)
    patch=assess(root,pristine,candidate.crop(box),description+' The candidate image is ONLY the edited native crop. Assess all new pixels inside this crop. Other body regions are outside the supplied candidate and must not be judged or invented; they have separately verified unchanged clean pixels.',dispatch=dispatch,persist=persist)
    evidence=dict(patch,candidate_sha256=image_digest(candidate),scope='Edited-region review plus byte-identical inheritance of previously pristine-qualified artwork',
                  patch_review=patch,source_evidence_sha256=digest(source_evidence),source_image_sha256=image_digest(source),edit_box=list(box),unchanged_outside=True)
    persist(Path(root)/'private'/('render-edit-fidelity-'+digest(evidence)[:20]+'.json'),evidence)
    return evidence
