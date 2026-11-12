"""Native-font preflight and explicit anchor checks; not an automatic design judge.

Usage: layout_check.py --spec layer-spec.json --plan layout-plan.json --out report.json
Only writes a new internal report. No drawing, network, AI, resizing or spec mutation.
"""
import argparse
import hashlib
import json
import math
from pathlib import Path
from PIL import Image, ImageColor, ImageDraw, ImageFont
from job_spec import resolve_canvas, validate_typography, text_style, size_pixels


def read(path):
    return json.loads(Path(path).read_text(encoding='utf-8-sig'))


def box(value):
    if not isinstance(value, (list, tuple)) or len(value) != 4:
        raise ValueError('Expected [left,top,right,bottom].')
    if not all(isinstance(v,(int,float)) and not isinstance(v,bool) and math.isfinite(v) for v in value):
        raise ValueError('Box requires finite numbers.')
    if value[2] <= value[0] or value[3] <= value[1]:
        raise ValueError('Box must have positive width and height.')
    return list(value)


def inside(inner, outer):
    return inner[0] >= outer[0] and inner[1] >= outer[1] and inner[2] <= outer[2] and inner[3] <= outer[3]


def intersect(a,b):
    return min(a[2],b[2]) > max(a[0],b[0]) and min(a[3],b[3]) > max(a[1],b[1])


def point(value):
    if not isinstance(value,(list,tuple)) or len(value)!=2 or not all(
        isinstance(v,(int,float)) and not isinstance(v,bool) and math.isfinite(v) for v in value):
        raise ValueError('Point requires two finite numbers.')
    return list(value)


def operation(spec, ref):
    for key in ('layer','operation'):
        if not isinstance(ref.get(key),int) or isinstance(ref[key],bool) or ref[key]<0:
            raise ValueError('Operation references use nonnegative layer/operation indexes.')
    return spec['layers'][ref['layer']]['operations'][ref['operation']]


def transform(matrix,p):
    a,b,c,d,tx,ty=matrix
    return [a*p[0]+c*p[1]+tx,b*p[0]+d*p[1]+ty]


def actual_points(op):
    if op['type'] in ('polygon','line','arrow'): return [point(p) for p in op['points']]
    if op['type']=='text': return [point(op['xy'])]
    if op['type'] in ('rect','ellipse'):
        b=box(op['box']); return [b[:2],b[2:]]
    raise ValueError('Binding needs polygon/line/arrow/text/rect/ellipse; raster objects need manual inspection.')


def frame_matrix(frame,spec,root):
    """For image ops derive the actual transform from the same fit/rounding as layers.py."""
    if 'image_operation' in frame:
        op=operation(spec,frame['image_operation'])
        if op.get('type')!='image': raise ValueError('Frame reference must point to an image operation.')
        path=root/op['path']
        if frame.get('source_sha256') and hashlib.sha256(path.read_bytes()).hexdigest()!=frame['source_sha256']:
            raise ValueError('Base source changed; reassess anchors and geometry.')
        with Image.open(path) as im: sw,sh=im.size
        l,t,r,b=box(op['box']); scale=min((r-l)/sw,(b-t)/sh)
        if not op.get('allow_upscale',False): scale=min(scale,1)
        w,h=max(1,round(sw*scale)),max(1,round(sh*scale))
        x,y=round(l+(r-l-w)/2),round(t+(b-t-h)/2)
        return [w/sw,0,0,h/sh,x,y], 'image_operation'
    matrix=frame.get('matrix')
    if not isinstance(matrix,list) or len(matrix)!=6 or not all(
        isinstance(x,(int,float)) and not isinstance(x,bool) and math.isfinite(x) for x in matrix):
        raise ValueError('Declared frame requires six finite affine values.')
    if not frame.get('evidence'): raise ValueError('Declared transform needs an evidence reference.')
    if abs(matrix[0]*matrix[3]-matrix[1]*matrix[2])<1e-15: raise ValueError('Singular frame transform.')
    return matrix,'declared_transform_only'


def rgb(value):
    if isinstance(value,str): return ImageColor.getcolor(value,'RGBA')[:3]
    if isinstance(value,(list,tuple)) and len(value) in (3,4):
        if not all(isinstance(n,int) and 0<=n<=255 for n in value): raise ValueError('Invalid color channels.')
        return tuple(value[:3])
    raise ValueError('Use explicit color strings or RGB/RGBA channels.')


