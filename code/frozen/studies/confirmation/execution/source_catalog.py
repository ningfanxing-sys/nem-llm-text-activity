"""Key/clock-only CONF sources; numerical reads are confined to guarded host adapters.

The JSON projection scans unselected values without constructing or decoding them.
ZIP identities contain central-directory metadata; no numerical CSV row is read.
"""
from __future__ import annotations
import csv, datetime as dt, hashlib, io, json, re, tempfile, zipfile
from pathlib import Path
import pandas as pd
import pyarrow as pa
import pyarrow.parquet as pq
from runtime import ROOT, CONF, PROJ, atomic_json, file_identity, read_json, sha256
AUDIT=ROOT/'OPENED_PATHS_panels.jsonl'
AEST=dt.timezone(dt.timedelta(hours=10)); KEY_FIELDS={'notice_id','notice_key','clocks','source_day_aest','source_kind','scope_group','version_sha256','input_sha256','source_registry_path','source_registry_sha256','source_registry_line','source_text_clock_sha256'}

def opened(path,mode,purpose):
 with AUDIT.open('a') as f:f.write(json.dumps({'path':str(Path(path).resolve()),'mode':mode,'purpose':purpose,'time_utc':dt.datetime.now(dt.timezone.utc).isoformat()})+'\n')

def metadata(path):
 opened(path,'certified_metadata','source paths, hashes, clocks, schemas and frozen contract only')
 return read_json(path)

def identity(path,kind,expected=None):
 opened(path,'hash_only','opaque bytes identity; no source values decoded')
 r=file_identity(path,kind=kind)
 if expected and r['sha256']!=expected:raise ValueError('Frozen source identity mismatch: '+str(path))
 return r

def _skip(s,i):
 """Return end of any JSON value without constructing its value."""
 while i<len(s) and s[i].isspace():i+=1
 c=s[i]
 if c=='"':
  i+=1
  while i<len(s):
   if s[i]=='\\':i+=2
   elif s[i]=='"':return i+1
   else:i+=1
  raise ValueError('Unclosed JSON string')
 if c in '[{':
  closing=']' if c=='[' else '}';i+=1
  while i<len(s):
   if s[i]=='"':i=_skip(s,i)
   elif s[i] in '[{':i=_skip(s,i)
   elif s[i]==closing:return i+1
   else:i+=1
  raise ValueError('Unclosed JSON compound')
 while i<len(s) and s[i] not in ',}]\r\n':i+=1
 return i

def project_json(line,fields=KEY_FIELDS):
 dec=json.JSONDecoder();i=0;out={};seen=set()
 while i<len(line) and line[i].isspace():i+=1
 if line[i]!='{':raise ValueError('Projected source is not an object')
 i+=1
 while True:
  while i<len(line) and (line[i].isspace() or line[i]==','):i+=1
  if line[i]=='}':return out
  key,end=dec.raw_decode(line,i);i=end
  if not isinstance(key,str) or key in seen:raise ValueError('Duplicate or invalid JSON field')
  seen.add(key)
  while line[i].isspace():i+=1
  if line[i]!=':':raise ValueError('Missing JSON colon')
  i+=1
  while line[i].isspace():i+=1
  if key in fields:out[key],i=dec.raw_decode(line,i)
  else:i=_skip(line,i)

def projected_csv_ids(path):
 """IDs and frozen admission flags only; unselected CSV fields remain opaque bytes."""
 opened(path,'key_columns_only','original source notice IDs and fixed relevance/clock-valid flags only; all text cells lexically skipped')
 result=set()
 with Path(path).open('rb') as f:
  header=f.readline().decode('utf-8-sig').rstrip('\r\n').split(',');columns=('notice_id','is_relevant_operational','available_time_valid');indices=sorted(header.index(x) for x in columns);field=rb'(?:[^,"\r\n]*|"(?:[^"]|"")*")';pattern=bytearray(b'^');cursor=0
  for i in indices:
   if i-cursor:pattern.extend(b'(?:'+field+b',){'+str(i-cursor).encode()+b'}')
   pattern.extend(b'('+field+b')');pattern.extend(b',' if i!=indices[-1] else rb'(?:,|\r?\n?$)');cursor=i+1
  regex=re.compile(bytes(pattern));pending=bytearray();inside=False
  for line in f:
   pending.extend(line);inside ^= bool(line.count(b'"')%2)
   if inside:continue
   match=regex.match(pending)
   if match is None:raise ValueError('Source registry lexical key projection failed')
   cells={header[index]:match.group(j+1).strip(b'"').decode('ascii') for j,index in enumerate(indices)}
   if cells['is_relevant_operational']=='True' and cells['available_time_valid']=='True':result.add(cells['notice_id'].strip().removesuffix('.0'))
   pending.clear()
  if pending:raise ValueError('Unfinished registry CSV record')
 return result

