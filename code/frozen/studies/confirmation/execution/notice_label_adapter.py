"""NRX source-only labels -> immutable FINAL3 records and typed Laz sidecars.

No import-time study reads. Host label loading requires the global permit. Pilot
label journals may be tested under the explicitly authorized label-only scope.
"""
from __future__ import annotations
from pathlib import Path
from types import SimpleNamespace
import hashlib, importlib.util, json, math, re, sys
import numpy as np
import pandas as pd
from runtime import CONF, PROJ, conf_module, sha256, read_json, atomic_json, file_identity

f = conf_module('features')
require_execution = conf_module('guard').require_execution
FINAL3_PATH = PROJ/'autopilot/q1_audits/FINAL/final3/assembler/nw_notices_final3.py'
CORRECTED_RULE_PATH = PROJ/'autopilot/q1_audits/EXTAUDIT/parser_review/corrected_rule.py'
SCALAR = re.compile(r'^[+-]?(?:\d+(?:\.\d*)?|\.\d+)(?:[eE][+-]?\d+)?$')
# CONFX4: NRX 1.3 keeps the source literal in value_text (e.g. "447 MW") and the
# unit in its own enum. One trailing token equal to that declared unit (any case)
# may follow a standard comma-grouped number; nothing is converted.
UNIT_TOKENS = ('MW', 'MWh', 'minutes')
NUMBER_UNIT = r'([+-]?(?:(?:\d{1,3}(?:,\d{3})+|\d+)(?:\.\d*)?|\.\d+)(?:[eE][+-]?\d+)?)\s*'


def load_final3(*, permit, expected=None):
    require_execution(permit)
    if expected is not None and sha256(FINAL3_PATH) != expected:
        raise ValueError('FINAL3 dependency identity drift')
    spec=importlib.util.spec_from_file_location('_confx2_final3',FINAL3_PATH)
    module=importlib.util.module_from_spec(spec); spec.loader.exec_module(module)
    if tuple(module.COLUMNS)!=f.L14_COLUMNS: raise ValueError('FINAL3 column identity drift')
    return module


def load_corrected_rule(*, permit):
    require_execution(permit)
    if sha256(CORRECTED_RULE_PATH)!='d40c55c993469841afcce20091d741ae7d5722e21caa29c3197e5885f98a23f0':
        raise ValueError('Corrected R wrapper identity drift')
    spec=importlib.util.spec_from_file_location('_confx2_corrected_rule',CORRECTED_RULE_PATH)
    module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module)
    return module


def scalar(text, *, nonnegative=False, unit=None):
    """Finite literal scalar, optionally followed by the declared unit token;
    ranges/qualifiers/other units/arithmetic stay unknown."""
    clean=str(text).strip()
    if unit in UNIT_TOKENS:
        literal=re.fullmatch(NUMBER_UNIT+re.escape(unit),clean,re.IGNORECASE)
        if literal:clean=literal.group(1)
    clean=clean.replace(',','')
    if not SCALAR.fullmatch(clean): return math.nan
    val=float(clean)
    return val if math.isfinite(val) and (not nonnegative or val>=0) else math.nan


def _label_evidence(label):
    spans=[]
    def walk(value):
        if isinstance(value,dict):
            spans.extend(s for s in value.get('evidence_spans',[]) if isinstance(s,str))
            for k,v in value.items():
                if k!='evidence_spans':walk(v)
        elif isinstance(value,list):
            for v in value:walk(v)
    walk(label)
    return ' '.join(dict.fromkeys(spans))


def _bound_quantities(label, window):
    groups={'REQUIREMENT':set(),'AVAILABLE':set()}; losses=[]; rejected=[]
    wid=str(window['window_id']); asset=f.value(window['asset_id'])
    for index,q in enumerate(label.get('quantities',[])):
        if q.get('window_id')!=wid: continue
        qasset=f.value(q.get('asset_id'))
        # A typed explicit window binding is sufficient for reserve scalars;
        # outage capacity additionally needs an explicit matching asset identity.
        bound=(q.get('binding_status')=='BOUND' and
               q.get('binding_reason')=='BOUND_EXPLICIT_SOURCE_SCOPE')
        val=scalar(q.get('value_text',''),unit=q.get('unit'))
        if bound and q.get('unit')=='MW' and math.isfinite(val) and q.get('role') in groups:
            if qasset=='UNKNOWN' or asset=='UNKNOWN' or qasset==asset:groups[q['role']].add(val)
        if q.get('role')=='LOSS':
            loss=scalar(q.get('value_text',''),nonnegative=True,unit=q.get('unit'))
            accepted=(bound and q.get('unit')=='MW' and math.isfinite(loss) and
                      asset!='UNKNOWN' and qasset==asset)
            if accepted: losses.append((f"{label['notice_id']}:q{index}",loss))
            else:rejected.append(index)
    one=lambda k:next(iter(groups[k])) if len(groups[k])==1 else math.nan
    req,avail=one('REQUIREMENT'),one('AVAILABLE')
    return req,avail,('BOUND' if math.isfinite(req) and math.isfinite(avail) else 'UNKNOWN_RELATION'),losses,rejected


