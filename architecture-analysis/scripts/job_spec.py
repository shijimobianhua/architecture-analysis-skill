"""V2 job decisions: pixel canvas, explicit background choice, confirmed typography."""
from pathlib import Path
from PIL import Image,ImageFont
import math,re

NOTE_RE=re.compile(r'定性推演|定性示意|待(?:项目)?(?:调研|调查)验证|制作备注')
def finite(v):return isinstance(v,(int,float)) and not isinstance(v,bool) and math.isfinite(v)
def resolve_canvas(spec,root):
 if str(spec.get('schema_version','')).split('.')[0]!='2':raise ValueError('Legacy specification: explicitly migrate to schema_version 2.0 before composing')
 c=spec['canvas'];dims=(c.get('width'),c.get('height'))
 if c.get('image'):
  with Image.open(Path(root)/c['image']) as im:
   if all(v is not None for v in dims) and dims!=im.size:raise ValueError('Canvas image and explicit dimensions conflict')
   dims=im.size
 # A canvas image supplies dimensions only. Its colors and DPI are never adopted.
 if not all(isinstance(v,int) and not isinstance(v,bool) and v>0 for v in dims):raise ValueError('Positive integer canvas dimensions required')
 if dims[0]*dims[1]>100_000_000:raise ValueError('Canvas too large for this helper')
 dpi=c.get('dpi',300)
 if not finite(dpi) or dpi<300:raise ValueError('New deliveries require dpi >= 300; existing low-DPI deliveries remain verifiable')
 bg=c.get('background')
 if bg is None:
  ref=c.get('reference_background') or {}
  if ref.get('prominent'):
   decision=ref.get('decision')
   if decision not in ('use','white'):raise ValueError('Background confirmation required for prominent reference background')
   if decision=='use':
    bg=ref.get('color')
    if bg is None:raise ValueError('Confirmed reference background color required')
  if bg is None:bg='#FFFFFF'
 if isinstance(bg,list):bg=tuple(bg)
 return dims,bg,dpi

def size_pixels(style,dpi):
 size=style.get('size');unit=style.get('unit')
 if not finite(size) or size<=0:raise ValueError('Explicit positive font size required')
 if unit not in ('pt','px'):raise ValueError('Explicit text unit pt or px required')
 return size*dpi/72 if unit=='pt' else size

def validate_typography(spec,dpi):
 has_text=any(l.get('role')=='text' or any(o.get('type')=='text' for o in l.get('operations',[])) for l in spec.get('layers',[]))
 ty=spec.get('typography') or {}
 if not has_text:return ty
 if ty.get('confirmed') is not True:raise ValueError('Typography confirmation required before composing')
 roles=ty.get('roles') or {}
 if not roles:raise ValueError('Confirmed typography roles required')
 for name,style in roles.items():
  if not style.get('font') or not style.get('family') or not style.get('weight'):raise ValueError('Font family, weight and actual font file required for '+name)
  if not Path(style['font']).is_file():raise ValueError('Font unavailable; ask user before substitution: '+str(style['font']))
  try:ImageFont.truetype(style['font'],size_pixels(style,dpi))
  except OSError as e:raise ValueError('Font unavailable; ask user before substitution') from e
 for layer in spec.get('layers',[]):
  for o in layer.get('operations',[]):
   if o.get('type')=='text':text_style(o,ty,dpi)
 return ty

def text_style(op,typography,dpi):
 role=op.get('text_role');style=(typography.get('roles') or {}).get(role)
 if style is None:raise ValueError('Each text operation must reference a confirmed text_role')
 if any(k in op for k in ('font','size','unit','family','weight')):raise ValueError('Text may not override confirmed role typography')
 if op.get('purpose')=='production_note' or NOTE_RE.search(op.get('text','')):raise ValueError('Production notes belong in handoff/internal records, not the image')
 return style['font'],size_pixels(style,dpi)
