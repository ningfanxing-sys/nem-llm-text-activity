'Check source paths for notice forecast inputs.'
import argparse
import ast
import datetime as dt
import hashlib
import json
import os
from pathlib import Path
import re
import stat
import sys

sys.dont_write_bytecode = True
HERE = Path(__file__).absolute().parent
PROJ = HERE.parents[4]
C_REL = 'studies/batch_estimation/batch_checks'
FILL_REL = 'tables/table_renderer/validation_group_10'
SCHEMA = 'FORECAST_BINDING_FINAL_ROOT_MAPPING_V1'
STATE = 'FINAL_REVIEWED_SOURCE_MAPPING_NOT_FREEZE'
REVIEW_SCHEMA = 'A8CONSUMER_INDEPENDENT_REVIEW_ACCEPTANCE_V1'
FORBIDDEN = {'host_state','state','dly8','cps8','sealed','scored','scores',
             'predictions','models','evaluation','run'}


def require(ok, why):
    if not ok:
        raise RuntimeError(why)


def regular(path):
    p = Path(path).absolute()
    require('..' not in p.parts and str(p) == os.path.normpath(str(p)), 'Noncanonical metadata path')
    for part in (p, *p.parents):
        require(not stat.S_ISLNK(part.lstat().st_mode), 'Metadata symlink refused: '+str(part))
    require(stat.S_ISREG(p.lstat().st_mode), 'Regular source/metadata file required')
    return p


def identity(path):
    p = regular(path)
    h = hashlib.sha256()
    with p.open('rb') as f:
        for block in iter(lambda: f.read(1048576), b''):
            h.update(block)
    return dict(path=str(p), bytes=p.stat().st_size, sha256=h.hexdigest())


def read(path):
    def pairs(items):
        result = {}
        for key, value in items:
            require(key not in result, 'Duplicate JSON key')
            result[key] = value
        return result
    return json.loads(regular(path).read_text(), object_pairs_hook=pairs,
        parse_constant=lambda value: (_ for _ in ()).throw(RuntimeError('Nonfinite JSON')))


def source_path(root, relative):
    rel = Path(relative)
    require(not rel.is_absolute() and '..' not in rel.parts and rel.parts and
            not FORBIDDEN.intersection(part.lower() for part in rel.parts) and
            rel.suffix in ('.py','.md','.json','.sh','.txt','.tex','.log'),
            'Source inventory path escaped permitted metadata')
    return Path(root)/rel


def constant(path, name):
    tree = ast.parse(regular(path).read_text())
    found = [node.value for node in tree.body if isinstance(node, ast.Assign)
        and any(isinstance(target, ast.Name) and target.id == name for target in node.targets)]
    require(len(found) == 1, 'Source must declare exactly one '+name)
    value = ast.literal_eval(found[0])
    require(isinstance(value, str) and value.strip(), 'Invalid source constant '+name)
    return value


def utc(value):
    require(isinstance(value, str), 'UTC evidence required')
    stamp = dt.datetime.fromisoformat(value.replace('Z','+00:00'))
    require(stamp.utcoffset() == dt.timedelta(0), 'Evidence must be UTC')
    return stamp


def mapping_sha256(mapping):
    return hashlib.sha256(json.dumps(mapping, sort_keys=True, separators=(',', ':'),
                                    allow_nan=False).encode()).hexdigest()


def final_mapping_contract(project=PROJ):

    project = Path(project).absolute()
    c = project/C_REL
    return dict(schema='FORECAST_BINDING_FINAL_ROOT_MAPPING_CONTRACT_V1',
        consumer_root=str(c), fill_root=str(project/FILL_REL),
        fill_relative_path=FILL_REL,
        source_metadata=[dict(path=str(c/name), schema=schema, state=state) for name,schema,state in (
            ('SOURCE_LOCK.json',None,'REVIEW_SNAPSHOT_NOT_FREEZE'),
            ('TABLE_RESULTS_BINDING.json','A8CONSUMER_TABLE_RESULTS_BINDING_V1','PINNED_SOURCE_ASSOCIATION_NOT_FREEZE'),
            ('SOURCE_PREPARATION_RECEIPT.json','A8CONSUMER_SOURCE_PREPARATION_V1','REVIEW_SNAPSHOT_NOT_FREEZE'),
            ('TEST_RESULTS.json',None,'PASS'),
            ('REVIEW_ACCEPTANCE.json',REVIEW_SCHEMA,'FREEZE-READY'))],
        publication_metadata=[dict(path=str(c/name), schema=schema, state=state,
                                   identity=None) for name,schema,state in (
            ('CONSUMER_FREEZE.json',None,'FROZEN_PATH_ASSOCIATION_BEFORE_T5'),
            ('SCORER_CODE_FREEZE.json','A8POST_LOSS_EXPORT_FREEZE_V1','A8_SCORER_CODE_FROZEN_BEFORE_T5'),
            ('RELEASE_BINDINGS.json',None,None),
            ('SCORER_BINDINGS.json',None,None))],
        publication_identity_rule='Required later by source; null is pending, never an identity or authorization',
        consumer_scope='source/path/schema association only; independent corrected reader owns scientific eligibility')


