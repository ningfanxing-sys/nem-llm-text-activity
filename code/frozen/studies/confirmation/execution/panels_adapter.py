"""Complete, bounded CONF numerical panels; no source I/O or fitting on import.

Pure functions accept only caller-provided frames/stores and are tested synthetically.
The host entry validates the original complete-global-input permit before any value read.
"""
from __future__ import annotations
import csv, gc, io, json, resource, shutil, sys, tempfile, zipfile
from pathlib import Path
import numpy as np
import pandas as pd
import pyarrow as pa
import pyarrow.parquet as pq
from runtime import ROOT, CONF, PROJ, atomic_json, conf_module, file_identity, read_json, sha256
from source_catalog import opened, archive_members
TZ='Australia/Brisbane';FIVE=300_000_000_000;HOUR=12*FIVE;DAY=24*HOUR;NAT=np.iinfo(np.int64).min
REGIONS=('NSW1','QLD1','SA1','TAS1','VIC1');NEWS_REGIONS=('NSW1','QLD1','TAS1')
FIELDS=('RRP','TOTALDEMAND','AVAILABLEGENERATION','DISPATCHABLEGENERATION','NETINTERCHANGE','DEMANDFORECAST')
NAMES=('price',)+tuple('phys_'+f.lower() for f in FIELDS[1:])
NEIGH={'NSW1':('QLD1','VIC1'),'QLD1':('NSW1',),'SA1':('VIC1',),'TAS1':('VIC1',),'VIC1':('NSW1','SA1','TAS1')}
NEWS_EXPECTED_ROWS=15408;NOTICE_EXPECTED_ROWS=527040
P5_COLUMNS=['p5_rrp','p5_gap','p5_rev','p5_max_run','p5_demand','p5_margin','p5_netinterchange','p5_nbr_rrp']
NEWS_NUMERIC=['region_code','horizon']+['target_'+x+'_'+t for x in ('hour','weekday','month') for t in ('sin','cos')]+[c for name in NAMES for k in range(1,73) for c in (f'{name}_lag_{k:02d}',f'{name}_lag_{k:02d}_observed')]

def ns(s):return pd.DatetimeIndex(s).as_unit('ns').asi8

def aest(value):return pd.Timestamp(value,tz=TZ).tz_convert('UTC')

def check_rss():
 peak=resource.getrusage(resource.RUSAGE_SELF).ru_maxrss;peak=int(peak if sys.platform=='darwin' else peak*1024)
 if peak>=2*1024**3:raise MemoryError('CONF numerical build exceeds 2GiB job ceiling')
 return peak

def clocks(values):
 t=pd.to_datetime(values,format='mixed',errors='coerce')
 return pd.DatetimeIndex(t).tz_localize(TZ).tz_convert('UTC').as_unit('ns').asi8

def same(a,b):return np.array_equal(a,b,equal_nan=True)