def normalize_notice(notice, final3, *, permit):
    require_execution(permit)
    frozen=final3.frozen
    nid=str(notice['notice_id']); label=notice.get('nrx_label')
    success=notice.get('extraction_status')=='SUCCESS'
    if success and (not isinstance(label,dict) or str(label.get('notice_id'))!=nid):
        raise ValueError('NRX label/source ID mismatch')
    available=pd.Timestamp(f.utc(notice['available_utc']))
    anchor=notice.get('anchor_local')
    if anchor is None:
        # This is the source-issued AEST day, not a physical event clock.
        anchor=available.tz_convert('Australia/Brisbane').tz_localize(None)
    anchor=pd.Timestamp(anchor)
    if anchor.tzinfo is not None:anchor=anchor.tz_convert('Australia/Brisbane').tz_localize(None)
    source=SimpleNamespace(notice_id=nid,title=str(notice.get('title','')),
        text=str(notice.get('body',notice.get('text',''))),
        notice_type=str(notice.get('notice_type',notice.get('source_notice_type',''))),
        anchor_local=anchor,available_utc=available,
        quantities_json=json.dumps(label.get('quantities',[]) if success else []))
    relation=final3.shared_relation(source.text,source.title)
    windows=label.get('impact_windows',[]) if success else []
    ids=[str(w['window_id']) for w in windows]
    if len(ids)!=len(set(ids)):raise ValueError('Duplicate NRX window ID')
    if success:
        allowed=set(ids)
        for q in label.get('quantities',[]):
            if q.get('binding_status')=='BOUND' and q.get('window_id') not in allowed:
                raise ValueError('Dangling NRX quantity-window binding')
    lifecycle=f.value(label.get('lifecycle')) if success else 'UNKNOWN'
    # Keep the immutable official title exceptions from FINAL3, but never infer
    # semantic region/kind/event bounds from the source body.
    status=frozen.v2._status(source.title,lifecycle)
    if lifecycle=='CEASED':status='RECOVERY'
    evidence=_label_evidence(label) if success else ''
    category='ADMINISTRATIVE_SYSTEM' if source.notice_type=='MARKET SYSTEMS' else source.notice_type
    rows=[]; sides=[]
    iterable=windows or [None]
    for wi,window in enumerate(iterable):
        if window is None:
            reg,kind,start_text,end_text='UNKNOWN','OTHER',None,None
            req,avail,qstatus,losses,rejected=math.nan,math.nan,'UNKNOWN_RELATION',[],[]
            asset,cls,fuel,interval='UNKNOWN','UNKNOWN','UNKNOWN','UNKNOWN'
            wid='__MISSING_LABEL__' if not success else '__NO_WINDOWS__'
        else:
            reg=f.value(window['region']); family=f.value(window['event_family'])
            kind=('CONSTRAINT' if source.notice_type=='RECLASSIFY CONTINGENCY' else
                  'OUTAGE' if family=='RETURN_TO_SERVICE' else
                  family if family in ('RESERVE','CONSTRAINT','INTERVENTION','OUTAGE') else 'OTHER')
            if family=='RETURN_TO_SERVICE' and status!='CANCELLATION':status='RECOVERY'
            start_text=f.value(window['start_text']); end_text=f.value(window['end_text'])
            start_text=None if start_text=='UNKNOWN' else start_text
            end_text=None if end_text=='UNKNOWN' else end_text
            req,avail,qstatus,losses,rejected=_bound_quantities(label,window)
            asset=f.value(window['asset_id']);cls=f.value(window['event_class'])
            fuel=f.value(window['fuel_type']); interval=f.value(window['interval_status']);wid=str(window['window_id'])
        action,prospective,reason,action_evidence,precision=pd.NaT,False,'UNKNOWN_ACTION_TIME','',''
        start,end,sp,ep,_=frozen.window_details(start_text,end_text,anchor,available)
        if status in ('CANCELLATION','RECOVERY'):
            # Endpoint evidence is label supported. An independently explicit
            # action may be found only inside accepted label evidence spans.
            action=end if pd.notna(end) else start
            precision=ep if pd.notna(end) else sp
            if pd.notna(action):reason='NRX_CLOSING_ENDPOINT'
            e_action,e_prospective,e_reason,e_span,e_precision=frozen.action_metadata('',evidence,anchor,available)
            if pd.notna(e_action):
                if pd.notna(action) and action!=e_action:
                    action=pd.NaT;reason='CONFLICTING_NRX_ACTION_TIMES'
                else:action,prospective,reason,action_evidence,precision=e_action,e_prospective,e_reason,e_span,e_precision
        record=frozen._record(source,'L',reg,kind,status,start_text,end_text,req,avail,qstatus,
            relation['related_notice_ids'],relation['source_body_regions'],relation['source_lor_level'],
            category,category!='ADMINISTRATIVE_SYSTEM' and success,reg,'NRX_REGION_ONLY',
            evidence,'NRX_ENDPOINTS_ONLY',action=action,action_precision=precision,
            action_evidence=action_evidence,prospective=prospective,action_reason=reason,
            scope=final3.relation_scope(status,relation),constraint_ids=relation['constraint_ids'],
            negative=relation['negative_state'],raw=windows)
        record['title_key']=relation['title_key']
        record['nrx_window_id']=wid;record['nrx_asset_id']=asset
        # Explicit interval enum controls active admission. Missing end never
        # becomes open merely because _record recognizes a free-form phrase.
        if interval=='OPEN_UNTIL_NOTICE' and pd.notna(start) and pd.isna(end):
            record['temporal_status']='OPEN_UNTIL_NOTICE';record['end_is_open']=True
        elif interval=='BOUNDED' and pd.notna(start) and pd.notna(end) and end>start:
            record['temporal_status']='BOUNDED'
        elif record['cancel'] and pd.notna(action):
            record['temporal_status']='CLOSING_INSTANT_ONLY'
        else:
            record['temporal_status']='UNKNOWN_INTERVAL';record['end_is_open']=False
        if window is None:record['feature_eligible']=False
        rows.append(record)
        sides.append(dict(notice_id=nid,nrx_window_id=wid,asset_id=asset,event_class=cls,
            fuel_type=fuel,interval_status=record['temporal_status'],
            bound_loss_mw=losses,known_partial_loss_mw=sum(mw for _,mw in losses),rejected_loss_quantity_indices=rejected,
            schema_window_order=wi,extraction_status=notice.get('extraction_status'),
            record_fields_sha256=hashlib.sha256(json.dumps(list(record),separators=(',',':')).encode()).hexdigest()))
    return rows,sides


