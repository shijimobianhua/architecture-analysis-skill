"""Render checked road components once as a full-canvas transparent layer.

No road extraction, network, geocoding, routing or implicit CRS conversion.
Each road is one selected unbranched component; independent grades remain independent.
"""
import argparse
import hashlib
import json
import math
from pathlib import Path
from PIL import Image, ImageChops, ImageColor, ImageDraw, ImageCms


def require(condition,message):
    if not condition: raise ValueError(message)


def finite(x):
    return isinstance(x,(int,float)) and not isinstance(x,bool) and math.isfinite(x)


def point(p):
    require(isinstance(p,(list,tuple)) and len(p)==2 and all(finite(x) for x in p),'Invalid finite point.')
    return list(p)


def points(ps,minimum=2):
    require(isinstance(ps,list) and len(ps)>=minimum,'Too few geometry vertices.')
    return [point(p) for p in ps]


def distance(a,b): return math.hypot(a[0]-b[0],a[1]-b[1])


def transformed(ps,m):
    a,b,c,d,tx,ty=m
    result=[[a*x+c*y+tx,b*x+d*y+ty] for x,y in ps]
    require(all(finite(n) for p in result for n in p),'Nonfinite transformed coordinates.')
    return result


def rgba(color):
    if isinstance(color,str): return ImageColor.getcolor(color,'RGBA')
    require(isinstance(color,(list,tuple)) and len(color) in (3,4) and all(
        isinstance(n,int) and not isinstance(n,bool) and 0<=n<=255 for n in color),'Invalid RGBA color.')
    return tuple(color) if len(color)==4 else tuple(color)+(255,)


def inside(p,b):return b[0]<=p[0]<=b[2] and b[1]<=p[1]<=b[3]


def on_frame(p,b,t):
    # Exterior endpoints are allowed: the actual visible stroke is cropped to the viewport.
    return not inside(p,b) or min(abs(p[0]-b[0]),abs(p[0]-b[2]),abs(p[1]-b[1]),abs(p[1]-b[3]))<=t


def signature(kind,geom):
    if kind=='centerline':
        p=tuple(map(tuple,geom));return min(p,p[::-1])
    # Ring signatures account for rotation/reversal, not arbitrary GIS equivalence.
    rings=[]
    for ring in geom:
        p=tuple(map(tuple,ring));p=p[:-1] if p[0]==p[-1] else p
        candidates=[p[i:]+p[:i] for i in range(len(p))]
        q=p[::-1];candidates += [q[i:]+q[:i] for i in range(len(q))]
        rings.append(min(candidates))
    return tuple(rings)


def intersect(a,b,c,d):
    def cross(u,v,w):return (v[0]-u[0])*(w[1]-u[1])-(v[1]-u[1])*(w[0]-u[0])
    return cross(a,b,c)*cross(a,b,d)<0 and cross(c,d,a)*cross(c,d,b)<0


