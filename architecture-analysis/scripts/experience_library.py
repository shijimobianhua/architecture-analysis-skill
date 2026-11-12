"""Scoped, consent-driven experience library. Never edits skill instructions."""
from pathlib import Path
import json,hashlib,datetime,argparse,copy,shutil
CATEGORIES={'brief-interpretation','style-adaptation','general-diagram','plan-diagram','model-diagram','layer-delivery'}
SCOPE_KEYS={'diagram_types','project_types','style_tags','constraints','project_ids'}
def default_library():
 new=Path.home()/'.workbuddy/architecture-analysis-library'
 legacy=Path.home()/'.codex/architecture-analysis-library'
 return str(legacy if (legacy.exists() and not new.exists()) else new)
def load(p):return json.loads(Path(p).read_text(encoding='utf-8-sig'))
def now():return datetime.datetime.now().astimezone().isoformat()
def fingerprint(candidate):
 payload={k:candidate.get(k) for k in ['category','level','scope','issue','solution','feedback','validation']}
 return hashlib.sha256(json.dumps(payload,ensure_ascii=False,sort_keys=True,separators=(',',':')).encode()).hexdigest()[:32]
def index(root):
 p=Path(root)/'experience-index.json'
 return load(p) if p.exists() else {'schema_version':'2.0','entries':{},'reviews':{},'events':[]}
def save_index(root,data):
 root=Path(root);root.mkdir(parents=True,exist_ok=True);p=root/'experience-index.json.tmp';p.write_text(json.dumps(data,ensure_ascii=False,indent=2),encoding='utf8');p.replace(root/'experience-index.json')
def validate(c):
 if c.get('category') not in CATEGORIES:raise ValueError('Unsupported experience category')
 if c.get('level') not in ('project_specific','conditional','general_rule'):raise ValueError('Explicit experience level required')
 scope=c.get('scope',{})
 if not isinstance(scope,dict) or set(scope)-SCOPE_KEYS:raise ValueError('Unsupported applicability scope')
 if any(not isinstance(v,list) or not all(isinstance(s,str) and s for s in v) for v in scope.values()):raise ValueError('Scope values must be lists of nonempty strings')
 if c['level']=='project_specific' and not scope.get('project_ids'):raise ValueError('Project-specific experience requires project_ids')
 if c['level']=='conditional' and not any(scope.values()):raise ValueError('Conditional experience requires scope')
 for k in ['issue','solution','evidence','feedback']:
  if not c.get(k):raise ValueError('Missing experience field '+k)
 if not isinstance(c.get('validation'),dict) or c['validation'].get('status') not in ('passed','user_reported','not_tested','failed'):raise ValueError('Explicit validation status required')
 return fingerprint(c)
def status(root,batch):
 data=index(root);out=[]
 for c in batch.get('candidates',[]):
  key=validate(c);e=data['entries'].get(key);out.append({'candidate_id':c['candidate_id'],'fingerprint':key,'state':e['state'] if e else 'new','should_offer':e is None})
 reviewed=batch.get('order_id') in data['reviews']
 return {'order_already_reviewed':reviewed,'should_offer':not reviewed and any(e['should_offer'] for e in out),'candidates':out}
def review(root,batch,accept_ids,approved=False):
 if not approved:raise ValueError('Explicit user review decision required')
 if batch.get('reviewed') is not True or not batch.get('order_id'):raise ValueError('Order evaluation must precede collecting experience')
 candidates=batch.get('candidates',[]);ids=[c.get('candidate_id') for c in candidates]
 if not ids or any(not isinstance(x,str) or not x for x in ids) or len(set(ids))!=len(ids):raise ValueError('Unique candidate IDs required')
 accept_ids=set(accept_ids)
 if not accept_ids.issubset(ids):raise ValueError('Unknown selected candidate')
 data=index(root);order=batch['order_id'];signature=hashlib.sha256(json.dumps({'batch':batch,'selected':sorted(accept_ids)},ensure_ascii=False,sort_keys=True).encode()).hexdigest()
 if order in data['reviews']:
  if data['reviews'][order]['signature']==signature:return {'unchanged':True,'order_id':order}
  raise ValueError('Order already reviewed; an explicit new revision/order ID is required')
 prepared=[]
 for c in candidates:
  key=validate(c);accepted=c['candidate_id'] in accept_ids;old=data['entries'].get(key)
  # A repeated acceptance/decline cannot replace earlier authorization, feedback or revocation.
  if old:continue
  refs=[Path(p).resolve() for p in c.get('references',[])]
  if accepted:
   if refs and c.get('customer_material') and c.get('customer_consent') is not True:raise ValueError('Customer references require separate consent')
   if any(not p.is_file() for p in refs):raise ValueError('Reference missing')
  entry=copy.deepcopy(c) if accepted else {'category':c['category'],'level':c['level']};entry.pop('references',None);entry['id']=key;entry['state']='accepted' if accepted else 'declined';entry['recorded_at']=now();entry['rule_state']='candidate' if c['level']=='general_rule' else 'not_applicable';entry['history']=[]
  prepared.append((key,entry,refs if accepted else []))
 # Validation above has no writes. Old style index and reference files are never changed.
 root=Path(root)
 for key,e,refs in prepared:
  dest=root/'experiences'/key
  if refs:dest.mkdir(parents=True,exist_ok=True)
  e['reference_files']=[]
  for i,p in enumerate(refs):
   filename=f'ref-{i+1}{p.suffix.lower()}';shutil.copy2(p,dest/filename);e['reference_files'].append(f'experiences/{key}/{filename}')
  data['entries'][key]=e
 data['reviews'][order]={'signature':signature,'recorded_at':now(),'selected':sorted(accept_ids)};data['events'].append({'action':'review','order_id':order,'at':now()});save_index(root,data)
 return {'order_id':order,'accepted':sum(e['state']=='accepted' for _,e,_ in prepared),'declined':sum(e['state']=='declined' for _,e,_ in prepared)}
