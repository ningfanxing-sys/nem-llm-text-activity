"""CONFX8 read-only frozen-design checks; --adapters selects a staged replica before install.
python verify_frozen_design.py --adapters DIR/CONFX2 --out FROZEN_DESIGN_VERIFICATION.json
"""
import argparse, ast, hashlib, json, stat
from pathlib import Path
HERE = Path(__file__).resolve().parent; CONF = HERE.parent
EXPECTED = {'BUDGET':'86400.0','JOB_LIMIT':'2 * 1024 ** 3','TREE_LIMIT':'6.6 * 1024 ** 3',
            'THROTTLE':'6.0 * 1024 ** 3','FIT_HEADROOM_BYTES':'3 * 1024 ** 3','NEWS_JOB_LIMIT':'3758096384',
            'NOTICE_JOB_LIMIT':'TREE_LIMIT','NEWS_REFERENCE_ROWS':'131472',
            'NEWS_REFERENCE_PEAKS':"{'news_wide': 3300741536, 'news_narrow': 2487864800}",
            'NEWS_REFERENCE_COLUMNS':"{'news_wide': 1258, 'news_narrow': 872}"}
A1 = {'A1/A1_FREEZE_CANDIDATE.json':'fc4d529a3918b534265d6938f05ab65e55149aeb598808470d24ef04c2d52a41',
      'A1/ADDENDUM_A1_FINAL.md':'d85131c9a12fd6847d778a4068485f661b8068af7354e835151149c8b03ace02',
      'A1/DECISIONS_A1_zh.md':'dca801989de8834709e93bb0f57934734411506546e13082bfd8df182dddead5'}

def sha(p): return hashlib.sha256(Path(p).read_bytes()).hexdigest()
def verify(adapters):
    frozen=json.loads((CONF/'FREEZE.json').read_text())
    design={rel:sha(CONF/rel)==item['sha256'] and (CONF/rel).stat().st_size==item['bytes'] for rel,item in frozen['frozen_files'].items()}
    spec=json.loads((HERE/'SPEC_FREEZE.json').read_text())
    parent=HERE/'archive/pre_CONFX8/CONFX2/ADAPTER_FREEZE.json'
    if not parent.exists():parent=CONF/'CONFX2/ADAPTER_FREEZE.json'
    parent_ok=sha(parent)==spec['parent_adapter_freeze']['sha256']
    constants={n.targets[0].id:ast.unparse(n.value) for n in ast.parse((Path(adapters)/'execution_adapter.py').read_text()).body
        if isinstance(n,ast.Assign) and len(n.targets)==1 and isinstance(n.targets[0],ast.Name)}
    resource={k:constants.get(k)==v for k,v in EXPECTED.items()}
    records={'spec_hash':sha(HERE/'SPEC.md')==spec['spec']['sha256'],
        'spec_freeze_read_only':not (HERE/'SPEC_FREEZE.json').stat().st_mode & (stat.S_IWUSR|stat.S_IWGRP|stat.S_IWOTH),
        'prior_scope_hash':sha(CONF/'CONFX7/UNCHANGED_CODE.json')==spec['parent_scope_proof']['sha256']}
    a1={rel:sha(CONF/rel)==digest for rel,digest in A1.items()}
    ok=all(design.values()) and parent_ok and all(resource.values()) and all(records.values()) and all(a1.values())
    return {'task':'CONFX8','state':'PASS' if ok else 'FAIL','design_frozen_files_verified':len(design),
        'design_files_unchanged':design,'registered_confx7_parent_unchanged':parent_ok,
        'spec_freeze_checks':records,'exact_resource_constants':resource,'a1_files_unchanged':a1,
        'compute_plan_unchanged':design.get('COMPUTE_PLAN.md'),
        'template_rule':'Author-authorized news resource limit/projection adjustment only; no research-method change.',
        'host_state_opened':False,'production_commands_run':[]}

def main():
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--adapters',default=str(CONF/'CONFX2'));p.add_argument('--out',required=True)
    a=p.parse_args();r=verify(a.adapters);Path(a.out).write_text(json.dumps(r,indent=2,sort_keys=True)+'\n')
    print(json.dumps({'state':r['state'],'design_files':r['design_frozen_files_verified']}));raise SystemExit(0 if r['state']=='PASS' else 1)

if __name__=='__main__':main()