def prepare(spec):
    require(spec.get('schema_version')=='1.0','Road sidecar requires schema_version 1.0; order schema is unchanged.')
    canvas=spec['canvas'];w,h=canvas['width'],canvas['height'];dpi=canvas.get('dpi',300)
    require(all(isinstance(n,int) and not isinstance(n,bool) and n>0 for n in (w,h)),'Invalid canvas.')
    require(finite(dpi) and dpi>=300,'Road output uses final delivery PPI >=300.')
    ss=spec.get('antialias',2)
    require(isinstance(ss,int) and not isinstance(ss,bool) and ss in (1,2,3,4),'Antialias must be 1..4.')
    require(w*h*ss*ss<=64_000_000,'Raster budget exceeded; explicitly lower antialias, not canvas size.')
    viewport=spec.get('viewport',[0,0,w,h])
    require(len(viewport)==4 and all(isinstance(x,int) and not isinstance(x,bool) for x in viewport)
        and 0<=viewport[0]<viewport[2]<=w and 0<=viewport[1]<viewport[3]<=h,'Viewport must use integer canvas bounds.')
    space=spec.get('coordinate_space')
    require(space in ('source_pixels','final_pixels','map_projected'),'Explicit coordinate_space required; raw longitude/latitude is not supported.')
    if space=='map_projected':require(spec.get('crs') in ('EPSG:3857','GCJ02:WebMercator'),
        'Use a supported projected map CRS; convert other data explicitly to source pixels first.')
    matrix=spec.get('transform',[1,0,0,1,0,0])
    require(len(matrix)==6 and all(finite(n) for n in matrix) and abs(matrix[0]*matrix[3]-matrix[1]*matrix[2])>1e-15,'Invalid source-to-canvas affine transform.')
    tol=spec.get('join_tolerance_px',.5)
    require(finite(tol) and 0<=tol<=2,'Join tolerance is an explicit 0..2 pixel rounding tolerance, not a gap repair radius.')
    styles={}
    for name,style in spec['styles'].items():
        color=rgba(style['color']);width=style.get('width_px')
        if width is not None:require(finite(width) and width>0,'Positive final-pixel stroke width required.')
        casing=style.get('casing_width_px',0)
        priority=style.get('priority',0)
        require(isinstance(priority,int) and not isinstance(priority,bool),'Style priority must be an integer analysis emphasis.')
        require(finite(casing) and casing>=0,'Invalid casing width.')
        require(casing==0 or style.get('casing_color') is not None,'Casing color must be explicitly chosen, never implicit white.')
        styles[name]={'color':color,'width_px':width,'priority':priority,'casing_width_px':casing,
                      'casing_color':rgba(style['casing_color']) if casing else None}
    errors=[];warnings=[];features=[];records=[];roadids=set();seen={}
    def err(code,**data):errors.append({'code':code,**data})
    def warn(code,**data):warnings.append({'code':code,**data})
    require(isinstance(spec.get('roads'),list) and spec['roads'],'Provide selected road components.')
    for road in spec['roads']:
        rid=road['id'];require(rid not in roadids,'Duplicate road ID.');roadids.add(rid)
        require(all(road.get(k) for k in ('evidence','reason','label')),'Road needs label, selection reason and source evidence.')
        kind=road['geometry_type'];require(kind in ('centerline','surface'),'Unknown road geometry type.')
        style=styles[road['style']]
        if kind=='centerline':require(style['width_px'] is not None,'Centerline needs an expression width, not an inferred real width.')
        if kind=='surface':require(style['casing_width_px']==0,'Surface casing is not implemented; preserve supplied pavement rings.')
        z=road.get('z_order',0);require(isinstance(z,int) and not isinstance(z,bool),'z_order must be explicit integer when used.')
        structure=road.get('structure','unknown')
        require(structure in ('ground','bridge','tunnel','unknown'),'Invalid declared structure.')
        if z or structure not in ('ground','unknown'):
            require(bool(road.get('structure_evidence')),'Different grades need material evidence, not visual guessing.')
        parts={};ordered=[];previous=None;axis=[]
        require(isinstance(road.get('segments'),list) and road['segments'],'Selected component needs reference segments.')
        for segment in road['segments']:
            sid=segment['id'];require(sid not in parts,'Duplicate reference segment ID.')
            if kind=='centerline':
                raw=points(segment['points']);geom=transformed(raw,matrix)
                require(any(distance(a,b)>0 for a,b in zip(geom,geom[1:])),'Degenerate road line.')
                if previous is not None:
                    if distance(previous,geom[-1])<distance(previous,geom[0]):geom=geom[::-1]
                    gap=distance(previous,geom[0])
                    if gap>tol:err('reference_join_gap',road=rid,segment=sid,gap_px=gap)
                    elif gap>0:
                        # Only join verified subpixel rounding differences; retain original source in spec.
                        geom[0]=list(previous);warn('rounding_join_snapped',road=rid,segment=sid,gap_px=gap)
                axis += geom if previous is None else geom[1:]
                previous=geom[-1]
            else:
                rings=segment['rings'];require(isinstance(rings,list) and rings,'Surface requires outer ring, then optional holes.')
                geom=[transformed(points(ring,3),matrix) for ring in rings]
                for ring in geom:
                    area=sum(a[0]*b[1]-b[0]*a[1] for a,b in zip(ring,ring[1:]+ring[:1]))
                    require(abs(area)>1e-10,'Degenerate pavement ring.')
            sig=(kind,signature(kind,geom),z)
            if sig in seen:err('duplicate_reference_geometry',road=rid,segment=sid,other=seen[sig])
            else:seen[sig]={'road':rid,'segment':sid}
            parts[sid]=geom;ordered.append(sid)
        chosen=road.get('draw_segments',ordered)
        require(isinstance(chosen,list),'draw_segments must list reference IDs.')
        missing=[sid for sid in ordered if sid not in chosen]
        unknown=[sid for sid in chosen if sid not in parts]
        duplicate=sorted({sid for sid in chosen if chosen.count(sid)>1})
        if missing:err('missing_selected_segments',road=rid,segments=missing)
        if unknown:err('unknown_draw_segments',road=rid,segments=unknown)
        if duplicate:err('duplicate_draw_segments',road=rid,segments=duplicate)
        if kind=='surface':
            if road.get('axis'):axis=transformed(points(road['axis']),matrix)
            else:warn('surface_continuity_and_ends_need_manual_review',road=rid)
        if axis:
            for end,p in [('start',axis[0]),('end',axis[-1])]:
                terminal=(road.get('ends') or {}).get(end,{})
                reason=terminal.get('kind')
                if reason not in ('frame','road_end','analysis_node','study_limit'):
                    err('unexplained_termination',road=rid,end=end)
                elif reason=='frame':
                    if not on_frame(p,viewport,tol):err('premature_frame_termination',road=rid,end=end,point=p)
                elif not terminal.get('evidence'):err('termination_evidence_required',road=rid,end=end)
        if len(road.get('segments',[]))>1 and kind=='surface':warn('pavement_segment_seams_need_visual_review',road=rid)
        feature={'id':rid,'style':road['style'],'kind':kind,'parts':[parts[sid] for sid in ordered if sid in chosen],
                 'axis':axis,'z_order':z,'structure':structure}
        features.append(feature)
        records.append({'road':rid,'label':road['label'],'geometry_type':kind,'expected_segments':ordered,
                        'draw_segments':chosen,'z_order':z,'structure':structure,'width_is_real_measurement':False if kind=='centerline' else None})
    crossings=[]
    for i,a in enumerate(features):
        for b in features[i+1:]:
            if a['z_order']==b['z_order'] or not a['axis'] or not b['axis']:continue
            crosses=any(intersect(p,q,r,s) for p,q in zip(a['axis'],a['axis'][1:]) for r,s in zip(b['axis'],b['axis'][1:]))
            if crosses:
                upper=max((a,b),key=lambda f:f['z_order'])
                casing=styles[upper['style']]['casing_width_px']>0
                crossings.append({'roads':[a['id'],b['id']],'upper':upper['id'],'topology_connected':False,'explicit_casing':casing})
                if not casing:warn('grade_separation_needs_visual_review',roads=[a['id'],b['id']])
    report={'schema_version':'1.0','tool':'road_overlay','status':'needs_correction' if errors else 'checks_complete_review_required',
            'canvas':{'width':w,'height':h,'dpi':dpi},'viewport':viewport,'roads':records,'crossings':crossings,
            'errors':errors,'warnings':warnings,'manual_review':{'reference_completeness':'pending','base_alignment':'pending',
                'visual_hierarchy':'pending','surface_continuity':'pending','grade_separation':'pending'},
            'limits':'Only supplied selected geometry is checked; no geographic truth, road extraction, graph routing or automatic visual approval.'}
    return report,features,styles,(w,h,dpi,ss,viewport)