def query(root,context,limit=6):
 data=index(root);results=[]
 for key,e in data['entries'].items():
  if e['state']!='accepted' or e['validation']['status'] not in ('passed','user_reported'):continue
  if e['level']=='general_rule' and e.get('rule_state')!='validated':continue
  matched=0;valid=True
  for field,values in e.get('scope',{}).items():
   if not values:continue
   requested=context.get(field,[])
   if not isinstance(requested,list):raise ValueError('Query context values must be lists')
   overlap=set(v.casefold() for v in values)&set(v.casefold() for v in requested)
   if not overlap:valid=False;break
   matched+=len(overlap)
  if valid:results.append((matched,1 if e['validation']['status']=='passed' else 0,key,e))
 # No frequency, popularity, recency or inferred global style preference participates.
 results.sort(key=lambda t:(-t[0],-t[1],t[2]))
 return [dict(e,match_score=score) for score,_,_,e in results[:limit]]
def change_state(root,key,action,approved=False,reason=None,regression=None):
 if not approved:raise ValueError('Explicit approval required')
 data=index(root)
 if key not in data['entries']:raise ValueError('Unknown experience')
 e=data['entries'][key]
 if action=='revoke':
  if not reason:raise ValueError('Revocation reason required')
  if e['state']!='accepted':raise ValueError('Only accepted experience can be revoked')
  e['history'].append({'at':now(),'previous_state':e['state'],'rule_state':e['rule_state'],'reason':reason});e['state']='revoked'
 elif action=='promote':
  if e['state']!='accepted' or e['level']!='general_rule':raise ValueError('Accepted general-rule candidate required')
  if not regression or regression.get('passed') is not True or regression.get('reproductions',0)<2 or not regression.get('cases'):raise ValueError('Repeated validation and passing regression report required')
  e['history'].append({'at':now(),'previous_rule_state':e['rule_state'],'regression':regression});e['rule_state']='validated'
 else:raise ValueError('Unsupported change')
 data['events'].append({'action':action,'id':key,'at':now()});save_index(root,data);return e

def main():
 p=argparse.ArgumentParser();p.add_argument('--library',default=default_library());s=p.add_subparsers(dest='cmd',required=True)
 a=s.add_parser('status');a.add_argument('batch')
 a=s.add_parser('review');a.add_argument('batch');a.add_argument('--accept',nargs='*',required=True);a.add_argument('--approved',action='store_true')
 a=s.add_parser('query');a.add_argument('context');a.add_argument('--limit',type=int,default=6)
 a=s.add_parser('revoke');a.add_argument('id');a.add_argument('--reason',required=True);a.add_argument('--approved',action='store_true')
 a=s.add_parser('promote');a.add_argument('id');a.add_argument('--regression',required=True);a.add_argument('--approved',action='store_true')
 a=p.parse_args()
 if a.cmd=='status':out=status(a.library,load(a.batch))
 elif a.cmd=='review':out=review(a.library,load(a.batch),a.accept,a.approved)
 elif a.cmd=='query':out=query(a.library,load(a.context),a.limit)
 else:out=change_state(a.library,a.id,a.cmd,a.approved,getattr(a,'reason',None),load(a.regression) if a.cmd=='promote' else None)
 print(json.dumps(out,ensure_ascii=False,indent=2))
if __name__=='__main__':main()
