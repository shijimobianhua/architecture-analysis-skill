"""Explicitly migrate V1 composition inputs; never overwrite the original."""
from pathlib import Path
from PIL import Image
import argparse,json,copy

def migrate(src,dst):
 src=Path(src).resolve();dst=Path(dst).resolve()
 if dst.exists():raise FileExistsError('Migration output exists')
 if dst.parent!=src.parent:raise ValueError('Keep migrated spec beside original so asset paths remain valid')
 old=json.loads(src.read_text(encoding='utf-8-sig'))
 if str(old.get('schema_version','1')).startswith('2'):raise ValueError('Already V2')
 new=copy.deepcopy(old);new['schema_version']='2.0';c=new['canvas'];old_dpi=c.get('dpi',96)
 if c.get('background') is None:
  if c.get('image'):
   im=Image.open(src.parent/c['image']).convert('RGB');ext=im.getextrema()
   if not all(a==b for a,b in ext):raise ValueError('Legacy implicit background cannot be inferred; specify it explicitly before migration')
   c['background']=list(im.getpixel((0,0)))
  else:c['background']='#FFFFFF'
 c['dpi']=max(300,old_dpi);roles={};keys={}
 for l in new.get('layers',[]):
  for o in l.get('operations',[]):
   if o.get('type')!='text':continue
   f=o.pop('font');size=o.pop('size',26);key=(f,size)
   if key not in keys:
    role='legacy-'+str(len(keys)+1);keys[key]=role;roles[role]={'font':f,'family':Path(f).stem,'weight':'unspecified-confirm-with-user','size':size,'unit':'px'}
   o['text_role']=keys[key]
 new['typography']={'confirmed':False,'roles':roles}
 new['migration']={'from':'1.x','previous_dpi':old_dpi,'pixel_geometry_preserved':True,'background_explicitly_preserved':True,'needs_user_confirmation':['font family/weight/size for each text role'],'note':'DPI changed to V2 minimum; pixel font sizes preserved, no claim of increased raster asset detail. Remove production-note text operations before composing.'}
 dst.write_text(json.dumps(new,ensure_ascii=False,indent=2),encoding='utf8');return new
if __name__=='__main__':
 p=argparse.ArgumentParser();p.add_argument('source');p.add_argument('destination');a=p.parse_args();migrate(a.source,a.destination);print('Migrated; typography still requires confirmation')
