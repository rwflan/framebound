"""Predeclared model-derived isolation, never a semantic quality assessment.

Only the official pinned SAM protocol parser decodes the compressed mask. Raw
sources/responses are retained by the caller. Empty, ambiguous or scenic media
fail acquisition rather than inviting another paid segmentation attempt.
"""
import hashlib
import io
import json
import re

import numpy as np
from PIL import Image, ImageOps


def concept_for(case):
    """Use the concrete frozen design noun, never a new teacher answer."""
    match=re.match(r'Original isolated 2D (?:character|animal|figure|object): one (?:rounded|angular|compact|elongated) (.+?), distinctive ',case.request)
    if not match or not 0<len(match[1])<=160:
        raise ValueError('segmented source requires a concrete frozen design noun')
    return match[1]


def spatial_prompt(raw, *, columns=1, rows=1):
    """SAM object prompts grounded in observed ink and declared cell layout.

    Positive points are actual nontechnical source pixels, not guessed cell
    centers or semantic labels. Background corners are checked before use.
    Neither these proposals nor the model mask establishes artistic acceptance.
    """
    from meta_sam_parser import FramePrompt,PromptBox,PromptObject,PromptPoint,build_object_prompt
    if (columns,rows) not in {(1,1),(3,2)}:raise ValueError('only anchor or six-cell spatial layout supported')
    with Image.open(io.BytesIO(raw)) as source:
        if source.width*source.height>16777216 or max(source.size)>8192:raise ValueError('spatial source bound')
        displayed=ImageOps.exif_transpose(source).convert('RGB');width,height=displayed.size
    if width%columns or height%rows or (columns>1 and width//columns!=height//rows):raise ValueError('spatial source layout mismatch')
    rgb=np.asarray(displayed).astype(np.int16)
    technical=(np.min(rgb,axis=2)>=235)|((rgb[:,:,0]>=185)&(rgb[:,:,1]<=70)&(rgb[:,:,2]>=185))
    cellw,cellh=width//columns,height//rows;objects=[];boxes=[]
    for slot in range(columns*rows):
        x=slot%columns*cellw;y=slot//columns*cellh
        dx,dy=max(1,cellw//20),max(1,cellh//20)
        negative=[(x+dx,y+dy),(x+cellw-dx-1,y+dy),(x+dx,y+cellh-dy-1),(x+cellw-dx-1,y+cellh-dy-1)]
        if any(not technical[py,px] for px,py in negative):raise ValueError('spatial negative corner is not declared technical backing')
        ys,xs=np.nonzero(~technical[y+dy:y+cellh-dy,x+dx:x+cellw-dx]);xs=xs+x+dx;ys=ys+y+dy
        if len(xs)<max(4,cellw*cellh//10000):raise ValueError('no bounded nontechnical ink for spatial prompt')
        pad=max(2,min(cellw,cellh)//128)
        box=PromptBox(max(x+dx,int(xs.min())-pad),max(y+dy,int(ys.min())-pad),min(x+cellw-dx,int(xs.max())+pad+1),min(y+cellh-dy,int(ys.max())+pad+1))
        # Center and occupied quadrants spread actual-ink guidance across parts
        # and held props; no point is placed on an empty center/pose gap.
        mx,my=float(xs.mean()),float(ys.mean());positive=[]
        groups=[np.ones(len(xs),dtype=bool),*(hx&hy for hx in (xs<=mx,xs>mx) for hy in (ys<=my,ys>my))]
        for group in groups:
            if not group.any():continue
            gx,gy=xs[group],ys[group];chosen=int(np.argmin((gx-gx.mean())**2+(gy-gy.mean())**2));point=(int(gx[chosen]),int(gy[chosen]))
            if point not in positive:positive.append(point)
        points=[PromptPoint(px,py,'positive') for px,py in positive]+[PromptPoint(px,py,'negative') for px,py in negative]
        objects.append(PromptObject(slot,[FramePrompt(box=box,points=points)]))
        boxes.append(dict(object_id=str(slot),slot=slot,bounds=[box.left,box.top,box.right,box.bottom],positive_ink=[list(p) for p in positive],negative_corners=[list(p) for p in negative],observed_ink_pixels=len(xs)))
    return build_object_prompt(objects=objects,size=(width,height)),dict(operator='observed-ink-object-prompts-v2',source_size=[width,height],layout=[columns,rows],boxes=boxes,
        basis='Frozen one-subject-per-cell layout; positive points are observed nontechnical pixels, negative points verified technical backing. Acquisition guidance only, never semantic labels')


def isolate(raw, response, *, columns=1, rows=1):
    from meta_sam_parser import CompletedOutcome, image_segmentation_format, decode_mask_to_raster
    with Image.open(io.BytesIO(raw)) as source:
        if source.width*source.height>16777216 or max(source.size)>8192:
            raise ValueError('segmentation source exceeds media bound')
        image=ImageOps.exif_transpose(source).convert('RGBA')
    width,height=image.size
    if width%columns or height%rows or (columns>1 and width//columns!=height//rows):
        raise ValueError('segmentation source does not match declared cell layout')
    body=json.loads(response)
    if body.get('status')!='completed':raise ValueError('segmentation response not completed')
    text=''.join(p.get('text','') for item in body.get('output',[]) for p in item.get('content',[]) if p.get('type')=='output_text')
    if len(text)>16*1024**2:raise ValueError('segmentation text bound')
    if not text.strip():raise ValueError('completed segmentation returned no matches')
    dimensions=re.findall(r'<\|box;[^|]*?;w=(\d+);h=(\d+)[^|]*\|>',text)
    if not dimensions or any((int(w),int(h))!=(width,height) for w,h in dimensions):
        raise ValueError('segmentation source dimensions do not match original')
    parser=image_segmentation_format().create_parser();parser.push(text)
    result=parser.finish(CompletedOutcome()).result
    if result.diagnostics:raise ValueError('segmentation protocol diagnostics; no inferred mask')
    masks=[record for record in result.records if record.kind=='mask']
    if len(masks)!=columns*rows:raise ValueError('segmentation must identify exactly one complete subject per cell')
    alpha=Image.new('L',image.size);seen=set();records=[]
    cellw,cellh=width//columns,height//rows
    for record in masks:
        bounds=record.bounds;box=(bounds.left,bounds.top,bounds.right,bounds.bottom)
        if any(int(v)!=v for v in box):raise ValueError('noninteger segmentation bounds')
        left,top,right,bottom=map(int,box)
        if not (0<=left<right<=width and 0<=top<bottom<=height):raise ValueError('segmentation outside source')
        col,row=left//cellw,top//cellh
        if col>=columns or row>=rows or right>(col+1)*cellw or bottom>(row+1)*cellh:
            raise ValueError('segmentation crosses cell boundary')
        slot=row*columns+col
        if slot in seen:raise ValueError('multiple segmented subjects in one cell')
        seen.add(slot)
        if record.mask.width*record.mask.height>16777216:raise ValueError('mask area bound')
        scale=min((right-left)/record.mask.width,(bottom-top)/record.mask.height)
        if abs(record.mask.width*scale-(right-left))>2 or abs(record.mask.height*scale-(bottom-top))>2:
            raise ValueError('segmentation raster aspect differs from source bounds')
        raster=decode_mask_to_raster(record.mask)
        mask=Image.frombytes('L',(record.mask.width,record.mask.height),bytes(v*255 for v in raster))
        # SAM may quantize a large box-local mask to 1024 pixels. Explicitly
        # map it back to its half-open source bounds; never paste unscaled.
        mask=mask.resize((right-left,bottom-top),Image.Resampling.NEAREST)
        foreground=mask.getbbox()
        if not foreground:raise ValueError('empty segmentation')
        margin=max(1,min(cellw,cellh)//50)
        tight=(left+foreground[0],top+foreground[1],left+foreground[2],top+foreground[3])
        if not (tight[0]>=col*cellw+margin and tight[1]>=row*cellh+margin and tight[2]<=(col+1)*cellw-margin and tight[3]<=(row+1)*cellh-margin):
            raise ValueError('segmented subject clips cell margin')
        alpha.paste(mask,(left,top))
        records.append(dict(object_id=record.object_id,slot=slot,bounds=list(box),mask_size=[record.mask.width,record.mask.height],raster_sha256=hashlib.sha256(raster).hexdigest()))
    rgb=np.asarray(image)[:,:,:3].astype(np.int16);selected=np.asarray(alpha)>0
    # The new source contract permits flat white or magenta technical backing,
    # not scenes/paper. Per-cell checks prevent a clean cell hiding a bad one.
    technical=(np.min(rgb,axis=2)>=235)|((rgb[:,:,0]>=185)&(rgb[:,:,1]<=70)&(rgb[:,:,2]>=185))
    proofs=[]
    for slot in range(columns*rows):
        x=slot%columns*cellw;y=slot//columns*cellh
        outside=~selected[y:y+cellh,x:x+cellw];allowed=technical[y:y+cellh,x:x+cellw]
        if outside.mean()<.25:raise ValueError('segmentation leaves insufficient technical surroundings')
        fraction=float(allowed[outside].mean())
        if fraction<.98:raise ValueError('nontechnical background outside mask; scenes and textured sources excluded')
        proofs.append(fraction)
    image.putalpha(alpha)
    return image,dict(operator='sam-isolation-v5',model='sam-3.1',source_sha256=hashlib.sha256(raw).hexdigest(),
        response_sha256=hashlib.sha256(response).hexdigest(),parser_commit='9348a8a791d3e5b6417232227e32e10464cdf49f',
        mask_mapping='official decoded box-local binary raster; NEAREST to half-open native bounds before any image resize',
        masks=records,technical_background_fraction=proofs,minimum=.98,
        meaning='Model-derived structural isolation only; independent alpha intake and semantic assessment still required')


def raw_clip_check(raw, recipe):
    """Reject source-connected ink at an edge before any paid mask can hide it."""
    from collections import deque
    with Image.open(io.BytesIO(raw)) as source:
        if source.width*source.height>16777216:
            raise ValueError('raw clipping source bound')
        rgb=np.asarray(ImageOps.exif_transpose(source).convert('RGB')).astype(np.int16)
    technical=(rgb.min(axis=2)>=235)|((rgb[:,:,0]>=185)&(rgb[:,:,1]<=70)&(rgb[:,:,2]>=185))
    ink=~technical
    height,width=ink.shape
    seen=np.zeros((height,width),dtype=bool)
    queue=deque()
    for x,y in recipe['boxes'][0]['positive_ink']:
        if not seen[y,x]:
            seen[y,x]=True
            queue.append((y,x))
    while queue:
        y,x=queue.popleft()
        for ny,nx in ((y-1,x),(y+1,x),(y,x-1),(y,x+1)):
            if 0<=ny<height and 0<=nx<width and ink[ny,nx] and not seen[ny,nx]:
                seen[ny,nx]=True
                queue.append((ny,nx))
    ys,xs=np.nonzero(seen)
    margin=max(1,min(width,height)//50)
    if not len(xs) or xs.min()<margin or ys.min()<margin or xs.max()>=width-margin or ys.max()>=height-margin:
        raise ValueError('observed raw ink component clips native cell; no mask can hide it')
    return dict(operator='observed-ink-raw-cell-clip-v1',
                bounds=[int(xs.min()),int(ys.min()),int(xs.max())+1,int(ys.max())+1],margin=margin)


def whitespace_reflow(raw):
    """Cut on observed technical whitespace, then pad six common-size cells.

    No foreground is resized, erased or invented. Nominal pose centers share
    one camera/scale convention; the original source and every crop stay bound.
    """
    with Image.open(io.BytesIO(raw)) as original:
        if original.width*original.height>16777216:raise ValueError('whitespace source bound')
        image=ImageOps.exif_transpose(original).convert('RGB')
    width,height=image.size
    if width%3 or height%2 or width//3!=height//2:raise ValueError('six square nominal poses required')
    rgb=np.asarray(image).astype(np.int16)
    technical=(rgb.min(axis=2)>=235)|((rgb[:,:,0]>=185)&(rgb[:,:,1]<=70)&(rgb[:,:,2]>=185))
    def boundary(clear,nominal,radius):
        lo=max(1,nominal-radius);hi=min(len(clear)-1,nominal+radius)
        runs=[];start=None
        for i in range(lo,hi):
            if clear[i] and start is None:start=i
            if start is not None and (not clear[i] or i==hi-1):
                end=i if not clear[i] else i+1;runs.append((start,end));start=None
        if not runs:raise ValueError('no real whitespace separating poses')
        left,right=max(runs,key=lambda r:(r[1]-r[0],-abs((r[0]+r[1])/2-nominal)))
        if right-left<4:raise ValueError('insufficient whitespace between poses')
        return (left+right)//2
    split=boundary(technical.all(axis=1),height//2,height//6)
    cells=[];centers=[];clips=[]
    for row,(top,bottom) in enumerate(((0,split),(split,height))):
        clear=technical[top:bottom].all(axis=0)
        first=boundary(clear,width//3,width//8);second=boundary(clear,2*width//3,width//8)
        if first>=second:raise ValueError('ambiguous whitespace pose order')
        for col,(left,right) in enumerate(((0,first),(first,second),(second,width))):
            bounds=[left,top,right,bottom];crop=image.crop(bounds);buf=io.BytesIO();crop.save(buf,format='PNG')
            _,proposal=spatial_prompt(buf.getvalue());clip=raw_clip_check(buf.getvalue(),proposal)
            cells.append(bounds);centers.append((col*(width//3)+width//6,row*(height//2)+height//4));clips.append(clip)
    # Common square size preserves one scale across all six poses. Original
    # nominal centers stay aligned; only known technical backing is padded.
    radius=3*(width//3)//4 # frozen 1.5 nominal-cell view, identical across sheets
    side=2*radius
    if 6*side*side>16777216:raise ValueError('reflowed source bound')
    output=Image.new('RGB',(3*side,2*side),'white');records=[]
    for slot,(bounds,(cx,cy),clip) in enumerate(zip(cells,centers,clips)):
        original_bounds=list(bounds);left,top,right,bottom=bounds
        bounds=[max(left,cx-radius),max(top,cy-radius),min(right,cx+radius),min(bottom,cy+radius)]
        def ink_count(box):
            l,t,r,b=box;return int((~technical[t:b,l:r]).sum())
        if ink_count(bounds)!=ink_count(original_bounds):raise ValueError('pose exceeds frozen common camera extent; no foreground can be trimmed')
        buf=io.BytesIO();image.crop(bounds).save(buf,format='PNG');_,proposal=spatial_prompt(buf.getvalue());render_clip=raw_clip_check(buf.getvalue(),proposal)
        left,top,right,bottom=bounds;offset=(radius+left-cx,radius+top-cy)
        output.paste(image.crop(bounds),(slot%3*side+offset[0],slot//3*side+offset[1]))
        records.append(dict(slot=slot,source_bounds=bounds,original_whitespace_bounds=original_bounds,nominal_center=[cx,cy],cell_offset=list(offset),raw_clip=clip,render_clip=render_clip,trim='technical backing only, foreground count unchanged'))
    buf=io.BytesIO();output.save(buf,format='PNG');rendered=buf.getvalue()
    return rendered,dict(operator='observed-whitespace-reflow-v2',source_sha256=hashlib.sha256(raw).hexdigest(),output_sha256=hashlib.sha256(rendered).hexdigest(),source_size=[width,height],output_size=list(output.size),cell_size=side,cells=records,resampling='NONE; foreground RGB pixels retained; only observed technical backing may be trimmed',padding='explicit pure white technical backing only; no foreground synthesis')


def validate_reflow_masks(image,recipe):
    """Validate unpadded source areas so added backing cannot dilute gates."""
    side=recipe['cell_size'];proofs=[]
    for record in recipe['cells']:
        slot=record['slot'];left,top,right,bottom=record['source_bounds'];width,height=right-left,bottom-top
        ox,oy=record['cell_offset'];tile=image.crop((slot%3*side,slot//3*side,(slot%3+1)*side,(slot//3+1)*side))
        native=tile.crop((ox,oy,ox+width,oy+height));alpha=np.asarray(native.getchannel('A'))>0
        if int((np.asarray(tile.getchannel('A'))>0).sum())!=int(alpha.sum()):raise ValueError('mask selected synthetic technical padding')
        bounds=native.getchannel('A').getbbox();margin=max(1,min(width,height)//50)
        if not bounds or bounds[0]<margin or bounds[1]<margin or bounds[2]>width-margin or bounds[3]>height-margin:raise ValueError('mask clips original whitespace cell margin')
        rgb=np.asarray(native)[:,:,:3].astype(np.int16);technical=(rgb.min(axis=2)>=235)|((rgb[:,:,0]>=185)&(rgb[:,:,1]<=70)&(rgb[:,:,2]>=185));outside=~alpha
        if outside.mean()<.25:raise ValueError('original whitespace cell has insufficient surroundings')
        fraction=float(technical[outside].mean())
        if fraction<.98:raise ValueError('nontechnical background outside mask in original whitespace cell')
        proofs.append(dict(slot=slot,technical_background_fraction=fraction,surroundings_fraction=float(outside.mean()),native_margin=margin,basis='original unpadded source crop, never synthetic padding'))
    return proofs
