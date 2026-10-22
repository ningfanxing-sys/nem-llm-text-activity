"""A8.1 pre-score metadata manifest. Streaming CSV/JSONL, no text/value loader.

Config contains exact identities of two article_manifest.csv files, scope.jsonl,
and coverage_evidence identities plus explicit news/notice coverage intervals.
It must be prepared from frozen source inventory, never inferred from arrivals.
"""
from pathlib import Path
import argparse
import ast
import csv
import datetime
import hashlib
import json
import os
import resource
import time

ALLOWED_IMPORTS = {'pathlib','argparse','ast','csv','datetime','hashlib','json','os','resource','time'}
FORBIDDEN = {'host_state','scored','scores','predictions','evaluation'}

def need(ok,message):
    if not ok: raise RuntimeError(message)

def ast_guard(source=None):
    tree = ast.parse(source or Path(__file__).read_text())
    for n in ast.walk(tree):
        if isinstance(n,ast.Import): need(all(a.name.split('.')[0] in ALLOWED_IMPORTS for a in n.names),'R8 manifest forbidden import')
        if isinstance(n,ast.ImportFrom): need(n.level == 0 and n.module.split('.')[0] in ALLOWED_IMPORTS,'R8 manifest forbidden import')
        if isinstance(n,ast.Call):
            name = n.func.id if isinstance(n.func,ast.Name) else n.func.attr if isinstance(n.func,ast.Attribute) else ''
            need(name not in {'__import__','import_module','exec','eval','spec_from_file_location'},'R8 manifest dynamic execution')
    return True

def identity(path):
    p=Path(path).resolve()
    need('/semantic_validation/private/' not in str(p) and not (FORBIDDEN & set(p.parts)) and not any(x in p.name.lower() for x in ('price','prediction','score','seal','label','host_state')),'Forbidden metadata input')
    h=hashlib.sha256()
    with p.open('rb') as stream:
        for block in iter(lambda:stream.read(1024*1024),b''): h.update(block)
    return dict(path=str(p),bytes=p.stat().st_size,sha256=h.hexdigest())

def checked(item):
    need(identity(item['path']) == item,'R8 metadata input identity drift')
    return Path(item['path'])

def strict(text):
    def pairs(items):
        row={}
        for key,value in items:
            need(key not in row,'Duplicate metadata key');row[key]=value
        return row
    return json.loads(text,object_pairs_hook=pairs,parse_constant=lambda x:need(False,'Nonfinite metadata number'))

def stamp(raw):
    s=datetime.datetime.fromisoformat(raw.replace('Z','+00:00'))
    need(s.tzinfo is not None,'Metadata timezone required');return s

def publish(path,value):
    path=Path(path);path.parent.mkdir(parents=True,exist_ok=True)
    data=(json.dumps(value,sort_keys=True,indent=2,ensure_ascii=False,allow_nan=False)+'\n').encode()
    if path.exists():
        need(path.read_bytes()==data,'Preserve metadata receipt');return path
    tmp=path.with_name(path.name+'.atomic.'+str(os.getpid()))
    with tmp.open('wb') as stream:stream.write(data);stream.flush();os.fsync(stream.fileno())
    os.link(tmp,path)
    # Keep temporary evidence; cleanup belongs to the coordinator.
    return path