def record_final_mapping(base_mapping, *, project=PROJ):

    project = Path(project).absolute()
    c = project/C_REL
    contract = final_mapping_contract(project)
    require(isinstance(base_mapping, dict) and
            base_mapping.get('schema') == 'FORECAST_BINDING_CURRENT_HOST_ROOTS_V3' and
            base_mapping.get('consumer_root') == str(c), 'Exact base V3 consumer path required')
    require(constant(c/'consumer_roots.py','FILL_REL') == FILL_REL,
            'Consumer final validation_group_10 pin is not ready')
    revision = constant(c/'freeze_consumers.py','TASK_REVISION')
    metadata = {}
    for spec in contract['source_metadata']:
        p = Path(spec['path'])
        value = read(p)
        require(value.get('state') == spec['state'] and
                (spec['schema'] is None or value.get('schema') == spec['schema']),
                'Final consumer metadata schema/state mismatch: '+p.name)
        metadata[p.name] = dict(identity=identity(p), contract=spec)
    tests = read(c/'TEST_RESULTS.json')
    require(tests.get('task_revision') == revision and tests.get('failures') == 0 and
            tests.get('errors') == 0 and tests.get('code_unchanged') is True and
            tests.get('production_state_reads') == 0 and tests.get('production_commands_run') == 0,
            'Final C complete clean source-only suite required')
    resources = tests['resources']
    require(resources['nice'] == 20 and resources['minimum_memory_free_percent'] >= 25 and
            resources['scratch_peak_bytes'] < 1000000000 and resources['test_processes'] == 1,
            'Final C synthetic resource receipt invalid')
    tested = tests.get('tested_files')
    require(isinstance(tested, dict) and tested, 'Missing final C tested source inventory')
    tested_identities = {}
    for relative, item in tested.items():
        p = source_path(c, relative)
        actual = identity(p)
        require(isinstance(item,dict) and set(item) == {'bytes','sha256'} and
                actual == dict(path=str(p), **item), 'Final C source changed after tests')
        tested_identities[relative] = actual
    require({'consumer_roots.py','freeze_consumers.py','prepare_sources.py'} <= set(tested),
            'Final C suite omits core source')
    acceptance = read(c/'REVIEW_ACCEPTANCE.json')
    require(acceptance.get('independent') is True and
            isinstance(acceptance.get('reviewed_by'), str) and acceptance['reviewed_by'].strip() and
            acceptance.get('production_state_reads') == 0 and
            acceptance.get('production_commands_run') == 0 and
            acceptance.get('reviewed_files') == tested and
            acceptance.get('test_receipt') == identity(c/'TEST_RESULTS.json') and
            utc(acceptance['reviewed_utc']) >= utc(tests['utc']),
            'Genuine final C acceptance must bind exact completed suite/source')
    reviews = {p.name: {key:value for key,value in identity(p).items() if key != 'path'}
               for p in sorted(c.glob('REVIEW*_source.md'))}
    require(reviews and acceptance.get('reviews') == reviews, 'Current C review inventory mismatch')
    final = acceptance['final_review']
    require(isinstance(final,dict) and set(final) == {'path','bytes','sha256'} and
            Path(final['path']).parent == c and Path(final['path']).name in reviews,
            'Final C acceptance review path mismatch')
    final_path = c/Path(final['path']).name
    require(identity(final_path) == final, 'Final C review identity drift')
    pattern = '(?m)^\\s*(?:\\*{1,2})?(?: Verdict | Conclusion | Status |Decision|Verdict)\\s*[：:]\\s*[`*]*(SET[ _-]FIRST|FREEZE-READY)\\b'
    decisions = {re.sub('[ _-]+',' ',v).upper() for v in re.findall(pattern, regular(final_path).read_text(), re.I)}
    require(decisions == {'FREEZE READY'}, 'Final C review is not unambiguous FREEZE-READY')
    blocking = []
    for name in reviews:
        text = regular(c/name).read_text()
        verdicts = {re.sub('[ _-]+',' ',v).upper() for v in re.findall(pattern,text,re.I)}
        if 'SET FIRST' in verdicts:
            blocking.append(identity(c/name))
    require(isinstance(acceptance.get('replaces'),list) and
            sorted(acceptance['replaces'],key=lambda item:item['path']) ==
            sorted(blocking,key=lambda item:item['path']),
            'Final C acceptance must explicitly replace every SET FIRST identity')
    final_text = regular(final_path).read_text()
    require(all(Path(item['path']).name in final_text and item['sha256'] in final_text
                for item in blocking), 'Final C review omits preserved blocker identities')
    lock = read(c/'SOURCE_LOCK.json')
    fill = read(c/'TABLE_RESULTS_BINDING.json')
    prepared = read(c/'SOURCE_PREPARATION_RECEIPT.json')
    require(lock['table_results_consumer']['root'] == fill['root'] == prepared['fill_root'] == FILL_REL and
            fill['freeze_path'] == FILL_REL+'/TABLE_RESULTS_FREEZE.json' and
            fill['freeze_schema'] == 'TABLE_RESULTS_FREEZE_V1' and
            fill['freeze_state'] == 'TABLE_RESULTS_FROZEN_BEFORE_D_SCORES' and
            prepared['source_lock'] == identity(c/'SOURCE_LOCK.json') and
            prepared['table_results_binding'] == identity(c/'TABLE_RESULTS_BINDING.json') and
            prepared['production_state_reads'] == 0 and prepared['future_freeze_created'] is False,
            'Final C source preparation/validation_group_10 schema association mismatch')
    for item in base_mapping['source_identities']:
        p = Path(item['path'])
        require(p.is_relative_to(project) and p.suffix in ('.py','.md','.sh') and
                not FORBIDDEN.intersection(part.lower() for part in p.relative_to(project).parts),
                'Base mapping identity is not a permitted source')
        require(identity(p) == item, 'Base mapping source identity drift')
    return dict(schema=SCHEMA, state=STATE, contract=contract,
        root_mapping=base_mapping, root_mapping_sha256=mapping_sha256(base_mapping),
        consumer_task_revision=revision, consumer_metadata=metadata,
        consumer_tested_sources=tested_identities, consumer_final_review=final,
        consumer_review_inventory=reviews, scientific_eligibility_changed=False,
        production_state_reads=0, production_commands_run=0, production_lock_probes=0,
        actual_publication_identities_created=False)