def archive_members(path):
 """Bind outer hash plus every nested archive/member CRC, size, and chain."""
 opened(path,'zip_central_directory','archive member identities only; no numerical CSV opened')
 records=[]
 def visit(z,chain):
  for x in z.infolist():
   item={'chain':chain+[x.filename],'crc32':x.CRC,'bytes':x.file_size,'compressed_bytes':x.compress_size,'compression':x.compress_type};records.append(item)
   if x.filename.lower().endswith('.zip'):
    with tempfile.TemporaryFile() as nested:
     digest=hashlib.sha256()
     with z.open(x) as src:
      for block in iter(lambda:src.read(1024*1024),b''):nested.write(block);digest.update(block)
     item['opaque_nested_sha256']=digest.hexdigest();nested.seek(0)
     with zipfile.ZipFile(nested) as inner:visit(inner,chain+[x.filename])
 with zipfile.ZipFile(path) as z:visit(z,[])
 return records

def prepare_notice_prefix(out,scope=None):
 scope=Path(scope or PROJ/'autopilot/q1_audits/NRX/scope.jsonl');opened(scope,'key_columns_only','lexical projection of notice IDs, timestamps and provenance hashes; bodies and labels skipped')
 rows=[];seen=set();seen_keys=set()
 with scope.open() as f:
  for line in f:
   x=project_json(line)
   ident=str(x['notice_id'])
   if ident in seen or str(x['notice_key']) in seen_keys:raise ValueError('Duplicate NRX scope identity')
   seen.add(ident);seen_keys.add(str(x['notice_key']));cl=x['clocks'];available=pd.Timestamp(cl['available_time_utc'])
   if available.tzinfo is None:raise ValueError('Notice availability missing timezone')
   day=x['source_day_aest'];train='2021-10-01'<=day<='2023-12-31';window='2026-07-27'<=day<='2026-09-30'
   rows.append({'notice_id':ident,'notice_key':str(x['notice_key']),'available_utc':available.tz_convert('UTC'),'raw_time_local':cl['raw_time_local'],'source_day_aest':day,'prefix_scope':'training' if train else 'confirmation_leadin' if window else 'other_saved_prefix','clocks_json':json.dumps(cl,sort_keys=True),'input_sha256':x['input_sha256'],'version_sha256':x['version_sha256'],'source_text_clock_sha256':x['source_text_clock_sha256'],'source_registry_path':x['source_registry_path'],'source_registry_sha256':x['source_registry_sha256'],'source_registry_line':x['source_registry_line']})
 frame=pd.DataFrame(rows).sort_values(['available_utc','notice_id'],kind='stable').reset_index(drop=True)
 months=set(frame.loc[frame.prefix_scope=='training','source_day_aest'].str[:7]);expected=set(str(p) for p in pd.period_range('2021-10','2023-12',freq='M'))
 if months!=expected:raise ValueError('Saved historical notice partition support incomplete')
 # Exhaustive saved-registry source-ID survival, independent of terminal labels.
 registry=PROJ.parents[1]/'artifacts/pivot_bq/m463_corrected_notice_timing/corrected_notice_registry.csv';expected_ids=projected_csv_ids(registry)
 data26_ids=set()
 for name in ('normalized_registry.jsonl','normalized_notices.jsonl'):
  source=PROJ/'autopilot/q1_audits/DATA26/notices'/name;opened(source,'key_columns_only','saved registry notice IDs and source clocks only; bodies and fields skipped')
  with source.open() as f:
   for line in f:
    x=project_json(line,{'notice_id','source_clock_aest'})
    if '2026-03-01'<=x['source_clock_aest'][:10]<='2026-09-30':data26_ids.add(str(x['notice_id']).strip().removesuffix('.0'))
 expected_ids |= data26_ids
 if expected_ids!=seen:raise ValueError('Original saved registry/catalogue ID survival gate: missing='+str(len(expected_ids-seen))+',unexpected='+str(len(seen-expected_ids)))
 # The source-clock projection is independent of terminal label success/failure.
 path=Path(out)/'notice_prefix_keys.parquet';frame.to_parquet(path,index=False)
 return {'path':str(path.resolve()),'rows':len(frame),'training_months':sorted(months),'columns':list(frame.columns),'identity':identity(path,'notice_prefix_key_clock_list'),'scope_identity':identity(scope,'NRX immutable normalized source scope'),'window_values_read':False,'saved_registry_id_survival':True,'expected_source_ids':len(expected_ids)}