def build(config_path,destination,measure_only=False):
    started=time.monotonic();ast_guard()
    config_id=identity(config_path);config=strict(Path(config_path).read_text())
    need(set(config)==({'news_manifests','notice_scope'} if measure_only else {'news_manifests','notice_scope','coverage','coverage_evidence'}),'Metadata config schema')
    need(len(config['news_manifests'])==2,'Two article manifests required')
    if not measure_only:
        need(config['coverage_evidence'],'Frozen coverage evidence required')
        for item in config['coverage_evidence']:checked(item)
        for source in ('news','notice'):
            need(config['coverage'].get(source),'Nonempty explicit source coverage required')
            for a,b in config['coverage'][source]:need(stamp(a)<stamp(b),'Invalid coverage interval')
    news={};fields=('article_id','publication_utc','modified_utc','saved_version_available_utc','article_text_chars','article_text_sha256')
    for item in config['news_manifests']:
        path=checked(item);need(path.name=='article_manifest.csv','Only article metadata manifest allowed')
        with path.open(newline='') as stream:
            reader=csv.DictReader(stream);need(set(fields)<=set(reader.fieldnames),'Article metadata schema')
            for source in reader:
                row={k:source[k] for k in fields};aid=row['article_id']
                need(aid not in news or news[aid]==row,'Conflicting saved article version')
                need(stamp(row['saved_version_available_utc'])>=max(stamp(row['publication_utc']),stamp(row['modified_utc'])),'Article admission clock')
                need(int(row['article_text_chars'])>=0,'Negative character count');news[aid]=row
    scope=checked(config['notice_scope']);need(scope.name=='scope.jsonl','Only NRX source registry allowed')
    raw_types=set();ids=set();count=0
    with scope.open() as stream:
        for line in stream:
            row=strict(line);nid=str(row['notice_id']);need(nid not in ids,'Duplicate notice source ID');ids.add(nid)
            stamp(row['clocks']['available_time_utc']);day=str(row['source_day_aest'])[:10]
            raw=row.get('source_notice_type');count+=1
            if '2021-10-01'<=day<='2023-12-31' and raw is not None and str(raw)!='':raw_types.add(str(raw))
    mapping={raw:'T_'+hashlib.sha256(raw.encode()).hexdigest() for raw in sorted(raw_types)}
    need(len(set(mapping.values()))==len(mapping),'Notice token collision')
    if measure_only:
        value=dict(state='MEASURED_PRESCORE_METADATA_ONLY',config=config_id,builder=identity(__file__),wall_seconds=time.monotonic()-started,peak_rss_native=resource.getrusage(resource.RUSAGE_SELF).ru_maxrss,source_counts=dict(news=len(news),notice=count),training_type_count=len(mapping),production_manifest_built=False,outcome_access=False)
        publish(Path(destination)/'R8_METADATA_MEASUREMENT.json',value)
        return value
    destination=Path(destination)
    interrupted=[identity(destination/name) for name in ('NOTICE_TRAINING_TYPES.json','R8_METADATA_MANIFEST.json') if (destination/name).exists()]
    metadata=dict(news_lag_scope='M_72H_IDS',notice_chars='TITLE_PLUS_BODY_NO_SEPARATOR',notice_type_map=mapping,
                  notice_training_types=sorted(mapping.values()),news_manifests=config['news_manifests'],notice_scope=config['notice_scope'],coverage=config['coverage'])
    destination=Path(destination)
    types=publish(destination/'NOTICE_TRAINING_TYPES.json',dict(state='TRAINING_ONLY_NOTICE_TYPES',period=['2021-10-01','2023-12-31'],notice_scope=config['notice_scope'],notice_type_map=mapping,notice_training_types=metadata['notice_training_types']))
    result=dict(state='R8_SOURCE_METADATA_FROZEN',metadata=metadata,training_types_receipt=identity(types),config=config_id,
                coverage_evidence=config['coverage_evidence'],builder=identity(__file__),source_counts=dict(news=len(news),notice=count),
                value_reads=False,training_period=['2021-10-01','2023-12-31'],mapping_rule='T_ + full SHA256 of exact UTF8 training-only raw type; later types OTHER')
    manifest=publish(destination/'R8_METADATA_MANIFEST.json',result)
    receipt_path=destination/'R8_BUILD_RECEIPT.json'
    if receipt_path.exists():
        validate_receipt(manifest,receipt_path)
        return result
    recovered=bool(interrupted)
    peak=resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
    publish(receipt_path,dict(manifest=identity(manifest),training_types=identity(types),
              wall_seconds=None if recovered else time.monotonic()-started,
              peak_rss_native=None if recovered else peak,config=config_id,builder=identity(__file__),
              source_identities=[*config['news_manifests'],config['notice_scope']],coverage_evidence=config['coverage_evidence'],
              source_counts=result['source_counts'],training_period=result['training_period'],metadata_only=True,
              recovery=dict(recovered=recovered,previously_published=interrupted,
                  initial_measurements='UNKNOWN_AFTER_INTERRUPTION' if recovered else 'RECORDED',
                  recovery_wall_seconds=time.monotonic()-started if recovered else None,
                  recovery_peak_rss_native=peak if recovered else None)))
    validate_receipt(manifest,receipt_path)
    return result

