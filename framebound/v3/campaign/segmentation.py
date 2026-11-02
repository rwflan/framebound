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