def normalize_notices(notices, final3, *, permit):
    require_execution(permit)
    rows=[];sides=[];seen=set()
    for n in notices:
        nid=str(n['notice_id'])
        if nid in seen:raise ValueError('Canonical notice population requires unique IDs')
        seen.add(nid);r,s=normalize_notice(n,final3,permit=permit);rows.extend(r);sides.extend(s)
    if rows:
        records=pd.DataFrame(rows)
    else:
        # An empty synthetic source population still has the frozen schema.
        records=pd.DataFrame(columns=final3.frozen.RECORD_COLUMNS+[
            'feature_eligible','action_effective_utc','prospective_action','constraint_ids',
            'negative_state','nrx_window_id','nrx_asset_id','cancel','temporal_status'])
    for name in ('available_utc','start_utc','end_utc','action_effective_utc'):
        records[name]=pd.to_datetime(records[name],utc=True)
    records=final3.normalize_closure_start(records)
    return records,sides


def laz_asof(resolved, sides, issue, target_time, region, *, permit):
    require_execution(permit)
    lookup={(s['notice_id'],s['nrx_window_id']):s for s in sides}
    now=pd.Timestamp(f.utc(issue));target=pd.Timestamp(f.utc(target_time));typed=[]
    for row in resolved.to_dict('records'):
        side=lookup[(str(row['notice_id']),str(row['nrx_window_id']))]
        closed=bool(row.get('cancel')) or (pd.notna(row.get('close_utc')) and row['close_utc']<=now)
        for announced,effective,_ in json.loads(row.get('prospective_closures_json','[]')):
            if now>=pd.Timestamp(announced):
                effective=pd.Timestamp(effective)
                if pd.isna(row['end_utc']) or effective<row['end_utc']:row['end_utc']=effective
                if row['start_utc']>=effective:closed=True
        basis=row.get('relation_basis','NEW_EVENT')
        reliable=(side['asset_id']!='UNKNOWN' and not side['rejected_loss_quantity_indices'] and basis in (
            'NEW_EVENT','EXPLICIT_NOTICE_ID','EXACT_CONSTRAINT_SET_ID','DATED_TITLE_OVERLAP','UNIQUE_DATED_TITLE'))
        typed.append({**side,**row,'available_utc':row['available_utc'],
            'start_utc':None if pd.isna(row['start_utc']) else row['start_utc'],
            'end_utc':None if pd.isna(row['end_utc']) else row['end_utc'],
            'interval_status':row['temporal_status'],'closed_asof_issue':closed,
            'resolved_event_identity':f"{row.get('event_id')}|{side['asset_id']}",
            'identity_reliable':reliable,'bound_loss_mw':side['bound_loss_mw'],
            'event_class':side['event_class'],'fuel_type':side['fuel_type']})
    out,diagnostics=f.laz_overlap_components(typed,issue,target-pd.Timedelta(minutes=5),target,region,permit=permit)
    known={};by_fuel={}
    for r in typed:
        if r['event_class']!='FAILURE' or r['region']!=region or r['closed_asof_issue'] or not r['feature_eligible']:
            continue
        if f.utc(r['available_utc'])>f.utc(issue) or r['start_utc'] is None:continue
        if r['interval_status']=='OPEN_UNTIL_NOTICE' and f.utc(issue)-f.utc(r['available_utc'])>=pd.Timedelta(hours=48):continue
        if r['interval_status'] not in ('OPEN_UNTIL_NOTICE','BOUNDED'):continue
        if not (pd.Timestamp(r['start_utc'])<target and (r['end_utc'] is None or pd.Timestamp(r['end_utc'])>target-pd.Timedelta(minutes=5))):continue
        for qid,mw in r['bound_loss_mw']:
            key=(r['resolved_event_identity'],str(qid))
            if key not in known:
                known[key]=float(mw);by_fuel[r['fuel_type']]=by_fuel.get(r['fuel_type'],0.)+float(mw)
    diagnostics.update(known_partial_outage_mw=sum(known.values()),known_mw_by_source_fuel=by_fuel,
        complete_outage_mw_available=math.isfinite(out[f.LAZ_COLUMNS[-1]]))
    return out,diagnostics