def validate_receipt(manifest_path,receipt_path):
    """Bind all three products and immutable build inputs; no model/value access."""
    manifest=strict(Path(manifest_path).read_text())
    receipt=strict(Path(receipt_path).read_text())
    need(manifest.get('state')=='R8_SOURCE_METADATA_FROZEN' and manifest.get('value_reads') is False,'R8 metadata manifest state')
    config=strict(checked(manifest['config']).read_text())
    need(set(config)=={'news_manifests','notice_scope','coverage','coverage_evidence'},'Metadata config schema')
    sources=[*config['news_manifests'],config['notice_scope']]
    need(config['coverage_evidence'] and len(config['news_manifests'])==2,'Build source/coverage required')
    metadata=manifest['metadata']
    need(all(metadata[k]==config[k] for k in ('news_manifests','notice_scope','coverage')),'Manifest config metadata drift')
    need(manifest['coverage_evidence']==config['coverage_evidence'],'Manifest coverage drift')
    types=strict(checked(manifest['training_types_receipt']).read_text())
    expected_types=dict(state='TRAINING_ONLY_NOTICE_TYPES',period=['2021-10-01','2023-12-31'],notice_scope=config['notice_scope'],
                        notice_type_map=metadata['notice_type_map'],notice_training_types=metadata['notice_training_types'])
    need(types==expected_types,'Training-only type object drift')
    expected=dict(manifest=identity(manifest_path),training_types=manifest['training_types_receipt'],
        config=manifest['config'],builder=manifest['builder'],source_identities=sources,
        coverage_evidence=config['coverage_evidence'],source_counts=manifest['source_counts'],training_period=manifest['training_period'],metadata_only=True)
    need(all(receipt.get(k)==v for k,v in expected.items()),'R8 build receipt identity drift')
    need(set(receipt)==set(expected)|{'wall_seconds','peak_rss_native','recovery'},'R8 build receipt field set')
    recovery=receipt['recovery'];need(set(recovery)=={'recovered','previously_published','initial_measurements','recovery_wall_seconds','recovery_peak_rss_native'},'Recovery field set')
    if recovery['recovered']:
        need(receipt['wall_seconds'] is None and receipt['peak_rss_native'] is None and recovery['initial_measurements']=='UNKNOWN_AFTER_INTERRUPTION' and recovery['previously_published'], 'Never fabricate interrupted first-build measurements')
        need(recovery['recovery_wall_seconds']>=0 and recovery['recovery_peak_rss_native']>0,'Recovery measurement required')
        for item in recovery['previously_published']:
            need(item in [expected['manifest'],expected['training_types']],'Recovery publication identity drift')
    else:
        need(recovery==dict(recovered=False,previously_published=[],initial_measurements='RECORDED',recovery_wall_seconds=None,recovery_peak_rss_native=None),'Initial build recovery drift')
        need(receipt['wall_seconds']>=0 and receipt['peak_rss_native']>0,'Initial build measurement required')
    items=[identity(manifest_path),identity(receipt_path),manifest['training_types_receipt'],manifest['config'],manifest['builder'],*sources,*manifest['coverage_evidence']]
    for item in items:checked(item)
    return list({item['path']:item for item in items}.values())

if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('--config',required=True);parser.add_argument('--output',required=True);parser.add_argument('--measure-only',action='store_true')
    args=parser.parse_args();build(args.config,args.output,measure_only=args.measure_only)
