"""MVP isolation gate. Raster isolation is not a semantic or artistic verdict."""
from collections import deque
import numpy as np
from PIL import Image

VERSION = 'isolated-sprite-v1'
PRINCIPLE = 'Isolated 2D characters, animals, figures or objects only; transparent surroundings, no scenery, matte, paper or baked checkerboard. Effects-only scenes are outside the MVP.'

def inspect(image):
    if image is None:
        return dict(policy=VERSION, eligible=False, reasons=['Unreadable native frame'])
    a=np.asarray(image.convert('RGBA')); alpha=a[:,:,3]
    clear=alpha<=8; visible=alpha>32
    border=np.concatenate((clear[0],clear[-1],clear[:,0],clear[:,-1]))
    transparent=float(clear.mean()); coverage=float(visible.mean()); edges=float(border.mean())
    reasons=[]
    if coverage<.0001:reasons.append('Empty or negligible foreground')
    if transparent<.05:reasons.append('Opaque background: real alpha transparency is required')
    if edges<.90:reasons.append('Background or clipped subject fills the native frame border')
    ys,xs=np.nonzero(visible)
    if len(xs):
        box=a[ys.min():ys.max()+1,xs.min():xs.max()+1]
        if box.shape[0]*box.shape[1]>.4*alpha.size and (box[:,:,3]>32).mean()>.995:
            perimeter=np.concatenate((box[0],box[-1],box[:,0],box[:,-1]))
            if ((perimeter[:,:3]>=235).all(axis=1)&(perimeter[:,3]>240)).mean()>.95:
                reasons.append('Large opaque white rectangle inside alpha padding: matte versus subject is unverified')
    return dict(policy=VERSION,eligible=not reasons,reasons=reasons,transparent_fraction=transparent,foreground_fraction=coverage,clear_border_fraction=edges,
                semantic_scope='Raster isolation only; subject identity and quality are not inferred')

def keyed(image, key=(255,0,255)):
    """Extract only an explicitly requested flat key, never guessed white scenery."""
    image=image.convert('RGBA')
    if inspect(image)['eligible']:return image,dict(operator='native-alpha',policy=VERSION)
    a=np.array(image);rgb=a[:,:,:3].astype(int);k=np.array(key)
    distance=np.max(np.abs(rgb-k),axis=2); candidates=distance<=70
    border=np.concatenate((candidates[0],candidates[-1],candidates[:,0],candidates[:,-1]))
    if border.mean()<.95:raise ValueError('Generated background is not the declared flat magenta key')
    h,w=candidates.shape;mask=np.zeros((h,w),dtype=bool);q=deque()
    for y,x in [(0,x) for x in range(w)]+[(h-1,x) for x in range(w)]+[(y,0) for y in range(h)]+[(y,w-1) for y in range(h)]:
        if candidates[y,x] and not mask[y,x]:mask[y,x]=True;q.append((y,x))
    while q:
        y,x=q.popleft()
        for ny,nx in ((y-1,x),(y+1,x),(y,x-1),(y,x+1)):
            if 0<=ny<h and 0<=nx<w and candidates[ny,nx] and not mask[ny,nx]:mask[ny,nx]=True;q.append((ny,nx))
    # The generation contract explicitly reserves this color, including closed pose gaps.
    enclosed=int((candidates & ~mask).sum());mask=candidates
    # Remove declared-key contamination only in the two-pixel boundary band.
    # Recover alpha against the nearest unpolluted subject sample; preserve interiors.
    foreground=~mask;spill=(rgb[:,:,0]>rgb[:,:,1]+30)&(rgb[:,:,2]>rgb[:,:,1]+30)&foreground
    near=np.zeros_like(mask)
    for dy,dx in ((-1,0),(1,0),(0,-1),(0,1),(-2,0),(2,0),(0,-2),(0,2)):
        shifted=np.roll(mask,(dy,dx),(0,1))
        if dy<0:shifted[dy:]=False
        if dy>0:shifted[:dy]=False
        if dx<0:shifted[:,dx:]=False
        if dx>0:shifted[:,:dx]=False
        near|=shifted
    fringe=spill&near;unresolved=fringe.copy();corrected=0
    for radius in range(1,5):
        for dy,dx in ((-radius,0),(radius,0),(0,-radius),(0,radius)):
            reference=np.roll(rgb,(dy,dx),(0,1));valid=np.roll(foreground&~spill,(dy,dx),(0,1))
            if dy<0:valid[dy:]=False
            if dy>0:valid[:dy]=False
            if dx<0:valid[:,dx:]=False
            if dx>0:valid[:,:dx]=False
            chosen=unresolved&valid
            if not chosen.any():continue
            observed=rgb[chosen].astype(float);ref=reference[chosen].astype(float);delta=ref-k
            alpha=np.clip(((observed-k)*delta).sum(axis=1)/np.maximum((delta*delta).sum(axis=1),1),.01,1)
            recovered=np.clip((observed-(1-alpha[:,None])*k)/alpha[:,None],0,255)
            a[chosen,:3]=np.rint(recovered).astype('uint8');a[chosen,3]=np.rint(alpha*255).astype('uint8')
            corrected+=int(chosen.sum());unresolved[chosen]=False
    # The reserved key is forbidden in artwork; isolated residual key specks in
    # this narrow boundary band are removed, not treated as subject color.
    residual=int(unresolved.sum());mask|=unresolved
    a[mask,3]=0;a[mask,:3]=0
    result=Image.fromarray(a)
    report=inspect(result)
    if not report['eligible']:raise ValueError('; '.join(report['reasons']))
    return result,dict(operator='declared-border-key-v1',key=list(key),max_channel_distance=70,removed_pixels=int(mask.sum()),enclosed_key_pixels=enclosed,edge_unmatting='nearest clean subject sample within 4px; two-pixel boundary band',edge_pixels=corrected,residual_boundary_key_pixels=residual,policy=VERSION)