def paint(mask,feature,width,ss):
    d=ImageDraw.Draw(mask)
    if feature['kind']=='centerline':
        radius=width*ss/2
        for p in feature['parts']:
            ps=[(x*ss,y*ss) for x,y in p]
            d.line(ps,fill=255,width=max(1,round(width*ss)),joint='curve')
            for x,y in ps:d.ellipse((x-radius,y-radius,x+radius,y+radius),fill=255)
    else:
        for rings in feature['parts']:
            part=Image.new('L',mask.size);pd=ImageDraw.Draw(part)
            for i,ring in enumerate(rings):pd.polygon([(x*ss,y*ss) for x,y in ring],fill=255 if i==0 else 0)
            mask.paste(ImageChops.lighter(mask,part))


def render(spec):
    report,features,styles,(w,h,dpi,ss,viewport)=prepare(spec)
    if report['errors']:return None,report
    high=Image.new('RGBA',(w*ss,h*ss));groups={}
    for f in features:groups.setdefault((f['z_order'],f['style']),[]).append(f)
    require(len(groups)<=32,'Too many independent road styles/grades for the lightweight helper.')
    for (z,key),items in sorted(groups.items(),key=lambda item:(item[0][0],styles[item[0][1]]['priority'],item[0][1])):
        style=styles[key];mask=Image.new('L',high.size)
        for f in items:paint(mask,f,style['width_px'],ss)
        if style['casing_width_px']:
            casing=Image.new('L',high.size)
            for f in items:paint(casing,f,style['width_px']+2*style['casing_width_px'],ss)
            # Replacement at high resolution avoids accumulating alpha at joins/intersections.
            high.paste(style['casing_color'],(0,0),casing)
        high.paste(style['color'],(0,0),mask)
    image=high.resize((w,h),Image.Resampling.LANCZOS) if ss>1 else high
    # Final exact viewport clipping; no need to stop the reference centerline early.
    clip=Image.new('L',(w,h));ImageDraw.Draw(clip).rectangle((viewport[0],viewport[1],viewport[2]-1,viewport[3]-1),fill=255)
    image.putalpha(ImageChops.multiply(image.getchannel('A'),clip))
    if not image.getchannel('A').getbbox():
        report['errors'].append({'code':'no_visible_selected_roads'});report['status']='needs_correction';return None,report
    if image.getchannel('A').getextrema()[0]==255:
        report['errors'].append({'code':'road_layer_has_no_transparent_space'});report['status']='needs_correction';return None,report
    report['raster']={'size':[w,h],'alpha_bbox':list(image.getchannel('A').getbbox()),'same_style_alpha_accumulated':False}
    return image,report