def prepare_p5min_mapping(out):
 """All fixed notice forecast join keys; existence certified by frozen key audit.

 No forecast value or LASTCHANGED is read. Host still enforces actual availability.
 """
 target=pd.date_range('2026-08-01','2026-10-01',inclusive='left',freq='5min',tz='Australia/Brisbane').tz_convert('UTC');parts=[]
 for region in ('NSW1','QLD1','SA1','TAS1','VIC1'):
  for h in (5,10,15,20,25,30):
   issue=target-pd.Timedelta(minutes=h)
   parts.append(pd.DataFrame({'region':region,'origin':issue,'target_time':target,'horizon':h,'run0':issue-pd.Timedelta(minutes=5),'run1':issue-pd.Timedelta(minutes=10),'offset0_minutes':h+5,'offset1_minutes':h+10}))
 frame=pd.concat(parts,ignore_index=True).sort_values(['target_time','region','horizon'],kind='stable');path=Path(out)/'p5min_key_mapping.parquet';frame.to_parquet(path,index=False)
 training=PROJ/'autopilot/q1_audits/B1b/development_metadata.parquet';opened(training,'key_columns_only','historical E3 exact original row IDs and issue/target/region/horizon join keys; no labels, prices or features')
 tr=pd.read_parquet(training,columns=['region','issue_time','target_time','horizon']);tr=tr.rename(columns={'issue_time':'origin'});tr['training_row_id']=range(len(tr));tr['run0']=tr.origin-pd.Timedelta(minutes=5);tr['run1']=tr.origin-pd.Timedelta(minutes=10);tr['offset0_minutes']=tr.horizon+5;tr['offset1_minutes']=tr.horizon+10;trpath=Path(out)/'p5min_training_key_mapping.parquet';tr.to_parquet(trpath,index=False)
 return {'path':str(path.resolve()),'rows':len(frame),'columns':list(frame.columns),'identity':identity(path,'E3 keys only'),'training_path':str(trpath.resolve()),'training_rows':len(tr),'training_identity':identity(trpath,'E3 historical training row join keys only'),'key_presence_source':str(PROJ/'autopilot/q1_audits/DATA26/p5min/INVENTORY.json'),'post_freeze_gates':['LASTCHANGED finite and <= issue','run+5min<=issue','exact projected duplicate equality','R0/R1 target and neighbor clocks'],'values_read':False}

