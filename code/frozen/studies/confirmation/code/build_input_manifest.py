'Hash input panels and record their source metadata.'
from pathlib import Path
import json,sys,datetime
confirmation=Path(__file__).resolve().parent.parent
PROJ=confirmation.parents[2]
sys.path.insert(0,str(confirmation))
from audit_io import read_text,sha256,record

def run():
    files={}; absent=[]
    def add(p,role,expected=None):
        p=Path(p).resolve(); key=str(p)
        if key in files:
            if role not in files[key]['roles']:files[key]['roles'].append(role)
            if expected and files[key]['sha256']!=expected:raise ValueError('Source receipt mismatch '+key)
            return
        if not p.is_file():absent.append({'path':key,'role':role});return
        if ('semantic_validation' in key and '/private/' in key) or any(s in key for s in ['auth.json','/.env','keychain']):return
        nrx_dir=PROJ/'studies/notice_extraction'
        if p.is_relative_to(nrx_dir):
            origin=p
            rel=p.relative_to(nrx_dir)
            snapshot=confirmation/'evidence/notice_label_reference'/rel
            snapshot.parent.mkdir(parents=True,exist_ok=True)
            if str(snapshot.resolve()) in files:return
            record(origin,'reference_snapshot_bytes','notice_extraction is in progress; freeze observed reference bytes without controlling producer')
            snapshot.write_bytes(origin.read_bytes())
            p=snapshot.resolve();key=str(p)
            role='notice_extraction reference snapshot; final producer identities pending; original '+str(origin)
            expected=None
            if key in files:return
        digest=sha256(p)
        if expected and digest!=expected:raise ValueError('Source receipt mismatch '+key)
        files[key]={'path':key,'sha256':digest,'bytes':p.stat().st_size,'roles':[role],'value_decoding':'none; opaque streaming hash'}
    source_inventory=json.loads(read_text(PROJ/'studies/source_acquisition/INVENTORY.json','certified metadata only'))
    downloads=json.loads(read_text(PROJ/'studies/source_acquisition/DOWNLOAD_RECEIPT.json','certified transfer identities only'))
    for row in downloads['downloads']:add(row['local_path'],'source_acquisition source and acquisition provenance',row.get('sha256'))
    def collect(obj,role):
        if isinstance(obj,dict):
            p=obj.get('path') or obj.get('local_path')
            if isinstance(p,str) and p.startswith('/') and obj.get('sha256'):add(p,role,obj['sha256'])
            for value in obj.values():collect(value,role)
        elif isinstance(obj,list):
            for value in obj:collect(value,role)
    collect(source_inventory,'source_acquisition selected existing source')
    for p in source_inventory['source_inventories'].values():
        add(p,'certified source metadata inventory')
        collect(json.loads(read_text(p,'certified metadata inventory only')),'source_acquisition selected source inventory')
    old=json.loads(read_text(PROJ/'studies/B1b/source_design.json','historical bank identity only'))
    for path,expected in old.get('window_design',{}).get('bank_sha256',{}).items():add(path,'original notice_fitting training bank',expected)
    rf=json.loads(read_text(PROJ/'studies/notice_fitting/INPUT_MANIFEST.json','notice_fitting input identities only'))
    for path,row in rf['files'].items():
        if '/site-packages/' in path or '/lib/python' in path:continue

        keep=(path.endswith(('.py','.md')) or path.endswith('development_metadata.parquet') or
              path.endswith('/forecast_replication/corrected_numeric.npy') or '/label_availability/input_checks/train_indices_' in path)
        if keep:add(path,'inherited notice_fitting code/training identity')


    opened=json.loads('null')
    log=read_text(confirmation/'OPENED_PATHS.jsonl','audit input discovery')
    for line in log.splitlines():
        row=json.loads(line);p=Path(row['path'])
        if str(p).startswith(str(confirmation)) or '/.llm_client/cache/' in str(p):continue
        if p.is_file():add(p,'opened design dependency')
    for folder in ['studies/notice_extraction','studies/news_extraction']:
        base=PROJ/folder;record(base,'directory_metadata','current upstream contract identities')
        for p in base.iterdir():
            if p.is_file() and p.suffix in ['.py','.md','.json'] and not any(s in p.name for s in ['RESULT','progress','labels','metadata','OUTPUT_MANIFEST','SCOPE_RECEIPT']):
                add(p,'upstream contract/code identity; extraction artifacts separate')
    critical=[
      PROJ/'studies/notice_records/source_relations/assembler/assemble_source_relations.py',
      PROJ/'studies/notice_records/event_assembly/assemble_event_features.py',
      PROJ/'notice_assembly/notice_event_records.py',
      PROJ/'studies/word_features/aligned/english_stopwords.txt',
      PROJ/'studies/word_features/aligned/run_word_features.py',
      PROJ/'studies/word_features/aligned/PROTOCOL_TFN2.md',
      PROJ/'studies/news_features/news_feature_definitions.py',
      PROJ/'studies/news_scheduling/news_resource_scheduler.py',
      Path('scripts/historical_support/audit_historical_support.py')]
    for p in critical:add(p,'mandatory method contract')
    pending=[
      {'id':'NRX_FINAL_LABEL_BANK','required':'Final isolated luna extraction receipt; full source ID and success/failure partition; canonical source clocks; label file byte hash, with no row-content read before completed input freeze','producer':'notice_extraction; no old M331 substitution; current code/docs are reference snapshots, final producer contract/code/label freeze must be bound before values'},
      {'id':'NEWSX_2026_EXTENSION_LABEL_BANK','required':'Frozen v4 host extraction on all 286 source_acquisition batch IDs including February; normalized text/source hashes and terminal failure partition; older v4 bank identity retained','producer':'code/prepare_news_manifest.py host adapter; NEWS_EXTRACTION_PLAN.md'},
      {'id':'NEWS_JAN_FEB_2026_BRIDGE','required':'Select and hash existing official January-February source files by metadata only, exact B3/forecast_replication clocks, continuous historical days for expanding refits','producer':'separate execution input completion'},
      {'id':'NOTICE_FINAL_CANONICAL_PREFIX','required':'Canonical source-ID/version/clock mapping across old/new registries and July27 lead-in; no uncovered month as zero; immutable registry and normalization hash','producer':'notice_extraction/source_acquisition input completion'},
      {'id':'E3_TRAINING_AND_CONFIRMATION_INPUTS','required':'Exact corrected historical E3 training block and new source_acquisition P5MIN source/clock mapping frozen for E3 only','producer':'separate execution input completion'},
      {'id':'MINILM_WEIGHT_INSTALLATION','required':'Pinned weight SHA from ENCODER_LOCK.json, local installed package versions and model revision, verify config/tokenizer frozen hashes before encoding','producer':'ENCODER_LOCK.json and model_lock'}
    ]
    result={'schema_version':1,'task':'confirmation','created_utc':datetime.datetime.now(datetime.timezone.utc).isoformat(),
      'state':'DESIGN_INPUT_IDENTITIES_FROZEN_PENDING_UPSTREAM_COMPLETION','inputs':sorted(files.values(),key=lambda r:r['path']),
      'pending_dependencies':pending,'absent_named_existing_inputs':absent,
      'values_in_manifest':False,'source_panels_decoded':False,
      'claim_limit':'Hashes bind opaque bytes, not completeness/finiteness/first-publication. No label or numeric source values included.',
      'completion_rule':'Fill upstream identities and predeclared bridges only; freeze completed manifest before any feature read of window values; no scientific rule change.'}
    if absent:raise RuntimeError('Expected existing input absent; see builder stdout: '+json.dumps(absent))
    (confirmation/'INPUT_MANIFEST.json').write_text(json.dumps(result,ensure_ascii=False,indent=2)+'\n')
    print(json.dumps({'input_files':len(files),'opaque_bytes_hashed':sum(x['bytes'] for x in files.values()),'pending_dependencies':len(pending)}))
if __name__=='__main__':run()
