"""Deterministic full-canvas layer export. Requires Pillow; no AI/API calls."""
from pathlib import Path
from PIL import Image, ImageDraw, ImageFont, ImageChops, ImageCms
import argparse,json,math,hashlib,sys
ROLES=['background','base','fills','lines','text']
ICC=ImageCms.ImageCmsProfile(ImageCms.createProfile('sRGB')).tobytes()
def read(p):return json.loads(Path(p).read_text(encoding='utf-8-sig'))
def write(p,v):Path(p).write_text(json.dumps(v,ensure_ascii=False,indent=2),encoding='utf8')
def safe(root,p):
 p=(root/p).resolve()
 if not p.is_relative_to(root.resolve()):raise ValueError('Output path must stay within delivery directory')
 return p

from job_spec import resolve_canvas,validate_typography,text_style

def canvas(spec,root):return resolve_canvas(spec,root)

def draw_ops(size,ops,root,typography,dpi):
 im=Image.new('RGBA',size);d=ImageDraw.Draw(im)
 def bounds(box):
  if box[0]<0 or box[1]<0 or box[2]>size[0] or box[3]>size[1]:raise ValueError(f'Content outside canvas: {box}')
 for item in ops:
  o=dict(item)
  for color_key in ('color','fill','outline'):
   if isinstance(o.get(color_key),list):o[color_key]=tuple(o[color_key])
  k=o['type']; color=o.get('color','#333333'); width=o.get('width',2)
  if k in ('rect','ellipse'):
   box=o['box'];bounds(box)
   getattr(d,'rectangle' if k=='rect' else 'ellipse')(box,fill=o.get('fill'),outline=o.get('outline'),width=width)
  elif k=='polygon':
   pts=o['points'];bounds((min(p[0] for p in pts),min(p[1] for p in pts),max(p[0] for p in pts),max(p[1] for p in pts)))
   d.polygon(pts,fill=o.get('fill'),outline=o.get('outline'),width=width)
  elif k in ('line','arrow'):
   pts=o['points']; pad=width/2
   bounds((min(p[0] for p in pts)-pad,min(p[1] for p in pts)-pad,max(p[0] for p in pts)+pad,max(p[1] for p in pts)+pad))
   if o.get('dash'):
    on,off=o['dash'];phase=0
    if on<=0 or off<0:raise ValueError('Invalid dash')
    for a,b in zip(pts,pts[1:]):
     dx,dy=b[0]-a[0],b[1]-a[1];length=math.hypot(dx,dy);steps=max(1,math.ceil(length))
     for j in range(steps):
      if phase%(on+off)<on:d.line([(a[0]+dx*j/steps,a[1]+dy*j/steps),(a[0]+dx*(j+1)/steps,a[1]+dy*(j+1)/steps)],fill=color,width=width)
      phase+=length/steps
   else:d.line(pts,fill=color,width=width,joint='curve')
   if k=='arrow':
    a,b=pts[-2:];theta=math.atan2(b[1]-a[1],b[0]-a[0]);n=o.get('head',16)
    poly=[b,(b[0]-n*math.cos(theta-.45),b[1]-n*math.sin(theta-.45)),(b[0]-n*math.cos(theta+.45),b[1]-n*math.sin(theta+.45))]
    bounds((min(p[0] for p in poly),min(p[1] for p in poly),max(p[0] for p in poly),max(p[1] for p in poly)))
    d.polygon(poly,fill=color)
  elif k=='text':
   font_file,font_size=text_style(o,typography,dpi);f=ImageFont.truetype(font_file,font_size);xy=o['xy'];b=d.textbbox(xy,o['text'],font=f,anchor='lt');bounds(b)
   if o.get('max_width') and b[2]-b[0]>o['max_width']:raise ValueError('Text exceeds allocated width: '+o['text'])
   d.text(xy,o['text'],font=f,fill=color,anchor='lt')
  elif k=='image':
   src=Image.open(root/o['path']).convert('RGBA');box=o['box'];bounds(box);bw,bh=box[2]-box[0],box[3]-box[1]
   scale=min(bw/src.width,bh/src.height)
   if scale>1 and not o.get('allow_upscale',False):scale=1
   if scale<=0:raise ValueError('Invalid image placement')
   src=src.resize((max(1,round(src.width*scale)),max(1,round(src.height*scale))),Image.Resampling.LANCZOS)
   x=round(box[0]+(bw-src.width)/2);y=round(box[1]+(bh-src.height)/2)
   im.alpha_composite(src,(x,y));d=ImageDraw.Draw(im)
  else:raise ValueError('Unknown operation '+k)
 return im

