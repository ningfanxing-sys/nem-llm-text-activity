"""T3 continuity for CONFX8: preserve original T3 identities plus the immediate CONFX7 parent.
Only listed CONF adapter Python code, HOST_RUN and adapter freeze are hashed; all other T3 payloads remain unopened.
python t3_continuity.py --out T3_CONTINUITY.json
"""
import argparse, hashlib, json
from pathlib import Path
HERE=Path(__file__).resolve().parent;CONF=HERE.parent;Q1=CONF.parent

def sha(p):return hashlib.sha256(Path(p).read_bytes()).hexdigest()
def main():
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--out',required=True);a=p.parse_args()
    manifest=CONF/'TIMESTAMPS/T3/MANIFEST_T3.sha256'
    entries=[];opened=[];unopened=[]
    for line in manifest.read_text().splitlines():
        if not line.strip() or line.startswith('#'):continue
        digest,size,rel=line.split(None,2);entries.append(rel)
        safe=(rel in ('CONF/HOST_RUN.md','CONF/CONFX2/ADAPTER_FREEZE.json') or
              (rel.startswith('CONF/CONFX2/') and rel.endswith('.py') and 'host_state/' not in rel))
        if not safe:
            unopened.append(rel);continue
        path=Q1/rel;current=sha(path)
        candidates=[HERE/'archive/pre_CONFX8'/rel[len('CONF/'):],CONF/'CONFX7/archive/pre_CONFX7'/rel[len('CONF/'):]]
        preserved=path if current==digest else next((q for q in candidates if q.is_file() and sha(q)==digest),None)
        opened.append({'t3_path':rel,'t3_sha256':digest,'current_sha256':current,'t3_bytes':int(size),
            't3_preserved':preserved is not None,'preserved_copy':str(preserved) if preserved else None})
    before=json.loads((HERE/'BEFORE_IDENTITIES.json').read_text())
    parent={rel:sha(Path(item['archive_path']))==item['sha256'] for rel,item in before.items()}
    ok=all(i['t3_preserved'] for i in opened) and all(parent.values())
    r={'task':'CONFX8','state':'PASS' if ok else 'FAIL','t3_manifest':{'path':str(manifest),'sha256':sha(manifest),'entries':len(entries)},
       'code_entries_verified':opened,'other_payloads_not_opened':unopened,'immediate_confx7_parent_archives_verified':parent,
       'confx7_continuity_record_sha256':sha(CONF/'CONFX7/T3_CONTINUITY.json'),
       'host_state_opened':False,'seal_score_prediction_payloads_opened':False,'production_commands_run':[]}
    Path(a.out).write_text(json.dumps(r,indent=2,sort_keys=True)+'\n');print(json.dumps({'state':r['state'],'verified':len(opened),'not_opened':len(unopened)}))
    raise SystemExit(0 if ok else 1)

if __name__=='__main__':main()
