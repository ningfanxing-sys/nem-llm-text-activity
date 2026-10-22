'Build notice records and summarize endpoint formats.'
import os
os.environ.setdefault('OPENBLAS_NUM_THREADS','1');os.environ.setdefault('OMP_NUM_THREADS','1')
import hashlib
import importlib.util
import json
from pathlib import Path
import resource
import pandas as pd

BASE=Path(__file__).resolve().parents[1]
s=importlib.util.spec_from_file_location('nw_final',Path(__file__).with_name('assemble_event_features.py'))
m=importlib.util.module_from_spec(s);s.loader.exec_module(m)
assert (BASE/'SPEC_FREEZE.json').exists(), 'Freeze specification first'
POP=m.load_population()
labels=pd.read_parquet(m.LABELS,columns=['notice_id','notice_type','impact_windows_json','lifecycle','quantities_json','evidence_spans_json','propagation_paths_json'])
labels['notice_id']=labels.notice_id.astype(str)
(BASE/'records').mkdir(exist_ok=True)
R=m.rule_records(POP);L,_=m.llm_records(POP,labels);P=m.shifted(L,28)
summary={}
for arm,frame in [('R',R),('L',L),('P',P)]:
 path=BASE/'records'/f'{arm}.parquet';frame.to_parquet(path,index=False)
 summary[arm]={'records':len(frame),'notices':int(frame.notice_id.nunique()),'feature_eligible':int(frame.feature_eligible.sum()),'sha256':hashlib.sha256(path.read_bytes()).hexdigest()}
anchor=dict(zip(POP.notice_id,POP.anchor_local));inventory=[]
for row in labels.loc[labels.notice_id.isin(anchor)].itertuples(index=False):
 for i,w in enumerate(json.loads(row.impact_windows_json)):
  for field in ['start_text','end_text']:
   value=w.get(field)
   if isinstance(value,str) and value.strip():
    stamp,precision=m.parse_nem(value,anchor[row.notice_id])
    inventory.append(dict(notice_id=row.notice_id,window_index=i,field=field,text=value,parsed_nem=str(stamp) if stamp is not None else '',precision=precision or '',open_end=bool('further notice' in value.lower() or 'further advice' in value.lower()),explicit_unknown=value.strip().lower() in ('unknown','none','null','n/a','not specified')))
inv=pd.DataFrame(inventory);inv.to_csv(BASE/'event_assembly'/'label_endpoint_inventory.csv',index=False)
inv.loc[inv.parsed_nem.eq('') & ~inv.open_end & ~inv.explicit_unknown].to_csv(BASE/'event_assembly'/'unparsed_label_endpoints.csv',index=False)
summary.update(code_sha256=hashlib.sha256(Path(m.__file__).read_bytes()).hexdigest(),population=len(POP),label_endpoint_values=len(inv),unparsed_nonunknown_endpoint_count=int((inv.parsed_nem.eq('') & ~inv.open_end & ~inv.explicit_unknown).sum()),peak_rss_bytes=resource.getrusage(resource.RUSAGE_SELF).ru_maxrss)
(BASE/'event_assembly'/'BUILD_RECEIPT.json').write_text(json.dumps(summary,indent=2)+'\n')
print(json.dumps(summary,indent=2))