def read(path):return json.loads(Path(path).read_text(encoding='utf-8-sig'))


def write(path,value):
    with Path(path).open('x',encoding='utf8') as f:json.dump(value,f,ensure_ascii=False,indent=2)


def main(argv=None):
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('mode',choices=['check','render']);p.add_argument('spec');p.add_argument('--out',required=True)
    a=p.parse_args(argv);out=Path(a.out)
    require(not out.exists(),'Output exists; choose a new version path.')
    spec=read(a.spec)
    if a.mode=='check':
        report=prepare(spec)[0];out.parent.mkdir(parents=True,exist_ok=True);write(out,report)
    else:
        image,report=render(spec);out.mkdir(parents=True,exist_ok=False)
        if image:
            icc=ImageCms.ImageCmsProfile(ImageCms.createProfile('sRGB')).tobytes()
            image.save(out/'roads.png',dpi=(report['canvas']['dpi'],)*2,icc_profile=icc)
            report['image']='roads.png';report['sha256']=hashlib.sha256((out/'roads.png').read_bytes()).hexdigest()
        write(out/'report.json',report)
    print(json.dumps({'status':report['status'],'errors':len(report['errors']),'warnings':len(report['warnings']),'output':str(out)},ensure_ascii=False))
    return 2 if report['errors'] else 0


if __name__=='__main__':
    try:raise SystemExit(main())
    except (ValueError,KeyError,TypeError,IndexError,OSError) as exc:raise SystemExit('Road input/output error: '+str(exc))