def verify_final_mapping(path=HERE/'FINAL_ROOT_MAPPING.json', *, project=PROJ):
    value = read(path)
    require(value == record_final_mapping(value['root_mapping'], project=project),
            'Final source/mapping drift; cannot refresh or silently substitute')
    return value


def runtime_mapping(base_mapping=None, *, receipt_path=HERE/'FINAL_ROOT_MAPPING.json', project=PROJ):
    value = verify_final_mapping(receipt_path, project=project)
    if base_mapping is None:
        from forecast_inputs import root_mapping_contract
        base_mapping = root_mapping_contract()
    require(value['root_mapping'] == base_mapping, 'Current frozen mapping provider drift')
    return value['root_mapping']


def refresh(base_mapping, *, project=PROJ, out=HERE):

    require(os.getpriority(os.PRIO_PROCESS,0) == 20, 'Refresh requires nice20')
    out = Path(out).absolute()
    require(out == HERE or out.is_relative_to(Path('/private/tmp')), 'Refresh write escaped overlay or synthetic scratch')
    value = record_final_mapping(base_mapping, project=project)
    target = out/'FINAL_ROOT_MAPPING.json'
    payload = (json.dumps(value,indent=2,ensure_ascii=False,allow_nan=False)+'\n').encode()
    fd = os.open(target,os.O_WRONLY|os.O_CREAT|os.O_EXCL,0o444)
    with os.fdopen(fd,'wb') as f:
        f.write(payload); f.flush(); os.fsync(f.fileno())
    return value


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--source-refresh',action='store_true')
    args = parser.parse_args()
    require(args.source_refresh, 'Explicit source refresh required')
    require(os.environ.get('FORECAST_BINDING_SOURCE_MAPPING_REFRESH') == '1', 'Source-only mapping refresh')
    sys.path.insert(0,str(HERE.parent/'code'))
    from forecast_inputs import root_mapping_contract
    refresh(root_mapping_contract())
    print('Final validation_group_10 source mapping recorded; no freeze or production run')


if __name__ == '__main__':
    try:
        main()
    except (OSError,ValueError,RuntimeError,KeyError,TypeError) as exc:
        raise SystemExit('forecast_hashes notice_records MAPPING REFUSED: '+str(exc))
