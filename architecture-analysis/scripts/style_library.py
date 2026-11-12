"""Local style library; requires explicit recorded approval for accepted imports."""
from pathlib import Path
import argparse,json,hashlib,shutil,datetime

def load(p):return json.loads(Path(p).read_text(encoding='utf-8-sig'))
def default_library():
 new=Path.home()/'.workbuddy/architecture-analysis-library'
 legacy=Path.home()/'.codex/architecture-analysis-library'
 return str(legacy if (legacy.exists() and not new.exists()) else new)
def fingerprint(card):
 features=card.get('features')
 if not isinstance(features,dict) or not features:raise ValueError('Nonempty features required')
 return hashlib.sha256(json.dumps(features,ensure_ascii=False,sort_keys=True,separators=(',',':')).encode()).hexdigest()[:24]
def status(library,card):
 root=Path(library);key=fingerprint(card);idx=load(root/'index.json') if (root/'index.json').exists() else {};entry=idx.get(key)
 return {'fingerprint':key,'state':entry['state'] if entry else 'new','should_offer':entry is None}
def record(library,card,decision,approved=False,references=(),customer_material=False,customer_consent=False):
 state=status(library,card)
 if decision not in ('accept','decline'):raise ValueError('Decision must be accept or decline')
 if decision=='accept' and not approved:raise ValueError('Explicit approval is required before collecting references')
 if decision=='accept' and customer_material and not customer_consent:raise ValueError('Customer material needs separate consent')
 if decision=='accept' and state['state']=='accepted':return {**state,'unchanged':True}
 # Validate everything before creating library files.
 refs=[Path(p).resolve() for p in references]
 if decision=='accept' and any(not p.is_file() for p in refs):raise ValueError('Reference does not exist')
 root=Path(library);root.mkdir(parents=True,exist_ok=True);index_path=root/'index.json';idx=load(index_path) if index_path.exists() else {};key=state['fingerprint']
 entry={'state':'accepted' if decision=='accept' else 'declined','updated_at':datetime.datetime.now().astimezone().isoformat()}
 if decision=='accept':
  dest=root/'styles'/key;dest.mkdir(parents=True,exist_ok=True)
  for i,p in enumerate(refs):shutil.copy2(p,dest/f'ref-{i+1}{p.suffix.lower()}')
  clean={k:v for k,v in card.items() if k!='reference_paths'};clean['reference_files']=[f'ref-{i+1}{p.suffix.lower()}' for i,p in enumerate(refs)]
  (dest/'style-card.json').write_text(json.dumps(clean,ensure_ascii=False,indent=2),encoding='utf8');entry['path']=f'styles/{key}/style-card.json'
 idx[key]=entry;temp=root/'index.json.tmp';temp.write_text(json.dumps(idx,ensure_ascii=False,indent=2),encoding='utf8');temp.replace(index_path)
 return status(root,card)
def main():
 p=argparse.ArgumentParser();p.add_argument('command',choices=['status','record']);p.add_argument('card');p.add_argument('--library',default=default_library());p.add_argument('--decision',choices=['accept','decline']);p.add_argument('--approved',action='store_true');p.add_argument('--reference',action='append',default=[]);p.add_argument('--customer-material',action='store_true');p.add_argument('--customer-consent',action='store_true');a=p.parse_args();card=load(a.card)
 if a.command=='status':r=status(a.library,card)
 else:
  if not a.decision:p.error('--decision required for record')
  r=record(a.library,card,a.decision,a.approved,a.reference,a.customer_material,a.customer_consent)
 print(json.dumps(r,ensure_ascii=False))
if __name__=='__main__':main()