def load_host_notices(nrx_directory, *, permit, prefix_clock_rows=None):
    require_execution(permit)
    root=Path(nrx_directory)
    label_path=root/'labels.parquet'
    table=pd.read_parquet(label_path,columns=['notice_id','terminal_state','label_json'])
    if table.notice_id.astype(str).duplicated().any():raise ValueError('NRX final labels duplicate IDs')
    labels={str(r.notice_id):(r.terminal_state,json.loads(r.label_json) if pd.notna(r.label_json) else None)
            for r in table.itertuples(index=False)}
    scope_path=root.parent/'scope.jsonl' if root.name=='results_1_3' else root/'scope.jsonl'
    if not scope_path.exists():scope_path=PROJ/'autopilot/q1_audits/NRX/scope.jsonl'
    clock_map={str(r['notice_id']):r for r in prefix_clock_rows or []}
    out=[]
    with scope_path.open() as stream:
        for line in stream:
            n=json.loads(line);nid=str(n['notice_id'])
            if nid not in labels:raise ValueError('NRX missing terminal census label: '+nid)
            status,label=labels[nid];clock=n['clocks']
            available=clock.get('available_time_utc')
            if not available:raise ValueError('NRX source missing official availability clock')
            if clock_map:
                if nid not in clock_map:raise ValueError('NRX scope absent from canonical prefix: '+nid)
                expected=clock_map[nid].get('available_utc',clock_map[nid].get('available_time_utc'))
                if f.utc(expected)!=f.utc(available):raise ValueError('NRX/prefix clock conflict: '+nid)
            out.append({**n,'available_utc':available,'notice_type':n.get('source_notice_type',''),
                'anchor_local':clock.get('raw_time_local'),
                'extraction_status':'SUCCESS' if status=='SUCCESS' else 'TERMINAL_FAILURE','nrx_label':label})
    if {str(n['notice_id']) for n in out}!=set(labels):raise ValueError('NRX scope/labels census mismatch')
    return sorted(out,key=lambda n:(f.utc(n['available_utc']),str(n['notice_id'])))