def cell(image, *, declared_white_rules=False):
    """Remove at most eight uniform sheet-rule pixels at an outer cell edge.

    Only a full, near-black straight rule (or explicitly declared white rule) is removable. Subject pixels and
    nonuniform scenery are never inferred as a rule. Alpha is still validated.
    """
    if inspect(image)['eligible']:return keyed(image)
    a=np.array(image.convert('RGBA'));removed=[]
    original_key=np.max(np.abs(a[:,:,:3].astype(int)-np.array([255,0,255])),axis=2)<=70
    if original_key.mean()<.1:raise ValueError('No substantial declared magenta surround; candidate withheld')
    for edge in ('top','bottom','left','right'):
        def line_at(depth):
            return a[depth] if edge=='top' else a[-1-depth] if edge=='bottom' else a[:,depth] if edge=='left' else a[:,-1-depth]
        depth_to_key=None
        for depth in range(min(9,min(a.shape[:2])//4)):
            rgb=line_at(depth)[:,:3].astype(int)
            key_line=np.max(np.abs(rgb-np.array([255,0,255])),axis=1)<=70
            white_or_key=(rgb>=235).all(axis=1)|key_line
            trim=min(8,len(rgb)//4)
            # Orthogonal declared edge rules can cover the row's corners.
            # Only the bounded edge band is excluded from this inward-key test.
            declared_inward_key=(declared_white_rules and trim>0 and key_line[trim:-trim].mean()>=.95
                and white_or_key.mean()>=.98)
            if key_line.mean()>=.95 or declared_inward_key:
                depth_to_key=depth;break
            # A complete straight dark/key-hued rule, allowing codec noise.
            reserved_hue=(rgb[:,1]<30)&(np.abs(rgb[:,0]-rgb[:,2])<25)
            # Earlier edge passes replace shared rule corners with the key.
            declared_white=declared_white_rules and white_or_key.mean()>=.98
            if reserved_hue.mean()<.98 and not declared_white:break
        if depth_to_key is not None:
            for depth in range(depth_to_key):line_at(depth)[:]=[255,0,255,255];removed.append([edge,depth])
    result,recipe=keyed(Image.fromarray(a))
    recipe['uniform_sheet_rules_removed']=removed
    if declared_white_rules:recipe['white_sheet_rules_explicitly_declared']=True
    return result,recipe