def export(spec_path,out):
 spec_path=Path(spec_path).resolve();root=spec_path.parent;spec=read(spec_path);size,bg,dpi=canvas(spec,root);typography=validate_typography(spec,dpi)
 out=Path(out);out.mkdir(parents=True,exist_ok=True)
 if (out/'manifest.json').exists():raise FileExistsError('Choose a new delivery directory; existing manifest preserved')
 entries=[{'role':'background','name':'background','image':Image.new('RGBA',size,bg)}]
 for layer in spec.get('layers',[]):
  role=layer['role']
  if role not in ROLES[1:]:raise ValueError('Unsupported role '+role)
  if layer.get('source'):
   im=Image.open(root/layer['source']).convert('RGBA')
   if im.size!=size:raise ValueError('Imported layer must have full canvas dimensions')
  else:im=draw_ops(size,layer.get('operations',[]),root,typography,dpi)
  if im.getchannel('A').getbbox() is None:continue
  if im.getchannel('A').getextrema()[0]==255:raise ValueError('Non-background layer needs transparent space; move full opaque underlay into background')
  entries.append({'role':role,'name':layer.get('name',role),'image':im})
 entries.sort(key=lambda e:ROLES.index(e['role']))
 flat=Image.new('RGBA',size);manifest={'schema_version':'2.0','skill_version':'3.2.0','typography':typography,'canvas':{'width':size[0],'height':size[1],'dpi':dpi,'color_space':'sRGB','origin':[0,0]},'blend':'normal','opacity':100,'layers':[],'final':'final.png','external_title':False}
 for i,e in enumerate(entries):
  filename=f'{i:02d}-{e["role"]}.png';im=e['image'];im.save(out/filename,dpi=(dpi,dpi),icc_profile=ICC)
  flat=Image.alpha_composite(flat,im)
  manifest['layers'].append({'file':filename,'role':e['role'],'name':e['name'],'alpha_bbox':list(im.getchannel('A').getbbox()),'sha256':hashlib.sha256((out/filename).read_bytes()).hexdigest()})
 flat.convert('RGB').save(out/'final.png',dpi=(dpi,dpi),icc_profile=ICC)
 write(out/'manifest.json',manifest)
 return verify(out)

def verify(out):
 out=Path(out).resolve();m=read(out/'manifest.json');c=m['canvas'];size=(c['width'],c['height']);flat=Image.new('RGBA',size);errors=[]
 if m.get('blend')!='normal' or m.get('opacity')!=100:errors.append('Unsupported blending')
 ranks=[];expected_icc=None
 for i,e in enumerate(m['layers']):
  p=safe(out,e['file']);im=Image.open(p)
  if e['role'] not in ROLES:raise ValueError('Unknown role')
  ranks.append(ROLES.index(e['role']))
  if im.mode!='RGBA' or im.size!=size:raise ValueError('Layer mode/size mismatch '+e['file'])
  a=im.getchannel('A');ext=a.getextrema()
  if a.getbbox() is None:errors.append('Empty layer '+e['file'])
  if i==0 and (e['role']!='background' or ext!=(255,255)):errors.append('Opaque background must be first')
  if i>0 and ext[0]==255:errors.append('Missing transparent space '+e['file'])
  if list(a.getbbox())!=e['alpha_bbox']:errors.append('Alpha bounds changed '+e['file'])
  if hashlib.sha256(p.read_bytes()).hexdigest()!=e['sha256']:errors.append('Layer file changed '+e['file'])
  profile=im.info.get('icc_profile')
  if expected_icc is None:expected_icc=profile
  if not profile or profile!=expected_icc:errors.append('Color profile mismatch '+e['file'])
  else:
   import io
   if 'srgb' not in ImageCms.getProfileDescription(ImageCms.ImageCmsProfile(io.BytesIO(profile))).lower():errors.append('Expected sRGB '+e['file'])
  if any(abs(v-c['dpi'])>.1 for v in im.info.get('dpi',(0,0))):errors.append('DPI mismatch '+e['file'])
  flat=Image.alpha_composite(flat,im)
 if not ranks or ranks!=sorted(ranks):errors.append('Layer order mismatch')
 actual_image=Image.open(safe(out,m['final']))
 if actual_image.info.get('icc_profile')!=expected_icc:errors.append('Final color profile mismatch')
 if any(abs(v-c['dpi'])>.1 for v in actual_image.info.get('dpi',(0,0))):errors.append('Final DPI mismatch')
 actual=actual_image.convert('RGB')
 if actual.size!=size:raise ValueError('Final image size mismatch')
 difference=ImageChops.difference(flat.convert('RGB'),actual).getbbox()
 if difference:errors.append('Recomposition differs from final')
 result={'status':'passed' if not errors else 'failed','pixels':list(size),'layer_count':len(ranks),'recomposition_difference_bbox':difference,'errors':errors}
 write(out/'verification.json',result)
 if errors:raise ValueError('; '.join(errors))
 return result

def main():
 p=argparse.ArgumentParser();s=p.add_subparsers(dest='cmd',required=True)
 a=s.add_parser('compose');a.add_argument('spec');a.add_argument('output')
 a=s.add_parser('verify');a.add_argument('output')
 a=s.add_parser('inspect');a.add_argument('image')
 args=p.parse_args()
 if args.cmd=='compose':r=export(args.spec,args.output)
 elif args.cmd=='verify':r=verify(args.output)
 else:
  im=Image.open(args.image);r={'size':im.size,'mode':im.mode,'dpi':im.info.get('dpi'),'extrema':im.convert('RGB').getextrema(),'uniform':all(a==b for a,b in im.convert('RGB').getextrema())}
 print(json.dumps(r,ensure_ascii=False))
if __name__=='__main__':main()