def check(spec,plan,root):
    root=Path(root)
    size,_,dpi=resolve_canvas(spec,root)
    typography=validate_typography(spec,dpi)
    errors=[]; warnings=[]
    def err(code,**data): errors.append({'code':code,**data})
    def warn(code,**data): warnings.append({'code':code,**data})
    choice=plan.get('density') or {}
    if choice.get('level') not in ('clear','balanced','rich') or choice.get('confirmed') is not True or not choice.get('confirmation_source'):
        err('density_confirmation_required')
    canvas=[0,0,*size]
    groups={}
    for group in plan.get('groups',[]):
        gid=group['id']
        if gid in groups: raise ValueError('Duplicate group ID: '+gid)
        groups[gid]=box(group['box'])
        if not inside(groups[gid],canvas): err('group_outside_canvas',group=gid)
        if not group.get('content_refs'): warn('group_content_needs_review',group=gid)
    if not groups: warn('information_grouping_needs_manual_review')
    texts=[]; ids=set(); source_layers=[]
    draw=ImageDraw.Draw(Image.new('L',(1,1)))
    fonts={}
    for li,layer in enumerate(spec.get('layers',[])):
        if layer.get('source'):
            source_layers.append({'layer':li,'reason':'raster layer text/geometry/palette cannot be inferred'})
        for oi,op in enumerate(layer.get('operations',[])):
            if op.get('type')=='image':
                source_layers.append({'layer':li,'operation':oi,'reason':'image content needs visual/semantic inspection'})
            if op.get('type')!='text': continue
            ident=op.get('id',f'text:{li}:{oi}')
            if ident in ids: raise ValueError('Duplicate text ID: '+ident)
            ids.add(ident)
            fp,fs=text_style(op,typography,dpi)
            if (fp,fs) not in fonts: fonts[(fp,fs)]=ImageFont.truetype(fp,fs)
            font=fonts[(fp,fs)]
            measured=list(draw.textbbox(op['xy'],op['text'],font=font,anchor='lt'))
            if not inside(measured,canvas): err('text_outside_canvas',id=ident,bbox=measured)
            if op.get('max_width') is not None and measured[2]-measured[0]>op['max_width']:
                err('text_exceeds_allocated_width',id=ident,bbox=measured)
            allocated=op.get('layout_box')
            if allocated is not None and not inside(measured,box(allocated)):
                err('text_outside_allocated_box',id=ident,bbox=measured)
            gid=op.get('group_id')
            if gid is not None:
                if gid not in groups: raise ValueError('Unknown text group: '+gid)
                if not inside(measured,groups[gid]): err('text_outside_group',id=ident,group=gid)
            else: warn('text_group_not_recorded',id=ident)
            texts.append({'id':ident,'bbox':measured,'role':op['text_role'],'group':gid,'font_px':fs})
    allowed={}
    for entry in plan.get('allowed_overlaps',[]):
        a,b=entry['a'],entry['b']
        if a not in ids or b not in ids or a==b or not entry.get('reason'):
            raise ValueError('Overlap allowance requires two existing text IDs and a reason.')
        allowed[frozenset((a,b))]=entry['reason']
    collisions=[]
    # Sweep by left edge: ordinary separated labels avoid all-pairs work.
    active=[]
    for t in sorted(texts,key=lambda x:x['bbox'][0]):
        active=[a for a in active if a['bbox'][2]>t['bbox'][0]]
        for a in active:
            if intersect(a['bbox'],t['bbox']):
                reason=allowed.get(frozenset((a['id'],t['id'])))
                collisions.append({'a':a['id'],'b':t['id'],'allowed':bool(reason),'reason':reason})
                if not reason: warn('possible_label_collision',a=a['id'],b=t['id'])
        active.append(t)
    matrices={}; geometry=[]
    for fid,frame in plan.get('frames',{}).items():
        try:
            matrices[fid]=frame_matrix(frame,spec,root)
            if matrices[fid][1]=='declared_transform_only': warn('frame_requires_manual_source_check',frame=fid)
        except (ValueError,OSError,KeyError,IndexError) as exc:
            err('invalid_or_changed_frame',frame=fid,detail=str(exc))
    for binding in plan.get('bindings',[]):
        bid=binding['id']
        if binding.get('frame') not in matrices:
            err('binding_frame_unavailable',id=bid); continue
        if not binding.get('evidence'):
            err('binding_evidence_required',id=bid); continue
        mode=binding.get('mode','coincident')
        if mode not in ('coincident','offset','external_label'): raise ValueError('Unknown binding mode.')
        offset=[0,0]
        if mode!='coincident':
            if not binding.get('reason'): raise ValueError('Intentional offset requires its reason.')
            offset=point(binding['offset'])
        tolerance=binding.get('tolerance_px',1)
        if not isinstance(tolerance,(int,float)) or isinstance(tolerance,bool) or not math.isfinite(tolerance) or tolerance<0:
            raise ValueError('Invalid explicit anchor tolerance.')
        op=operation(spec,binding['operation'])
        actual=actual_points(op)
        if 'point_indices' in binding:
            indexes=binding['point_indices']
            if not all(isinstance(i,int) and not isinstance(i,bool) and 0<=i<len(actual) for i in indexes):
                raise ValueError('Invalid operation point indexes.')
            actual=[actual[i] for i in indexes]
        expected=[transform(matrices[binding['frame']][0],point(p)) for p in binding['source_points']]
        if not expected or len(expected)!=len(actual): raise ValueError('Source and selected operation point counts must match.')
        deviations=[math.hypot(a[0]-e[0]-offset[0],a[1]-e[1]-offset[1]) for a,e in zip(actual,expected)]
        passed=max(deviations)<=tolerance
        geometry.append({'id':bid,'mode':mode,'maximum_deviation_px':max(deviations),'tolerance_px':tolerance,
                         'within_tolerance':passed,'basis':matrices[binding['frame']][1]})
        if not passed: err('anchor_mismatch',id=bid,deviation_px=max(deviations))
    if not plan.get('bindings'): warn('geometry_requires_manual_review')
    palette=plan.get('palette')
    if palette:
        if palette.get('mode') not in ('strict','flexible'): raise ValueError('Palette mode must be strict or flexible.')
        base={rgb(c) for c in palette['base_colors']}
        additions={}
        for extension in palette.get('extensions',[]):
            color=rgb(extension['color'])
            if color in additions: raise ValueError('Duplicate auxiliary color.')
            if extension.get('decision') not in ('approved','declined','pending'): raise ValueError('Invalid color decision.')
            if extension['decision']=='approved' and not all(extension.get(k) for k in ('confirmation_source','role','locations')):
                raise ValueError('Approved auxiliary color needs consent, role and location.')
            additions[color]=extension
        for li,layer in enumerate(spec.get('layers',[])):
            for oi,op in enumerate(layer.get('operations',[])):
                fields=[(k,op[k]) for k in ('color','fill','outline') if op.get(k) is not None]
                if op.get('type')=='text' and 'color' not in op: fields.append(('color','#333333'))
                if op.get('type') in ('line','arrow') and 'color' not in op: fields.append(('color','#333333'))
                for key,value in fields:
                    color=rgb(value)
                    if color in base or (palette.get('allow_grayscale') is True and color[0]==color[1]==color[2]): continue
                    addition=additions.get(color)
                    if palette['mode']=='strict' or not addition or addition['decision']!='approved':
                        err('unapproved_or_forbidden_color',layer=li,operation=oi,field=key,color=list(color))
    else: warn('palette_requires_manual_review')
    return {'schema_version':'1.0','tool':'layout_check','density':choice,
        'canvas':{'size':list(size),'ppi':dpi},
        'relative_capacity':{r:{'font_px':size_pixels(s,dpi),'width_in_font_units':size[0]/size_pixels(s,dpi),
                               'height_in_font_units':size[1]/size_pixels(s,dpi)} for r,s in typography.get('roles',{}).items()},
        'groups':[{'id':gid,'box':b,'text_count':sum(t['group']==gid for t in texts)} for gid,b in groups.items()],
        'text_boxes':texts,'label_collisions':collisions,'geometry_bindings':geometry,
        'raster_layers_requiring_inspection':source_layers,
        'errors':errors,'warnings':warnings,'status':'needs_correction' if errors else 'checks_complete_review_required',
        'manual_review':{'information_adequacy':'pending','visual_cohesion':'pending','semantic_geometry':'pending'},
        'limits':'No ideal-density score, texture/occupancy score, fact verification or automatic visual approval.'}


def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--spec',required=True); p.add_argument('--plan',required=True); p.add_argument('--out',required=True)
    a=p.parse_args()
    out=Path(a.out)
    if out.exists(): raise FileExistsError('Existing report preserved; use a new version path.')
    result=check(read(a.spec),read(a.plan),Path(a.spec).resolve().parent)
    out.parent.mkdir(parents=True,exist_ok=True)
    with out.open('x',encoding='utf8') as f: json.dump(result,f,ensure_ascii=False,indent=2)
    print(json.dumps({'status':result['status'],'errors':len(result['errors']),
                      'warnings':len(result['warnings']),'output':str(out)},ensure_ascii=False))
    return 2 if result['errors'] else 0


if __name__=='__main__': raise SystemExit(main())
