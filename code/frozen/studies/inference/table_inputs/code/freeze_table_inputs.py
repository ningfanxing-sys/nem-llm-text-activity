'Check table-input sources and save their hashes.'
from pathlib import Path
from datetime import datetime,timezone
import argparse,json,sys
import producer as R
P=R.P

def sources():
    paths=[*sorted((R.ROOT/'code').glob('*.py')),*sorted((R.ROOT/'tests').glob('*.py')),
           R.ROOT/'SPEC.md',R.ROOT/'DEPENDENCY_PINS.json',R.ROOT/'HOST_RUN.md',R.ROOT/'T5_ROWS.json',R.ROOT/'EXPECTED_TEST_CASES.json',
           R.ROOT/'G05_CLASSIFICATION.json',R.ROOT/'G05_INTERFACE_SCHEMAS.json',R.ROOT/'G05_FILL_INTERFACE_REQUEST.md',R.ROOT/'DEPENDENCY_REFRESH.json']
    return {str(p.relative_to(R.AP)):P.sha256(p) for p in paths}

def validate_receipt(item):
    r=P.strict_json(P.checked(item))
    P.require(r.get('schema')=='A8POST5_SERIAL_TEST_V1' and r.get('state')=='PASS' and r.get('returncode')==0,
              'AP5 clean full-suite receipt required')
    P.require(r.get('full_collection_complete') is True and r['passed']==r['collected'] and r['source_stable'] is True,
              'AP5 incomplete collection/source evidence')
    P.require(r['nice']==20 and r['single_test_process'] is True and r['minimum_memory_free_percent']>=25
              and r['scratch_bytes']<1000000000 and r['peak_rss_bytes']<=1.5*1024**3, 'AP5 invalid resources')
    P.require(r['own_sources']==sources(), 'AP5 source changed after tests')
    P.require(r.get('dependency_sources')==R.verify_pins()['files'], 'AP5 tested dependency inventory mismatch')
    P.require(r.get('production_payload_reads')==0 and r.get('fill_source_k8')=='PASS', 'AP5 missing safe fill e2e')
    for name in ('collection','execution_events','log','resource_monitor'):P.checked(r[name])
    cases=P.strict_json(r['collection']['path'])['nodeids']
    events=[json.loads(line) for line in Path(r['execution_events']['path']).read_text().splitlines()]
    P.require(len(cases)==r['collected'] and len(set(cases))==len(cases), 'AP5 duplicate collection')
    old=P.strict_json(R.AP/'a8post3/final_suite3/TEST_CASES.json')['nodeids']

    normalize=lambda n: n.split('studies/inference/')[-1] if 'studies/inference/' in n else n
    present={normalize(n) for n in cases}
    expected=P.strict_json(R.ROOT/'EXPECTED_TEST_CASES.json')
    P.require(present=={normalize(n) for n in expected['nodeids']}, 'AP5 exact full parametrized census required')
    P.require(expected['test_source_sha256']==P.sha256(R.ROOT/'tests/test_producer.py'), 'AP5 collected test inventory drift')
    P.require(len(old)==108 and {normalize(n) for n in old}<=present, 'AP5 all 108 specified cases required')
    import ast
    names={n.name for n in ast.parse((R.ROOT/'tests/test_producer.py').read_text()).body
           if isinstance(n,ast.FunctionDef) and n.name.startswith('test_')}
    executed={n.split('::')[-1].split('[')[0] for n in cases if 'test_producer.py::' in n}
    P.require(executed==names, 'AP5 every additive regression must execute')
    P.require(all({e['phase']:e['outcome'] for e in events if e['nodeid']==node}==dict(setup='passed',call='passed',teardown='passed') for node in cases), 'AP5 missing test phase')
    return r

def candidate(test_item,acceptance_item):
    pins=R.verify_pins();r=validate_receipt(test_item)
    full=P.strict_json(P.checked(r['fill_full_native_k8_receipt']))
    P.require(full.get('state')=='PASS' and r.get('fill_full_native_k8')=='PASS',
              'AP5 full specified native forest/typed-table K8 contract remains blocked; bounded fixture PASS cannot freeze')
    a=P.strict_json(P.checked(acceptance_item))
    P.require(a.get('schema')=='A8POST5_INDEPENDENT_ACCEPTANCE_V1' and a.get('state')=='ACCEPTED_FOR_SOURCE_FREEZE'
              and a.get('independent') is True and bool(a.get('verified_by')), 'AP5 real independent acceptance missing')
    P.require(a.get('tested_sources')==sources() and a.get('test_receipt')==test_item
              and a.get('dependency_pins_sha256')==P.sha256(R.ROOT/'DEPENDENCY_PINS.json'), 'AP5 review version association')
    return dict(schema='A8POST5_CODE_FREEZE_V1',state='A8POST_CODE_FROZEN_BEFORE_T5',
                frozen_utc=datetime.now(timezone.utc).isoformat(),files=sources(),external_identities=pins['files'],
                exact_ast=pins.get('exact_ast',{}),test_receipt=test_item,independent_acceptance=acceptance_item,
                freeze_readiness='READY_FOR_T5_FREEZE',production_status='PRODUCTION_GATED')

def verify(path):
    path=Path(path)
    P.require(path.resolve()==R.ROOT/'A8POST5_CODE_FREEZE.json', 'AP5 exact additive freeze path')
    f=P.strict_json(path)
    P.require(f.get('schema')=='A8POST5_CODE_FREEZE_V1' and f.get('state')=='A8POST_CODE_FROZEN_BEFORE_T5', 'AP5 freeze absent/invalid')
    pins=R.verify_pins()
    P.require(f['files']==sources() and f['external_identities']==pins['files'] and f.get('exact_ast')==pins.get('exact_ast',{}), 'AP5 freeze source drift')

    c=candidate(f['test_receipt'],f['independent_acceptance'])
    P.require(all(f[k]==v for k,v in c.items() if k!='frozen_utc'), 'AP5 freeze approval drift')
    return f

def main(argv=None):
    p=argparse.ArgumentParser();p.add_argument('--write',type=Path,required=True)
    p.add_argument('--test-receipt',type=Path,required=True);p.add_argument('--review-acceptance',type=Path,required=True)
    a=p.parse_args(argv)
    P.require(a.write.resolve()==R.ROOT/'A8POST5_CODE_FREEZE.json', 'AP5 non-overwriting additive path only')
    R.exclusive(a.write,candidate(P.identity(a.test_receipt),P.identity(a.review_acceptance)))

if __name__=='__main__':main()