def prepare_source_identities(out):
 out=Path(out);out.mkdir(parents=True,exist_ok=True);inputs={};sources={}
 def bind(p,kind,expected=None):
  p=Path(p).resolve();key=str(p)
  if key in inputs:
   if expected and inputs[key]['sha256']!=expected:raise ValueError('Conflicting source binding')
   return inputs[key]
  inputs[key]=identity(p,kind,expected);return inputs[key]
 # Preserve every original identity. Opaque hashes do not grant a value permit.
 old=metadata(CONF/'INPUT_MANIFEST.json');bind(CONF/'INPUT_MANIFEST.json','original frozen complete design source manifest')
 for r in old['inputs']:bind(r['path'],';'.join(r['roles']),r['sha256'])
 dap=PROJ/'autopilot/q1_audits/DAPANEL/SOURCE_MANIFEST.json';bind(dap,'DAPANEL historical source manifest');hist=metadata(dap)
 for r in hist['sources']:
  x=dict(r);x['table']='PRICE' if r['family']=='price' else 'REGIONSUM';sources[(r['path'],x['table'])]=x;bind(r['path'],'historical '+r['family'],r['sha256'])
 numeric=PROJ/'autopilot/q1_audits/DATA26/numeric/FILE_INVENTORY.json';bind(numeric,'DATA26 numeric schema/member inventory')
 for r in metadata(numeric):
  bind(r['path'],'confirmation numeric source',r['sha256'])
  for ref in r['sources']:
   x={'path':r['path'],'sha256':r['sha256'],'bytes':r['size_bytes'],'table':ref['table'],'family':'price' if ref['table']=='PRICE' else 'physical','month':ref['month'],'source_family':ref['source_family'],'headers':[h for h in r['headers'] if h['table']==ref['table']]};sources[(r['path'],ref['table'])]=x
 # Same C-era official source recovery relation for the January bridge.
 lamp=PROJ.parents[1];recovery=lamp/'reports/pivot_h/data/dispatchprice_continuous_recovery_manifest.csv';bind(recovery,'C historical PRICE recovery manifest');opened(recovery,'certified_metadata','January official archive path and immutable hash only')
 with recovery.open() as f:
  jan=[r for r in csv.DictReader(f) if r['month']=='2026-01' and r['verdict'].startswith(('DOWNLOADED_OFFICIAL','REUSED_OFFICIAL'))]
 if len(jan)!=1:raise ValueError('January official PRICE source is ambiguous or missing')
 r=jan[0];p=Path(r['local_path']);p=p if p.is_absolute() else lamp/p;bind(p,'Jan2026 official PRICE bridge',r['sha256']);sources[(str(p),'PRICE')]={'path':str(p),'sha256':r['sha256'],'table':'PRICE','family':'price','month':'2026-01'}
 c=PROJ/'autopilot/windows/C/build_receipt.json';bind(c,'C physical source identities');crec=metadata(c)
 for p,h in crec['sources'].items():
  if 'DISPATCHREGIONSUM' in p and '202601' in p:bind(p,'Jan2026 physical bridge',h);sources[(p,'REGIONSUM')]={'path':p,'sha256':h,'table':'REGIONSUM','family':'physical','month':'2026-01'}
 p5inventory=PROJ/'autopilot/q1_audits/DATA26/p5min/INVENTORY.json';p5=metadata(p5inventory);bind(p5inventory,'E3 key coverage');bind(p5['strict_reader_freeze'],'E3 strict key reader freeze')
 p5sources={}
 for m in p5['months']:
  for r in m['files']:bind(r['path'],'E3 confirmation P5MIN raw source',r['sha256']);p5sources[r['path']]={'path':r['path'],'sha256':r['sha256'],'month':m['month']}
 for rel in ['autopilot/q1_audits/B5/e3/p5_development.npy','autopilot/q1_audits/B5/e3/p5_development_INPUTS.json','autopilot/q1_audits/B5/e3/p5_development_PREPARATION.json','autopilot/q1_audits/RF2/final/design.json','autopilot/q1_audits/B1b/development_metadata.parquet','autopilot/q1_audits/B4/corrected_numeric.npy']:
  bind(PROJ/rel,'frozen historical RF2/E3 training dependency')
 prefix=prepare_notice_prefix(out);mapping=prepare_p5min_mapping(out)
 for r in (prefix['identity'],prefix['scope_identity'],mapping['identity'],mapping['training_identity']):inputs[r['path']]=r
 archive_paths=sorted(set(x['path'] for x in sources.values())|set(p5sources));members={p:archive_members(p) for p in archive_paths}
 cat={'schema_version':1,'state':'SOURCE_IDENTITIES_READY_GLOBAL_LABEL_GATE_PENDING','inputs':sorted(inputs.values(),key=lambda r:r['path']),'numeric_sources':list(sources.values()),'p5min_sources':list(p5sources.values()),'archive_members':members,'notice_prefix':prefix,'p5min_mapping':mapping,'numerical_values_read':False,'global_gate_unchanged':True,'path':str((out/'source_catalog.json').resolve())}
 atomic_json(out/'source_catalog.json',cat);return cat