class RawStore:
 """Disk-backed fixed five-minute grid; exact duplicate records collapse."""
 def __init__(self,start,end,out=None,regions=REGIONS):
  self.start=pd.Timestamp(start).value;self.end=pd.Timestamp(end).value;self.n=(self.end-self.start)//FIVE+1;self.regions=tuple(regions)
  shapes={'values':((len(regions),self.n,6),'float64',np.nan),'price_clock':((len(regions),self.n),'int64',NAT),'seen':((len(regions),self.n,2),'bool',False)}
  for name,(shape,dtype,fill) in shapes.items():
   if out is None:a=np.full(shape,fill,dtype=dtype)
   else:
    Path(out).mkdir(parents=True,exist_ok=True);a=np.lib.format.open_memmap(Path(out)/(name+'.npy'),mode='w+',dtype=dtype,shape=shape);a[:]=fill
   setattr(self,name,a)
  self.duplicates=0;self.receipts=[]
 def consume(self,frame,table):
  price=table=='PRICE';cols=['SETTLEMENTDATE','REGIONID']+(['RRP','LASTCHANGED'] if price else list(FIELDS[1:]));d=frame[cols].copy();d['end']=clocks(d.SETTLEMENTDATE);d=d.drop(columns='SETTLEMENTDATE')
  if (d.end==NAT).any() or ((d.end-self.start)%FIVE!=0).any():raise ValueError('Invalid/off-grid numeric source key')
  d=d.loc[d.REGIONID.isin(self.regions)&(d.end>=self.start)&(d.end<=self.end)]
  for col in cols[2:]:d[col]=clocks(d[col]) if col=='LASTCHANGED' else pd.to_numeric(d[col],errors='coerce')
  before=len(d);d=d.drop_duplicates();self.duplicates+=before-len(d)
  if d.duplicated(['REGIONID','end']).any():raise ValueError('Conflicting projected source records in chunk')
  fam=0 if price else 1;dst=slice(0,1) if price else slice(1,6)
  for r,part in d.groupby('REGIONID'):
   ri=self.regions.index(r);idx=((part.end.to_numpy()-self.start)//FIVE).astype('int64');v=part[['RRP'] if price else list(FIELDS[1:])].to_numpy('float64');seen=self.seen[ri,idx,fam]
   if seen.any():
    if not same(self.values[ri,idx[seen],dst],v[seen]):raise ValueError('Conflicting numeric values across members or files')
    if price and not np.array_equal(self.price_clock[ri,idx[seen]],part.LASTCHANGED.to_numpy()[seen]):raise ValueError('Conflicting PRICE source clocks')
    self.duplicates+=int(seen.sum())
   self.values[ri,idx,dst]=v;self.seen[ri,idx,fam]=True
   if price:self.price_clock[ri,idx]=part.LASTCHANGED.to_numpy('int64')
 def take(self,region,ends):
  ri=self.regions.index(region);ends=np.asarray(ends,dtype='int64');idx=(ends-self.start)//FIVE;ok=(idx>=0)&(idx<self.n)&((ends-self.start)%FIVE==0);safe=np.clip(idx,0,self.n-1)
  val=np.array(self.values[ri,safe],copy=True);val[~ok]=np.nan;avail=np.broadcast_to((ends+FIVE)[...,None],val.shape).copy();lc=np.array(self.price_clock[ri,safe]);avail[...,0]=np.where((lc!=NAT)&ok,np.maximum(ends+FIVE,lc),NAT);avail[~ok]=NAT
  return val,avail
 def latest_anchor(self,region,issues):
  ri=self.regions.index(region);issues=np.asarray(issues,dtype='int64');idx=np.minimum((issues-FIVE-self.start)//FIVE,self.n-1);ok=idx>=0;safe=np.clip(idx,0,self.n-1)
  ends=self.start+safe*FIVE;aa=np.where(self.price_clock[ri,safe]!=NAT,np.maximum(ends+FIVE,self.price_clock[ri,safe]),NAT)
  bad=ok&((aa==NAT)|(aa>issues)|~np.isfinite(self.values[ri,safe,0]))
  while bad.any():
   idx[bad]-=1;ok=idx>=0;safe=np.clip(idx,0,self.n-1);ends=self.start+safe*FIVE;aa=np.where(self.price_clock[ri,safe]!=NAT,np.maximum(ends+FIVE,self.price_clock[ri,safe]),NAT);bad=ok&((aa==NAT)|(aa>issues)|~np.isfinite(self.values[ri,safe,0]))
  if not ok.all():raise ValueError('No finite issue-legal whole-sequence anchor')
  return np.asarray(self.values[ri,safe,0]),safe

def _visit(z,chain=()):
 for item in z.infolist():
  if item.filename.lower().endswith('.csv'):
   with z.open(item) as f:yield chain+(item.filename,),f
  elif item.filename.lower().endswith('.zip'):
   with tempfile.TemporaryFile() as nested:
    with z.open(item) as src:shutil.copyfileobj(src,nested,length=1024*1024)
    nested.seek(0)
    with zipfile.ZipFile(nested) as inner:yield from _visit(inner,chain+(item.filename,))

def stream_archive(rec,members,tables=None,permit=None):
 """At most 10,000 projected rows; all source/member bytes bound before decode."""
 conf_module('guard').require_execution(permit)
 if sha256(rec['path'])!=rec['sha256']:raise PermissionError('Archive hash changed')
 if archive_members(rec['path'])!=members:raise PermissionError('Archive central directory identity changed')
 tables=tables or {rec.get('table','PRICE')};opened(rec['path'],'guarded_source_values','post-global-freeze PRICE/REGIONSUM/P5MIN projected chunks <=10000')
 with zipfile.ZipFile(rec['path']) as z:
  for chain,f in _visit(z):
   headers={};chunks={}
   for row in csv.reader(io.TextIOWrapper(f,encoding='utf-8-sig')):
    if len(row)<4 or row[2] not in tables:continue
    table=row[2]
    if table in {'PRICE','REGIONSUM'} and row[1]!='DISPATCH':continue
    if table=='REGIONSOLUTION' and row[1]!='P5MIN':continue
    required=(['SETTLEMENTDATE','REGIONID','INTERVENTION']+(['RUNNO','RRP','LASTCHANGED'] if table=='PRICE' else list(FIELDS[1:]))) if table in {'PRICE','REGIONSUM'} else ['RUN_DATETIME','INTERVAL_DATETIME','REGIONID','INTERVENTION','LASTCHANGED','RRP','TOTALDEMAND','AVAILABLEGENERATION','NETINTERCHANGE']
    if row[0]=='I':
     header={c:i for i,c in enumerate(row)}
     if not set(required)<=set(header):raise ValueError('Required frozen source columns absent '+rec['path'])
     headers[table]=header;chunks[table]=[];continue
    if row[0]!='D':continue
    if table not in headers:raise ValueError('Numerical record preceding schema')
    header=headers[table]
    if row[header['INTERVENTION']] not in ('0','0.0','0.00000'):continue
    if table=='PRICE' and row[header['RUNNO']] not in ('1','1.0','1.00000'):continue
    if row[header['REGIONID']] not in REGIONS:continue
    chunks[table].append([row[header[c]] for c in required])
    if len(chunks[table])==10000:yield table,pd.DataFrame(chunks[table],columns=required);chunks[table].clear()
   for table,chunk in chunks.items():
    if chunk:yield table,pd.DataFrame(chunk,columns=(['SETTLEMENTDATE','REGIONID','INTERVENTION']+(['RUNNO','RRP','LASTCHANGED'] if table=='PRICE' else list(FIELDS[1:]))) if table in {'PRICE','REGIONSUM'} else ['RUN_DATETIME','INTERVAL_DATETIME','REGIONID','INTERVENTION','LASTCHANGED','RRP','TOTALDEMAND','AVAILABLEGENERATION','NETINTERCHANGE'])

def aggregate(raw,region,ends,issue=None):
 v,a=raw.take(region,ends);v=v[...,0];a=a[...,0];valid=np.isfinite(v)&(a!=NAT)
 if issue is not None:valid &= a<=issue
 complete=valid.all(axis=-1);means=np.where(complete,np.where(valid,v,0).sum(axis=-1)/12,np.nan);clock=np.where(complete,a.max(axis=-1),NAT)
 return means,clock,complete

def build_news_day(raw,origin):
 origin=pd.Timestamp(origin).tz_convert('UTC');t=origin.value;parts=[];day=origin.tz_convert(TZ).strftime('%Y-%m-%d')
 for region in NEWS_REGIONS:
  ends=t+np.arange(24)[:,None]*HOUR+np.arange(1,13)*FIVE;y,clock,_=aggregate(raw,region,ends)
  hist=t-np.arange(1,73)[:,None]*HOUR+np.arange(12)*FIVE;v,a=raw.take(region,hist);legal=np.isfinite(v)&(a!=NAT)&(a<=t);mask=legal.all(axis=1);means=np.where(mask,np.where(legal,v,0).sum(axis=1)/12,np.nan)
  naive,nclock,nlegal=aggregate(raw,region,ends-7*DAY,t)
  d={'origin':np.repeat(origin,24),'issue_time':np.repeat(origin,24),'target_time':pd.to_datetime(t+np.arange(24)*HOUR,utc=True),'target_day':[day]*24,'region':[region]*24,'horizon':np.arange(24,dtype='int16'),'region_code':np.repeat(NEWS_REGIONS.index(region),24),'y':y,'label_available':pd.to_datetime(clock,utc=True),'weekly_naive':naive,'weekly_naive_available':pd.to_datetime(nclock,utc=True),'weekly_naive_legal':nlegal,'weight':np.ones(24,'float32'),'split':['train' if day<='2024-12-31' else 'validation' if day<='2025-12-31' else 'history' if day<'2026-03-01' else 'confirmation']*24,'history_eligible':np.repeat(hist.min()>=raw.start,24)}
  for label,x,den in [('hour',np.arange(24),24),('weekday',np.repeat(origin.tz_convert(TZ).weekday(),24),7),('month',np.repeat(origin.tz_convert(TZ).month-1,24),12)]:
   for trig,fn in [('sin',np.sin),('cos',np.cos)]:d['target_'+label+'_'+trig]=fn(2*np.pi*x/den)
  for j,name in enumerate(NAMES):
   for k in range(72):d[f'{name}_lag_{k+1:02d}']=np.repeat(means[k,j],24);d[f'{name}_lag_{k+1:02d}_observed']=np.repeat(mask[k,j],24).astype('float32')
  parts.append(pd.DataFrame(d))
 out=pd.concat(parts,ignore_index=True).copy();out['day_complete']=bool(np.isfinite(out.y).all() and out.label_available.notna().all());out['pooled_day_label_available']=pd.to_datetime(np.repeat(out.label_available.max().value if out.day_complete.all() else NAT,len(out)),utc=True)
 return out

def notice_keys(first,last):
 targets=pd.date_range(first,last,inclusive='left',freq='5min',tz=TZ).tz_convert('UTC');parts=[]
 for region in REGIONS:
  for h in (5,10,15,20,25,30):parts.append(pd.DataFrame({'region':region,'origin':targets-pd.Timedelta(minutes=h),'target_time':targets,'horizon':np.int16(h)}))
 return pd.concat(parts,ignore_index=True).sort_values(['target_time','region','horizon'],kind='stable').reset_index(drop=True)

def build_notice_numeric(raw,keys,numeric_names):
 out=keys.copy();out['issue_time']=out.origin;out['target_day']=out.target_time.dt.tz_convert(TZ).dt.strftime('%Y-%m-%d');t=ns(out.origin);target=ns(out.target_time);n=len(out)
 names=['legal_anchor','price_lag_5m','price_lag_10m','price_lag_30m','price_lag_60m'];fields={x:np.full(n,np.nan) for x in names};y=np.full(n,np.nan);ya=np.full(n,NAT,'int64');seq=np.zeros((n,24),'float32');mask=np.zeros(n,'float32');graph=np.zeros((n,3),'float32');physical=np.full((n,8),np.nan)
 for region,ix in out.groupby('region').indices.items():
  tt=t[ix];ri=raw.regions.index(region);anchor,last=raw.latest_anchor(region,tt)
  for name,off in zip(names,(5,10,15,35,65)):
   v,a=raw.take(region,tt-off//5*FIVE);values=v[:,0];values[(a[:,0]==NAT)|(a[:,0]>tt)]=np.nan
   fields[name][ix]=anchor if name=='legal_anchor' else values
  v,a=raw.take(region,target[ix]);y[ix]=v[:,0];ya[ix]=a[:,0]
  inds=last[:,None]-np.arange(23,-1,-1);valid=inds[:,0]>=0;safe=np.clip(inds,0,raw.n-1);ends=raw.start+safe*FIVE;sv,sa=raw.take(region,ends);valid &= ((sa[...,0]!=NAT)&(sa[...,0]<=tt[:,None])&np.isfinite(sv[...,0])).all(axis=1)
  values=sv[...,0].astype('float32');values[~valid]=anchor[~valid,None].astype('float32');seq[ix]=values;mask[ix]=valid
  ga=[];gr=[]
  for neighbor in NEIGH[region]:
   av,_=raw.latest_anchor(neighbor,tt);bv,ba=raw.take(neighbor,tt-2*FIVE);bv=bv[:,0];bv[(ba[:,0]==NAT)|(ba[:,0]>tt)]=np.nan;ga.append(av);gr.append(av-bv)
  A,R=np.vstack(ga),np.vstack(gr);ac=np.isfinite(A).sum(axis=0);rc=np.isfinite(R).sum(axis=0);graph[ix,0]=np.where(ac,np.nansum(A,axis=0)/np.maximum(ac,1),0);graph[ix,1]=np.where(rc,np.nansum(R,axis=0)/np.maximum(rc,1),0);graph[ix,2]=np.isfinite(A).all(axis=0)&np.isfinite(R).all(axis=0)
  pv,pa_=raw.take(region,tt-FIVE);old,oa=raw.take(region,tt-7*FIVE);p=pv[:,1:];p[(pa_[:,1:]==NAT)|(pa_[:,1:]>tt[:,None])]=np.nan;before=old[:,1:];before[(oa[:,1:]==NAT)|(oa[:,1:]>tt[:,None])]=np.nan
  margin=p[:,1]-p[:,0];physical[ix]=np.column_stack([p,margin,p[:,0]-before[:,0],margin-(before[:,1]-before[:,0])])
 out['y']=y;out['label_available']=pd.to_datetime(ya,utc=True);out['anchor']=fields['legal_anchor'];out['weight']=np.float32(1);out['split']='confirmation'
 for name,values in fields.items():out[name]=values
 for lag in (5,10,30,60):out[f'ramp_{lag}m']=out.legal_anchor-out[f'price_lag_{lag}m']
 out['recent_volatility']=pd.DataFrame(fields).std(axis=1).to_numpy()
 for cut in (300,1000,5000):out[f'observed_pos{cut}']=(out.legal_anchor>cut).astype('float32')
 for j in range(24):out[f'price_seq_{j:02d}']=seq[:,j]
 out['price_sequence_mask']=mask;out['price_seq_ramp_last']=seq[:,-1]-seq[:,-2];out['price_seq_volatility']=np.std(np.diff(seq,axis=1),axis=1).astype('float32')
 local=out.origin.dt.tz_convert(TZ)
 for label,x,den in [('hour',local.dt.hour+local.dt.minute/60,24),('weekday',local.dt.dayofweek,7),('month',local.dt.month-1,12)]:
  for trig,fn in [('sin',np.sin),('cos',np.cos)]:out['calendar_'+label+'_'+trig]=fn(2*np.pi*x/den).astype('float32')
 out['region_code']=out.region.map({r:i for i,r in enumerate(REGIONS)});out['horizon_code']=out.horizon.map({h:i for i,h in enumerate((5,10,15,20,25,30))});out['horizon_group']=pd.cut(out.horizon,[0,10,20,30],labels=[0,1,2]).astype('int8')
 for j,col in enumerate(('graph_neighbor_anchor_mean','graph_neighbor_ramp_mean','graph_source_mask')):out[col]=graph[:,j]
 for j,col in enumerate(['phys_'+f.lower() for f in FIELDS[1:]]+['phys_margin','phys_demand_change_30m','phys_margin_change_30m']):out[col]=physical[:,j]
 missing=set(numeric_names)-set(out)
 if missing:raise ValueError('Frozen RF2 numeric columns unimplemented '+str(sorted(missing)))
 if not np.isfinite(out.y).all() or out.label_available.isna().any() or not np.isfinite(out.anchor).all():raise ValueError('Complete notice target/clock/anchor gate failed')
 for col in numeric_names:
  if col!='horizon':out[col]=out[col].astype('float32')
 return out

def validate_news(frame,primary=True):
 if frame.duplicated(['origin','region','horizon']).any():raise ValueError('Duplicate news forecast key')
 if len(frame)!=72 or set(frame.region)!=set(NEWS_REGIONS) or set(frame.horizon)!=set(range(24)):raise ValueError('Incomplete news day keys')
 if primary and (not np.isfinite(frame.y).all() or frame.label_available.isna().any()):raise ValueError('Complete news target/clock gate failed')
 for name in NAMES:
  for k in range(1,73):
   c=f'{name}_lag_{k:02d}';m=frame[c+'_observed'].to_numpy()
   if not np.isin(m,[0,1]).all() or not np.array_equal(np.isfinite(frame[c]),m==1):raise ValueError('History value/mask mismatch')
 return {'keys':len(frame),'day_complete':bool(np.isfinite(frame.y).all() and frame.label_available.notna().all()),'legal_weekly_naive_keys':int(frame.weekly_naive_legal.sum()),'history_eligible':bool(frame.history_eligible.all())}

def _append(writer,path,frame):
 table=pa.Table.from_pandas(frame,preserve_index=False)
 if writer is None:writer=pq.ParquetWriter(path,table.schema,compression='zstd')
 writer.write_table(table.cast(writer.schema),row_group_size=min(len(frame),10000));return writer

class P5Store:
 def __init__(self,start,end,out):
  self.start=pd.Timestamp(start).value;self.n=(pd.Timestamp(end).value-self.start)//FIVE+1;shape=(self.n,5,12);out=Path(out);out.mkdir(parents=True,exist_ok=True)
  self.v=np.lib.format.open_memmap(out/'p5_values.npy',mode='w+',dtype='float32',shape=shape+(4,));self.v[:]=np.nan
  self.a=np.lib.format.open_memmap(out/'p5_availability.npy',mode='w+',dtype='int64',shape=shape);self.a[:]=NAT
  self.seen=np.lib.format.open_memmap(out/'p5_seen.npy',mode='w+',dtype='bool',shape=shape);self.seen[:]=False
 def consume(self,d):
  d=d.copy();d['run']=clocks(d.RUN_DATETIME);d['target']=clocks(d.INTERVAL_DATETIME);d['lc']=clocks(d.LASTCHANGED)
  if ((d.run-self.start)%FIVE!=0).any() or ((d.target-d.run)%FIVE!=0).any():raise ValueError('Off-grid P5MIN key')
  d=d.loc[(d.run>=self.start)&(d.run<self.start+self.n*FIVE)]
  numeric=['RRP','TOTALDEMAND','AVAILABLEGENERATION','NETINTERCHANGE']
  for col in numeric:d[col]=pd.to_numeric(d[col],errors='coerce')
  d=d[['run','target','REGIONID','lc']+numeric].drop_duplicates()
  if d.duplicated(['run','target','REGIONID']).any():raise ValueError('Conflicting P5MIN source keys')
  for row in d.itertuples(index=False):
   i=(row.run-self.start)//FIVE;r=REGIONS.index(row.REGIONID);h=(row.target-row.run)//FIVE
   if not 0<=h<12:raise ValueError('Invalid P5MIN registered horizon')
   v=np.array([pd.to_numeric(x,errors='coerce') for x in (row.RRP,row.TOTALDEMAND,row.AVAILABLEGENERATION,row.NETINTERCHANGE)],dtype='float32');a=NAT if row.lc==NAT else max(row.run+FIVE,row.lc)
   if self.seen[i,r,h] and (not same(self.v[i,r,h],v) or self.a[i,r,h]!=a):raise ValueError('Conflicting P5MIN values or clocks')
   self.v[i,r,h]=v;self.a[i,r,h]=a;self.seen[i,r,h]=True
 def block(self,keys):
  issue=ns(keys.origin);target=ns(keys.target_time);r=keys.region.map({r:i for i,r in enumerate(REGIONS)}).to_numpy();values=[]
  def value(run,region):
   i=(run-self.start)//FIVE;h=(target-run)//FIVE;ok=(i>=0)&(i<self.n)&(h>=0)&(h<12);safe=np.clip(i,0,self.n-1);hh=np.clip(h,0,11);ok &= self.seen[safe,region,hh]&(self.a[safe,region,hh]!=NAT)&(self.a[safe,region,hh]<=issue)&(run+FIVE<=issue)
   v=np.array(self.v[safe,region,hh]);v[~ok]=np.nan;return v,safe,ok
  a,i,ok=value(issue-FIVE,r);b,_,_=value(issue-2*FIVE,r);rrp=a[:,0];runrows=np.array(self.v[i,r,:,0]);valid=self.seen[i,r,:]&(self.a[i,r,:]!=NAT)&(self.a[i,r,:]<=issue[:,None]);runrows[~valid]=np.nan;runrows[~ok]=np.nan
  finite=np.isfinite(runrows);runmax=np.where(finite.any(axis=1),np.max(np.where(finite,runrows,-np.inf),axis=1),np.nan);nbr=np.full(len(keys),np.nan,'float32')
  for name,neighbors in NEIGH.items():
   sel=keys.region.eq(name).to_numpy();rows=np.stack([value(issue-FIVE,np.full(len(keys),REGIONS.index(other)))[0][:,0] for other in neighbors]);count=np.isfinite(rows).sum(axis=0).astype('float32');total=np.where(np.isfinite(rows),rows,0).sum(axis=0,dtype='float32');nbr[sel]=np.where(count[sel]>0,total[sel]/np.maximum(count[sel],1),np.nan)
  out=pd.DataFrame(dict(zip(P5_COLUMNS,[rrp,rrp.astype('float64')-keys.anchor.to_numpy('float64'),rrp-b[:,0],runmax,a[:,1],a[:,2]-a[:,1],a[:,3],nbr])))
  return out.astype('float32')

def build_panels(permit,out,catalog=None):
 conf_module('guard').require_execution(permit);out=Path(out);out.mkdir(parents=True,exist_ok=True)
 catalog=catalog or read_json(ROOT/'prepared_sources/source_catalog.json')
 # The permit binds every file; each archive and central directory is rechecked at its read.
 manifest_path=out/'manifest.json'
 if manifest_path.exists():
  m=read_json(manifest_path)
  for entry in m['files']:
   if sha256(entry['path'])!=entry['sha256']:raise ValueError('Panel resume identity mismatch')
  return m
 raw=RawStore(aest('2021-10-01'),aest('2026-10-01'),out/'raw_mmap')
 for rec in catalog['numeric_sources']:
  for table,d in stream_archive(rec,catalog['archive_members'][rec['path']],permit=permit):raw.consume(d,table)
  check_rss();gc.collect()
 writer=None;hourwriter=None;days=[]
 for origin in pd.date_range('2021-10-01','2026-09-30',freq='D',tz=TZ).tz_convert('UTC'):
  frame=build_news_day(raw,origin);primary=origin>=aest('2026-03-01');gate=validate_news(frame,primary);gate['day']=origin.tz_convert(TZ).strftime('%Y-%m-%d');days.append(gate)
  for col in NEWS_NUMERIC:
   if col!='horizon':frame[col]=frame[col].astype('float32')
  writer=_append(writer,out/'news.parquet',frame)
  hourly=frame[['region','target_time','target_day','horizon','y','label_available']];hourwriter=_append(hourwriter,out/'hourly.parquet',hourly)
 writer.close();hourwriter.close()
 # Keep all five regions' prices; diagnostics may read them only after seal.
 writer=None
 for region in REGIONS:
  ri=REGIONS.index(region)
  for start in range(0,raw.n,10000):
   ends=raw.start+np.arange(start,min(start+10000,raw.n))*FIVE;v,a=raw.take(region,ends);d=pd.DataFrame({'region':region,'interval_end':pd.to_datetime(ends,utc=True),'event_time':pd.to_datetime(ends,utc=True),'price':v[:,0],'rrp':v[:,0],'available_time':pd.to_datetime(a[:,0],utc=True)});writer=_append(writer,out/'canonical_price.parquet',d)
 writer.close()
 des=read_json(PROJ/'autopilot/q1_audits/RF2/final/design.json');numeric=des['numeric_names'];writer=None;ewriter=None;rows=0;e3_rows=0;e3_finite=np.zeros(8,dtype='int64');e3_error=None
 p5=P5Store(aest('2026-07-27'),aest('2026-10-01'),out/'p5_mmap')
 try:
  for rec in catalog['p5min_sources']:
   # Runs before July cannot contribute; month source selection is metadata only.
   if rec['month'] not in {'2026-07','2026-08','2026-09'}:continue
   for _,d in stream_archive(rec,catalog['archive_members'][rec['path']],{'REGIONSOLUTION'},permit=permit):p5.consume(d)
   check_rss();gc.collect()
 except ValueError as exc:
  # E3's source/value gate cannot remove or alter any primary forecast key.
  e3_error=repr(exc)
 for first in pd.date_range('2026-08-01','2026-09-30',freq='D'):
  keys=notice_keys(first.strftime('%Y-%m-%d'),(first+pd.Timedelta(days=1)).strftime('%Y-%m-%d'));frame=build_notice_numeric(raw,keys,numeric);rows+=len(frame);writer=_append(writer,out/'notices.parquet',frame);e3=p5.block(frame);e3_rows+=len(e3);e3_finite+=np.isfinite(e3.to_numpy()).sum(axis=0);ewriter=_append(ewriter,out/'notice_p5.parquet',e3)
 writer.close();ewriter.close()
 if rows!=NOTICE_EXPECTED_ROWS or sum(x['keys'] for x in days if x['day']>='2026-03-01')!=NEWS_EXPECTED_ROWS:raise ValueError('Frozen complete panel count gate')
 # RF2 C train IDs are the ENTIRE original development population, never filtered.
 meta=PROJ/'autopilot/q1_audits/B1b/development_metadata.parquet';opened(meta,'guarded_source_values','post-freeze RF2 fixed training keys/labels/weights/anchor');matrix=np.load(PROJ/'autopilot/q1_audits/B4/corrected_numeric.npy',mmap_mode='r');p5train=np.load(PROJ/'autopilot/q1_audits/B5/e3/p5_development.npy',mmap_mode='r');pf=pq.ParquetFile(meta);writer=None;ewriter=None;offset=0;train_rows=0;first_issue=aest('2026-07-31 23:30')
 for batch in pf.iter_batches(batch_size=10000,columns=['region','issue_time','target_time','horizon','y_true','label_available_time','legal_anchor','weight','bank_month','event_replay_flag']):
  d=batch.to_pandas();n=len(d)
  if not ((d.target_time<first_issue)&(d.label_available_time<first_issue)).all():raise ValueError('B6 strict fixed-training label gate')
  if not np.array_equal(d.weight.to_numpy(),np.where(d.event_replay_flag>.5,1.,50.)):raise ValueError('Fixed RF2 training weights gate')
  if not d.bank_month.between('2021-10','2023-12').all():raise ValueError('Forbidden appended notice training period')
  d=d.rename(columns={'issue_time':'origin','y_true':'y','label_available_time':'label_available','legal_anchor':'anchor'});d['target_day']=d.target_time.dt.tz_convert(TZ).dt.strftime('%Y-%m-%d');d['split']='train'
  for j,col in enumerate(numeric):d[col]=np.asarray(matrix[offset:offset+n,j])
  writer=_append(writer,out/'notices_train.parquet',d);e=pd.DataFrame(np.asarray(p5train[offset:offset+n]),columns=P5_COLUMNS);ewriter=_append(ewriter,out/'notice_p5_train.parquet',e);offset+=n;train_rows+=n
 writer.close();ewriter.close()
 if offset!=len(matrix) or offset!=len(p5train):raise ValueError('RF2/E3 original training membership mismatch')
 del matrix,p5train;gc.collect()
 entries={name:file_identity(out/name) for name in ['news.parquet','hourly.parquet','notices.parquet','notices_train.parquet','notice_p5.parquet','notice_p5_train.parquet','canonical_price.parquet']}
 m={'state':'PANELS_COMPLETE_VALIDATED','news':{**entries['news.parquet'],'numeric_columns':NEWS_NUMERIC,'confirmation_rows':NEWS_EXPECTED_ROWS,'days':days},'notices':{**entries['notices.parquet'],'train_path':str((out/'notices_train.parquet').resolve()),'numeric_columns':numeric,'confirmation_rows':rows,'train_rows':train_rows},'ordinary_hourly':entries['hourly.parquet'],'hourly':entries['hourly.parquet'],'raw_price_path':entries['canonical_price.parquet']['path'],'canonical_price':entries['canonical_price.parquet'],'notice_p5':entries['notice_p5.parquet'],'notice_p5_train':entries['notice_p5_train.parquet'],'p5_columns':P5_COLUMNS,'e3_state':'READY' if e3_error is None and (e3_finite==rows).all() else 'UNAVAILABLE_INPUT_GATE','e3_error':e3_error,'e3_finite_counts':dict(zip(P5_COLUMNS,map(int,e3_finite))),'numeric_columns':{'news':NEWS_NUMERIC,'notices':numeric},'source_catalog_sha256':sha256(catalog.get('path',ROOT/'prepared_sources/source_catalog.json')),'files':list(entries.values()),'source_conflicting_keys':0,'exact_duplicate_records':raw.duplicates,'peak_rss_bytes':check_rss(),'window_weights':1,'no_fits':True}
 atomic_json(manifest_path,m,immutable=True);return m
