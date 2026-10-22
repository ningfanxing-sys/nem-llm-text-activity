
'Save the source hashes used by statistical inference.'
import argparse,ast,hashlib,json
from datetime import datetime,timezone
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1];PROJ=ROOT.parents[2]
DOCS=('HOST_RUN_A8POST.md','PROPOSED_INTERFACE_CHANGES.md','DEPENDENCY_PINS.json',
      'SYNTHETIC_SPEC.md','SYNTHETIC_SPEC_IDENTITY.json','SYNTHETIC_SPEC_A8POST2.md',
      'SYNTHETIC_SPEC_A8POST2_IDENTITY.json','INPUTS.template.json','tests/SYNTHETIC_SPECIFICATION_2_CONSUMER_FIXTURE.json','T5_REQUIREMENTS.md',
      'a8post3/INPUTS_V2_validation_group_5.template.json','a8post3/SPEC.md','a8post3/SPEC_IDENTITY.json','a8post3/T5_PENDING.txt','a8post3/HOST_ALIGNMENT_source.md')


def inventory():return (*[str(p.relative_to(ROOT)) for folder in ('code','tests') for p in sorted((ROOT/folder).glob('*.py'))],*DOCS)
def sha(path):return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def verify_dependencies(pins):
    for rel,digest in pins['files'].items():
        p=(PROJ/rel).resolve()
        if not p.is_relative_to(PROJ) or sha(p)!=digest:raise ValueError('Dependency drift: '+rel)
    for rel,names in pins.get('exact_ast',{}).items():
        nodes={n.name:n for n in ast.parse((PROJ/rel).read_text()).body if isinstance(n,(ast.FunctionDef,ast.ClassDef))}
        for name,digest in names.items():
            if name not in nodes or hashlib.sha256(ast.dump(nodes[name],include_attributes=False).encode()).hexdigest()!=digest:
                raise ValueError('Exact AST dependency drift: '+rel+'/'+name)


def candidate():
    pins=json.loads((ROOT/'DEPENDENCY_PINS.json').read_text());verify_dependencies(pins)
    status=json.loads((ROOT/'PRODUCER_RECHECK.json').read_text())
    item=status['source_test_receipt'];testpath=Path(item['path']).resolve()
    if not testpath.is_relative_to(ROOT) or sha(testpath)!=item['sha256']:raise ValueError('Suite receipt identity drift')
    testroot=testpath.parent
    tests=json.loads(testpath.read_text())
    if tests.get('schema')!='A8POST3_SERIAL_TEST_V1' or tests['state']!='PASS' or tests['returncode']!=0:raise ValueError('Full A8POST3 suite not PASS')
    if not tests.get('full_collection_complete') or tests.get('collected')!=tests.get('passed') or not tests.get('source_stable') or tests.get('scratch_bytes',1000000000)>=1000000000 or tests.get('minimum_memory_free_percent',0)<25 or tests.get('nice',0)<5:raise ValueError('Suite source/resource evidence invalid')
    if tests['peak_rss_bytes']>1.5*1024**3:raise ValueError('RSS limit exceeded')
    tested=json.loads((testroot/'SOURCE_HASHES_AT_TEST.json').read_text())
    for rel in inventory():
        if (rel.endswith('.py') or rel.startswith('tests/')) and tested.get(rel)!=sha(ROOT/rel):raise ValueError('Code changed after tests: '+rel)
    if status.get('freeze_readiness')!='READY_FOR_T5_FREEZE':raise ValueError('Unresolved producer review: '+status.get('freeze_readiness','absent'))
    return dict(schema='A8POST_CODE_FREEZE_V1',state='A8POST_CODE_FROZEN_BEFORE_T5',frozen_utc=datetime.now(timezone.utc).isoformat(),
        files={rel:sha(ROOT/rel) for rel in inventory()},test_receipts={str((testroot/rel).relative_to(ROOT)):sha(testroot/rel) for rel in ('TEST_RESULTS.json','RUNTIME_MEMORY.json','NATIVE_RUNTIME_MEMORY.json','TEST_LOG.txt','SOURCE_HASHES_AT_TEST.json','DEPENDENCY_HASHES_AT_TEST.json','TEST_CASES.json','TEST_EXECUTION_EVENTS.jsonl','RESOURCE_MONITOR.json','TEST_RESOURCE_LIMITS.json')},
        external_identities=pins['files'],exact_ast=pins.get('exact_ast',{}),freeze_readiness='READY_FOR_T5_FREEZE',production_status='PRODUCTION_GATED',
        timestamp_checks='source review; effective specification2/T4B/T5 and SCORE_RECEIPT/seal gates remain mandatory')


def verify(path):
    record=json.loads(Path(path).read_text())
    if record.get('schema')!='A8POST_CODE_FREEZE_V1' or record.get('state')!='A8POST_CODE_FROZEN_BEFORE_T5':raise ValueError('inference code freeze missing/invalid')
    if set(record['files'])!=set(inventory()):raise ValueError('inference freeze inventory drift')
    for key in ('files','test_receipts'):
        for rel,digest in record[key].items():
            p=(ROOT/rel).resolve()
            if not p.is_relative_to(ROOT) or sha(p)!=digest:raise ValueError('inference frozen file drift: '+rel)
    pins=json.loads((ROOT/'DEPENDENCY_PINS.json').read_text())
    if record['external_identities']!=pins['files'] or record.get('exact_ast')!=pins.get('exact_ast',{}):raise ValueError('Frozen pin registry drift')
    verify_dependencies(pins);return record


def main():
    parser=argparse.ArgumentParser();g=parser.add_mutually_exclusive_group(required=True)
    g.add_argument('--dry-run',action='store_true');g.add_argument('--write',type=Path);g.add_argument('--verify',type=Path);a=parser.parse_args()
    if a.verify:verify(a.verify);print('inference FREEZE VERIFIED');return
    record=candidate()
    if a.write:
        with a.write.open('x') as stream:json.dump(record,stream,indent=2);stream.write('\n')
    else:print(json.dumps(record,indent=2))


if __name__=='__main__':main()
