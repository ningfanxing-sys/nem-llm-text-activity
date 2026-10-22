"""Write the design freeze only after a successful fresh no-values self-check."""
from pathlib import Path
from datetime import datetime,timezone
import json,sys,os
CONF=Path(__file__).resolve().parent.parent
sys.path[:0]=[str(CONF),str(CONF/'code')]
from audit_io import read_text,sha256,record

def run():
    if (CONF/'FREEZE.json').exists():raise FileExistsError('Never overwrite an existing freeze')
    receipt=json.loads(read_text(CONF/'SELF_CHECK.json','require successful selfcheck before freeze'))
    if receipt['state']!='PASS' or not all(row['pass'] for row in receipt['checks']):
        raise ValueError('Self-check did not pass')
    if any(receipt.get(k)!=0 for k in ['study_fits','study_scores','confirmation_feature_builds']):
        raise ValueError('Design-only task boundary violated')
    manifest=json.loads(read_text(CONF/'INPUT_MANIFEST.json','explicit incomplete-input design status'))
    # Verify every current input again as opaque bytes. Mutating a sibling
    # protocol during hashing yields drift and stops, without controlling it.
    for row in manifest['inputs']:
        if sha256(row['path'])!=row['sha256']:raise ValueError('Input drift before freeze: '+row['path'])
    # Live access logs continue on verification. Seal a static prefix snapshot.
    log=read_text(CONF/'OPENED_PATHS.jsonl','seal complete opened-path prefix')
    (CONF/'OPENED_PATHS_AT_FREEZE.jsonl').write_text(log)
    snapshot_urls=CONF/'MODEL_URL_ACCESS.jsonl'
    if snapshot_urls.exists():
        (CONF/'MODEL_URL_ACCESS_AT_FREEZE.jsonl').write_text(read_text(snapshot_urls,'seal model source URL prefix'))
    frozen={}
    exclude={'FREEZE.json','OPENED_PATHS.jsonl','MODEL_URL_ACCESS.jsonl','CLOSURE_VERIFICATION.json'}
    for p in sorted(CONF.rglob('*')):
        if p.is_file() and p.name not in exclude and '__pycache__' not in p.parts:
            frozen[str(p.relative_to(CONF))]={'sha256':sha256(p),'bytes':p.stat().st_size}
    value={
       'task':'CONF','created_utc':datetime.now(timezone.utc).isoformat(),
       'state':'DESIGN_FROZEN_EXECUTION_BLOCKED_PENDING_INPUT_COMPLETION',
       'historical_not_prospective':True,'scientific_execution_authorized':False,
       'self_check_passed_before_freeze':True,'self_check_sha256':sha256(CONF/'SELF_CHECK.json'),
       'input_manifest_sha256':sha256(CONF/'INPUT_MANIFEST.json'),
       'pending_dependencies':[x['id'] for x in manifest['pending_dependencies']],
       'frozen_files':frozen,
       'study_fits':0,'study_scores':0,'confirmation_feature_builds':0,
       'source_panel_value_access':False,
       'source_text_access_caveat':'A body-containing ARTICLE_METADATA.json was mechanically decoded during metadata preparation; only a prewindow sample was displayed. BLINDING_ACCESS_NOTE.md records the limitation; do not claim zero raw-text decoding.',
       'access_record':'OPENED_PATHS_AT_FREEZE.jsonl static prefix + append-only OPENED_PATHS.jsonl for subsequent verification',
       'execution_rule':'Later task must verify this freeze and bind all pending input identities in a completed input freeze before any feature read of window values. It must not change a scientific rule. Seal all completed registered predictions before outcome scoring.',
       'budget_rule':'24 fitting wall-hours, fixed priority and metadata-only whole-stage admission; no effect-dependent omission.'}
    fd=os.open(CONF/'FREEZE.json',os.O_WRONLY|os.O_CREAT|os.O_EXCL,0o444)
    try:os.write(fd,(json.dumps(value,ensure_ascii=False,indent=2)+'\n').encode())
    finally:os.close(fd)
    print(json.dumps({'state':value['state'],'frozen_files':len(frozen),'pending_inputs':len(manifest['pending_dependencies'])}))
if __name__=='__main__':run()
