'Assemble checked numerical records for the result tables.'
from contextlib import contextmanager
from copy import deepcopy
from datetime import datetime, timezone
from functools import wraps
from pathlib import Path
import argparse, ast, json, os, sys

ROOT = Path(__file__).resolve().parents[1]
AP = ROOT.parent
PROJ = AP.parents[2]
sys.path.insert(0, str(AP/'code'))
import read_comparisons as P
from table_input_hash import FILL_ROOT, FILL_ROUND
import postscore_guards as G
CROOT = PROJ/'studies/batch_estimation/batch_checks'
DROOT = CROOT.parent/'disk_checks'
BROOT = CROOT.parent/'fitting'


def verify_pins():
    pins = P.strict_json(ROOT/'DEPENDENCY_PINS.json')
    for rel, digest in pins['files'].items():
        path = (PROJ/rel).resolve()
        P.require(path.is_relative_to(PROJ) and P.sha256(path) == digest, 'AP5 dependency drift: '+rel)
    from freeze_inference import verify_dependencies
    verify_dependencies(pins)
    return pins


@contextmanager
def consumer_scope():

    verify_pins()
    names = lambda n: n in ('table_results_conf_results','check_table_sources','freeze_table_results') or n.startswith('table_renderer')
    saved = {n:m for n,m in sys.modules.items() if names(n)}
    reference_snapshot = list(sys.path)
    for n in saved: del sys.modules[n]
    sys.path.insert(0,str(FILL_ROOT))
    try:
        f = P.load_module('table_results_conf_results',FILL_ROOT/'table_results_conf_results.py')
        sys.modules['table_results_conf_results'] = f
        yield f
        verify_pins()
    finally:
        for n in list(sys.modules):
            if names(n): del sys.modules[n]
        sys.modules.update(saved)
        sys.path[:] = reference_snapshot


def exact_t5(record, item):
    P.checked(item)
    P.require(record['timestamps']['T5']['files'].get(str(Path(item['path']).resolve())) == item['sha256'],
              'AP5 metadata exact path absent from T5')


def align_tables(record, plan):

    from table_renderer import table_bodies as T
    from table_renderer.table_headings import headings
    P.require(set(plan) == {'schema','tables'} and plan['schema'] == 'A8POST5_TABLE_PLAN_V1', 'AP5 typed table plan schema')
    P.require(set(plan['tables']) == set(T.TABLES)-set(T.PRIMARY), 'AP5 nine-table descriptor census')
    tables = {t['id']:t for t in record['source_tables']}
    P.require(len(record['source_tables']) == len(tables) == 12 and set(tables) == set(T.TABLES), 'AP5 twelve-table census')
    for name, table in tables.items():
        table['scientific_context'] = T.scientific_context(record,name)
        if name not in T.PRIMARY:
            cells = deepcopy(plan['tables'][name])
            P.require(isinstance(cells,list) and cells and all(isinstance(r,list) and r for r in cells), 'AP5 empty typed body')
            P.require(len({len(r) for r in cells}) == 1, 'AP5 rectangular typed body')
            P.require(all(isinstance(d,dict) and isinstance(d.get('kind'),str) for row in cells for d in row),
                      'AP5 typed descriptors required before consumer validation')
            table['body_cells'] = cells
            table['rows'] = [['']*len(r) for r in cells]
            table['spec'] = 'l'*len(cells[0])
        table['rows'] = T.expected_rows(record,table)
        table['caption'],table['header'] = headings(table,record)
    T.validate(record)
    return record


def coverage_plan(record, plan):

    from table_renderer import table_bodies as T
    result = deepcopy(plan)
    P.require(result.get('schema') == 'A8POST5_TABLE_PLAN_V1', 'AP5 coverage plan schema')
    for row in record['forest_rows']:
        if row['group'] == 'Primary': continue
        name = 'secondary_' + row['task']
        descriptor = dict(kind='pair', task=row['task'], arm=row['arm'], reference=row['ref'])
        probe = dict(id=name, scientific_context=T.scientific_context(record,name),
                     body_cells=[[descriptor]], rows=[['']])
        try: T.expected_rows(record,probe)
        except Exception as exc:
            if str(exc) in ('table body outside table scientific scope', 'table body contrast scope', 'table body pair reference'):
                continue
            raise
        cells = result['tables'][name]
        P.require(bool(cells) and all(isinstance(r,list) and r for r in cells), 'AP5 coverage body shape')
        if any(cell==descriptor for raw in cells for cell in raw):continue
        width = max(2,len(cells[0]))
        P.require(len({len(r) for r in cells}) == 1, 'AP5 coverage body rectangular')
        if len(cells[0]) < width:
            for raw in cells: raw.extend([dict(kind='label',value='')]*(width-len(raw)))
        cells.append([descriptor,dict(kind='label',value='descriptive only')]
                     +[dict(kind='label',value='') for _ in range(width-2)])
    return result


def assemble_hooks(record, *, anchor_inputs=None, deviations=None, synthetic=False):

    from table_renderer import forecast_binding as A, deviation_hook as D
    result = deepcopy(record)
    if anchor_inputs is not None:
        P.require(set(anchor_inputs) == {'native_identity','eligibility_identity','specification3_identity'}, 'AP5 anchor input roles')
        if not synthetic:
            P.require(all(P.checked(i).is_relative_to(PROJ) for i in anchor_inputs.values()), 'AP5 production anchor metadata must be project-owned')
        side = dict(schema='TABLE_RESULTS_ANCHOR_SIDECAR_V1',synthetic_only=False,**deepcopy(anchor_inputs),claim_cap={})
        result['forecast_binding'] = side
        native = A.native(result,production=not synthetic)
        side['claim_cap'] = A.derive_cap(result,native)
        A.validate(result,production=not synthetic)
    if deviations is not None:
        P.require(isinstance(deviations,dict), 'AP5 final deviation shape')
        result['deviation_table'] = deepcopy(deviations)
        D.validate(result,production=not synthetic)
    P.require(result['tasks'] == record['tasks'] and result['specified_reading_2000'] == record['specified_reading_2000']
              and result['specified_reading_n0'] == record['specified_reading_n0'], 'AP5 changed specified reading')
    return result


def not_run_reading(record, authority_item, *, synthetic=False):

    from table_renderer import forecast_binding as A
    a=P.strict_json(P.checked(authority_item))
    P.require(synthetic or Path(authority_item['path']).resolve().is_relative_to(PROJ), 'AP5 NR timestamp_checks must be project-owned')
    P.require(a.get('schema')=='A8POST5_NOT_RUN_AUTHORITY_V1' and a.get('state')=='INDEPENDENT_NOT_RUN_VERIFIER_PASS'
              and a.get('independent') is True and bool(a.get('verified_by')), 'AP5 independent NR timestamp_checks required')
    P.require(a.get('specified_source_receipt_sha256')==record['identities']['source_receipt_sha256']
              and a.get('specified_task_sha256')==A.task_hash(record['tasks']['notice']), 'AP5 NR specified association')
    P.require(P.utc(a['verified_utc'])>=P.utc(record['human_review']['score_utc']), 'AP5 NR verification follows scoring')
    identities=deepcopy(a['identities'])
    required={'original_seal_sha256','specified_prediction_view_sha256','specified_parity_sha256','scorer_freeze_sha256','T5_sha256'}
    P.require(set(identities)==required and all(__import__('re').fullmatch('[0-9a-f]{64}',v or '') for v in identities.values()), 'AP5 NR identity census')
    identities.update(dict.fromkeys(('corrected_seal_sha256','corrected_prediction_view_sha256','corrected_parity_sha256')))
    P.require(P.sha256(A.COUNT_SOURCE)==A.COUNT_SOURCE_SHA,'AP5 NR source count identity')
    return dict(schema='FORECAST_BINDING_READING_V1',state='NOT_RUN_BEFORE_SCORING',scope=deepcopy(A.SCOPE),
        specified_source_receipt_sha256=record['identities']['source_receipt_sha256'],specified_task_sha256=A.task_hash(record['tasks']['notice']),
        counts=deepcopy(A.COUNTS),count_source_sha256=A.COUNT_SOURCE_SHA,discovery='2026-10-05 05:53–06:10 AEDT before any score',
        secondary_reading='AS_RUN',corrected_task=None,reason='not run before scoring',bootstrap=None,
        identities=identities,source_functions=deepcopy(A.FUNCTION_SOURCES))


def reader_permission(parity, tasks=('news','notice')):
    P.require(isinstance(parity,dict) and tasks and set(tasks) <= {'news','notice'}, 'AP5 applicable parity tasks')
    P.require(all(isinstance(parity.get(t),dict) and parity[t].get('state') == 'PASS' for t in tasks),
              'STOP ordinary numeric readers: applicable SCORING_PARITY is not PASS')
    return dict(schema='A8POST5_READER_PERMISSION_V1',tasks=list(tasks),state='PASS',rc0_is_not_permission=True)


def ordinary_reader_gate(item=None, tasks=('news','notice'), *, synthetic=False):
    item=item or P.identity(DROOT/'state/scoring/SCORING_PARITY.json')
    P.require(synthetic or Path(item['path']).resolve()==DROOT/'state/scoring/SCORING_PARITY.json',
              'AP5 parity timestamp_checks must be D scoring root')
    permission=reader_permission(P.strict_json(P.checked(item)),tasks)
    permission['parity_identity']=deepcopy(item)
    return permission


def assembly_function(producer=None):

    tree = ast.parse((AP/'code/read_comparisons.py').read_text())
    fn = next(n for n in tree.body if isinstance(n,ast.FunctionDef) and n.name == 'assemble_output')
    slots = [i for i,n in enumerate(fn.body) if isinstance(n,ast.Assign) and any(isinstance(t,ast.Name) and t.id == 'caps' for t in n.targets)]
    P.require(len(slots) == 1, 'AP5 assembly injection point drift')
    exports={}
    fn.body[slots[0]:slots[0]] = ast.parse('_ap5_exports.update(_ap5_align(record, inputs, current, bundles))\n').body
    ns = dict(vars(producer or P),_ap5_align=align_from_context,_ap5_exports=exports)
    exec(compile(ast.set_missing_locations(ast.Module(body=[fn],type_ignores=[])),str(AP/'code/read_comparisons.py'),'exec'),ns)
    original=ns['assemble_output']
    @wraps(original)
    def assembled(*args,**kwargs):
        exports.clear()
        record,evidence=original(*args,**kwargs)
        evidence['nonprimary_supplement']=deepcopy(exports)
        return record,evidence
    return assembled


def prescore_base_plan(item):
    plan=P.strict_json(P.checked(item))
    expected={'combinations','cheap','secondary_news','secondary_notice','sensitivities','diagnostics','clipping_news','clipping_notice','execution'}
    P.require(set(plan)=={'schema','tables'} and plan['schema']=='A8POST5_TABLE_PLAN_V1'
              and isinstance(plan['tables'],dict) and set(plan['tables'])==expected,'AP5 static base table plan schema')
    for body in plan['tables'].values():
        P.require(isinstance(body,list) and body and all(isinstance(row,list) and row for row in body)
                  and len({len(row) for row in body})==1,'AP5 static base table plan shape')
        for row in body:
            for cell in row:
                P.require(isinstance(cell,dict) and isinstance(cell.get('kind'),str),'AP5 static base typed descriptor')
                P.require(cell['kind'] not in ('forest_pair','forest_native'),'AP5 POSTscore expanded descriptors cannot be prescore T5 plan')
    return plan


def align_from_context(record, inputs, current, bundles):
    item = inputs['context'].get('table_plan')
    P.require(isinstance(item,dict), 'AP5 requires explicit table_plan in existing context role')
    exact_t5(record,item)
    base=coverage_plan(record,prescore_base_plan(item))
    import supplement as S
    native=S.native_supplement(record,current,bundles)
    primary=record['tasks']['news']['contrasts'][0]['native_primary']['timestamp_checks']
    root=P.checked(primary).parent/'nonprimary_supplement'
    P.require(root.resolve().is_relative_to(AP) or root.resolve().is_relative_to(Path('/private/tmp')),
              'AP5 postscore supplement metadata destination')
    root.mkdir(exist_ok=False)
    native_path=root/'NATIVE_SUPPLEMENT.json';exclusive(native_path,native)
    native_item=P.identity(native_path)
    requested=S.requested_plan(record,base,native_item)
    plan_path=root/'TABLE_PLAN_POSTSCORE.json';exclusive(plan_path,requested)
    from table_renderer import table_bodies as T
    probe=dict(kind='forest_pair',identity=native['rows'][0]['identity']) if native['rows'] else None
    route=probe is None
    if probe is not None:
        try:T.cell(record,probe);route=True
        except (ValueError,RuntimeError) as error:
            P.require(str(error)=='table body unsupported kind','AP5 consumer forest route failed: '+str(error))


    align_tables(record,requested if route else base)
    return dict(native_authority=native_item,expanded_table_plan=P.identity(plan_path),
                prescore_base_plan=item,consumer_route_accepted=route,
                source_receipt_sha256=record['identities']['source_receipt_sha256'],
                postscore_only=True,nonprimary_rows=len(native['rows']))


@contextmanager
def specified_scope(f, producer=None):

    from unittest.mock import patch
    import freeze_inference as legacy_freeze
    import freeze_table_inputs as new_freeze
    producer = producer or P
    old = producer.dependencies
    def dependencies(consumer=True):
        verified = old(consumer=False)
        return (*verified[:4],f if consumer else None)
    def own_verify(path):
        P.require(Path(path).resolve() == AP/'A8POST_CODE_FREEZE.json', 'Unexpected legacy freeze request')
        return new_freeze.verify(ROOT/'A8POST5_CODE_FREEZE.json')
    with patch.object(producer,'CONSUMER_MS',FILL_ROOT),patch.object(producer,'dependencies',dependencies),\
         patch.object(producer,'assemble_output',assembly_function(producer)),patch.object(legacy_freeze,'verify',own_verify):
        yield


def bound_record(receipt_item):
    receipt = P.strict_json(P.checked(receipt_item))
    P.require(receipt.get('state') == 'A8_POSTSCORE_COMPLETE', 'AP5 specified receipt incomplete')
    outputs = receipt.get('outputs',[])
    P.require(len(outputs) == 2 and {Path(i['path']).name for i in outputs} == {'A8_POSTSCORE.json','A8_POSTSCORE_EVIDENCE.json'}, 'AP5 specified output census')
    data = {Path(i['path']).name:P.strict_json(P.checked(i)) for i in outputs}
    record,evidence = data['A8_POSTSCORE.json'],data['A8_POSTSCORE_EVIDENCE.json']
    P.require(record['identities']['source_receipt_sha256'] == evidence['inputs']['score_receipt']['sha256'], 'AP5 score-source association')
    G.validate_official_score(evidence['inputs'],record['identities']['source_receipt_sha256'],P=P)
    return record,evidence


def mapped_roles(items):

    required = {'seal','score_receipt','score_report','a2','a3','a4','batch','batch_seal','dly_seal','clk8',
                'author','author_prescore','timestamps','human_review','repins','context','specification2','hrc_review','hrc_agreement','author_a3_a6'}
    optional = {'pc','pcx','a2batch','a2batch_receipt','label','label_receipt','kcx','check_window_inputs','cps8_selection','cps8_selection_receipt'}
    P.require(required <= set(items) <= required|optional, 'AP5 closed specified V2 role census')
    paths = {'batch':DROOT/'state/scoring/A8BATCH_POSTSCORE_INPUTS.json',
             'batch_seal':DROOT/'state/SEAL_BATCH.json','check_window_inputs':DROOT/'state/R8_ADMISSION.json',
             'cps8_selection':CROOT/'CPS8_METADATA.json','cps8_selection_receipt':CROOT/'CPS8_METADATA.receipt.json'}
    for role,path in paths.items():
        if role in items: P.require(Path(items[role]['path']).resolve() == path, 'AP5 consumer/D role path: '+role)
    P.require(Path(items['dly_seal']['path']).resolve() in (DROOT/'dly8/DELAY_FORECAST_SEAL.json',DROOT/'dly8/DLY8_SEAL_R8.json'), 'AP5 DLY outer seal root')
    for item in items.values(): P.checked(item)
    return dict(schema='A8POST_INPUTS_V2',synthetic=False,inputs=deepcopy(items))


def timestamp_projection(raw):

    P.require(set(raw)=={'schema','records'} and raw.get('schema') == 'A8POST5_TRUSTED_TIMESTAMP_FIELDS_V1', 'AP5 timestamp field schema')
    result={}
    P.require({'T4','T4A','T4B','T5'}<=set(raw['records']) and all(__import__('re').fullmatch('T[0-5][A-Z]*',k) for k in raw['records']), 'AP5 timestamp label census')
    for label in raw['records']:
        r=raw['records'][label]
        P.require(r.get('tsa_trust_verified') is True and r.get('binding_verified') is True, 'AP5 unverified timestamp fields')
        P.utc(r['utc'])
        for item in r['files']: P.checked(item)
        P.require(len({i['path'] for i in r['files']}) == len(r['files']), 'AP5 duplicate timestamp identity')
        result[label]=dict(utc=r['utc'],files={i['path']:i['sha256'] for i in r['files']})
    baseline=[P.utc(result[k]['utc']) for k in ('T4','T4A','T4B','T5')]
    P.require(baseline==sorted(baseline), 'AP5 timestamp order')
    P.require(all(P.utc(v['utc'])<=P.utc(result['T5']['utc']) for k,v in result.items() if k!='T5'),
              'AP5 prior timestamp label follows T5')
    return result


def exclusive(path, value):
    path = Path(path)
    P.require(not path.exists() and path.parent.exists(), 'AP5 refuses overwrite/missing parent')
    with path.open('x') as stream:
        json.dump(value,stream,indent=2,ensure_ascii=False,allow_nan=False);stream.write('\n')
    return P.identity(path)


def cutoff_snapshot(raw, observed_utc):

    return G.cutoff_snapshot(raw,observed_utc,P=P)


def later_manifest(raw):
    parent=P.strict_json(P.checked(raw['parent_manifest']))
    P.require(parent.get('schema')=='A8POST_INPUTS_V2','AP5 later parent schema')
    for name in ('seal','score_receipt','score_report'):
        P.require(raw['inputs'][name]==parent['inputs'][name],'AP5 refill changed official confirmation source: '+name)
    official=G.validate_official_score(raw['inputs'],P=P)
    snapshot=P.strict_json(P.checked(raw['cutoff_snapshot']))
    P.require(snapshot.get('official_score')==official,'AP5 cutoff/official score association mismatch')
    P.require(snapshot.get('schema')=='A8POST5_CUTOFF_IDENTITIES_V1'
              and P.utc(snapshot['cutoff_utc'])==P.fill_cutoff(raw['fill_clock'],refill=True), 'AP5 cutoff snapshot association')
    P.require(snapshot.get('state')=='OUTCOME_BLIND_IDENTITY_OBSERVATION' and snapshot.get('pending_is_negative') is False
              and snapshot.get('source_values_decoded') is False, 'AP5 genuine identity-only snapshot required')
    lateness=(P.utc(snapshot['observed_utc'])-P.utc(snapshot['cutoff_utc'])).total_seconds()
    P.require(lateness>=0 and snapshot['capture_lateness_seconds']==lateness
              and snapshot['exact_cutoff_observation'] is (lateness==0), 'AP5 cutoff observation clock mismatch')
    P.require(len({i['path'] for i in snapshot['files']})==len(snapshot['files']), 'AP5 snapshot duplicate identity')
    for item in snapshot['files']:P.checked(item)
    embedded='capture_authority' in snapshot or 'capture_authority_kind' in snapshot
    if embedded:
        P.require('late_snapshot_authority' not in raw,'Ambiguous late capture authorities on refill')
        P.require('capture_authority' in snapshot and snapshot.get('capture_authority_kind')
                  in ('INDEPENDENT_DISCLOSED_DEVIATION','scoring_callback'),
                  'Late cutoff lacks embedded accepted capture timestamp_checks')
        G.validate_embedded_capture(snapshot,official,raw['fill_clock'],P=P)
    elif snapshot.get('exact_cutoff_observation') is not True:
        timestamp_checks=raw.get('late_snapshot_authority')
        P.require(isinstance(timestamp_checks,dict),'AP5 late snapshot needs independent disclosed timestamp_checks')
        a=P.strict_json(P.checked(timestamp_checks))
        P.require(a.get('schema')=='A8POST5_LATE_SNAPSHOT_AUTHORITY_V1' and a.get('state')=='INDEPENDENT_DISCLOSED_DEVIATION_ACCEPTED'
                  and a.get('independent') is True and bool(a.get('verified_by')) and a.get('snapshot_identity')==raw['cutoff_snapshot']
                  and a.get('no_historic_byte_claim') is True, 'AP5 late snapshot timestamp_checks mismatch')
    m=mapped_roles(raw['inputs']);m['refill']=True

    for name in ('seal','score_receipt','score_report'):
        P.require(m['inputs'][name]==parent['inputs'][name], 'AP5 refill changed official confirmation source: '+name)
    for name in ('a3','a4','context'):
        P.require(m['inputs'][name]!=parent['inputs'][name], 'AP5 refill requires fresh '+name)
    m['later_inputs']=deepcopy({k:raw[k] for k in ('cutoff_snapshot','parent_manifest','fill_clock','late_snapshot_authority') if k in raw})
    return m


def prescore_metadata_gate(manifest):

    f=__import__('freeze_table_inputs').verify(ROOT/'A8POST5_CODE_FREEZE.json')
    times=P.strict_json(P.checked(manifest['inputs']['timestamps']))
    files=times['T5']['files']
    required=[P.identity(ROOT/'A8POST5_CODE_FREEZE.json')]
    required += [dict(path=str(AP/rel),sha256=digest) for rel,digest in f['files'].items()]
    required += [dict(path=str(PROJ/rel),sha256=digest) for rel,digest in verify_pins()['files'].items()]
    P.require(all(files.get(i['path'])==i['sha256'] for i in required),'AP5 exact T5 source coverage missing')
    P.require(P.utc(f['frozen_utc'])<P.utc(times['T5']['utc']),'AP5 source freeze must precede T5')
    context=P.strict_json(P.checked(manifest['inputs']['context']))
    plan=context.get('table_plan')
    P.require(isinstance(plan,dict) and files.get(plan.get('path'))==plan.get('sha256'),'AP5 exact T5 table plan missing')
    prescore_base_plan(plan)
    if manifest.get('refill'):
        later=manifest.get('later_inputs');P.require(isinstance(later,dict),'AP5 refill lacks later-input binding')
        rebuilt=later_manifest(dict(later,inputs=manifest['inputs']))
        P.require(rebuilt['later_inputs']==later, 'AP5 refill binding changed')


def input_schema(raw,command):
    specs={
        'manifest':('A8POST5_MANIFEST_BINDINGS_V1',{'schema','inputs'},set()),
        'assemble':('A8POST5_ASSEMBLY_INPUTS_V1',{'schema','specified_receipt'},{'anchor_inputs','deviations','refill'}),
        'reader-gate':('A8POST5_READER_GATE_INPUTS_V1',{'schema','parity_identity'},{'tasks'}),
        'not-run':('A8POST5_NOT_RUN_INPUTS_V1',{'schema','specified_receipt','not_run_authority'},set()),
        'later-inputs':('A8POST5_LATER_INPUTS_V1',{'schema','inputs','fill_clock','parent_manifest','cutoff_snapshot'},{'late_snapshot_authority'})}
    if command in specs:
        schema,required,optional=specs[command]
        P.require(isinstance(raw,dict) and raw.get('schema')==schema and required<=set(raw)<=required|optional,'AP5 closed command input schema: '+command)
    return raw


@contextmanager
def associated():

    verify_pins()
    sys.path.insert(0,str(CROOT))
    import consumer_roots as C
    P.require(Path(C.__file__).resolve() == CROOT/'consumer_roots.py', 'AP5 wrong association module')
    P.require(C.ENTRIES['table_results_conf_results'] == str((FILL_ROOT/'table_results_conf_results.py').relative_to(PROJ)), 'STOP C is not reviewed '+FILL_ROUND)
    a = C.Association()
    a.release();a.ambiguity()
    with a.installed():
        a.source_delivery();a.verify_t5_coverage()
        for source in sorted((ROOT/'code').glob('*.py')): a.verify_code(source)


        a.load('read_comparisons')
        previous=globals()['P'];globals()['P']=sys.modules['read_comparisons']
        try:
            with a._consumer_execution('read_comparisons'):yield a
        finally:globals()['P']=previous


def main(argv=None):
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--production',action='store_true',required=True)
    sub=parser.add_subparsers(dest='command',required=True)
    for name in ('specified','assemble','manifest','timestamps','reader-gate','later-inputs','cutoff','not-run'):
        s=sub.add_parser(name);s.add_argument('--inputs',type=Path,required=True);s.add_argument('--inputs-sha256',required=True);s.add_argument('--out',type=Path,required=True)
    a=parser.parse_args(argv)
    try:
        P.require(os.getpriority(os.PRIO_PROCESS,0) == 20, 'AP5 requires actual nice20')
        P.resource_gate()
        import freeze_table_inputs as Z
        Z.verify(ROOT/'A8POST5_CODE_FREEZE.json')
        P.require(P.sha256(a.inputs)==a.inputs_sha256 and not a.out.exists(), 'AP5 input/output identity gate')
        with associated() as association:
            if a.command == 'specified':

                module=association.load('read_comparisons')
                prescore_metadata_gate(P.strict_json(a.inputs))
                permission=ordinary_reader_gate()
                with consumer_scope() as f, specified_scope(f,sys.modules['read_comparisons']):
                    record,evidence=module.build(a.inputs,a.inputs_sha256,production=True)
                    evidence['producer']=dict(producer=P.identity(Path(__file__)),consumer_root=str(FILL_ROOT))
                    evidence['reader_permission']=permission
                    module.write_output(a.out,record,evidence)
            else:
                raw=input_schema(P.strict_json(a.inputs),a.command)
                if a.command=='assemble':
                    record,evidence=bound_record(raw['specified_receipt'])
                    with consumer_scope() as f:
                        record=assemble_hooks(record,anchor_inputs=raw.get('anchor_inputs'),deviations=raw.get('deviations'))
                        f.validate_record(record)
                        from table_renderer.complete_fill import validate_complete_inputs
                        validate_complete_inputs(record,refill=raw.get('refill',False))
                    evidence=deepcopy(evidence);evidence['assembly_inputs']=P.identity(a.inputs)
                    association.load('read_comparisons').write_output(a.out,record,evidence)
                elif a.command=='manifest':exclusive(a.out,mapped_roles(raw['inputs']))
                elif a.command=='timestamps':exclusive(a.out,timestamp_projection(raw))
                elif a.command=='reader-gate':
                    exclusive(a.out,ordinary_reader_gate(raw['parity_identity'],tuple(raw.get('tasks',('news','notice')))))
                elif a.command=='cutoff':
                    value=cutoff_snapshot(raw,datetime.now(timezone.utc).isoformat())
                    value['clock_identity']=P.identity(a.inputs);exclusive(a.out,value)
                elif a.command=='not-run':
                    record,_=bound_record(raw['specified_receipt'])
                    with consumer_scope():exclusive(a.out,not_run_reading(record,raw['not_run_authority']))
                else:


                    exclusive(a.out,later_manifest(raw))
        print(json.dumps(dict(state='A8POST5_COMPLETE',command=a.command)))
        return 0
    except (P.Refusal,OSError,KeyError,ValueError,RuntimeError) as error:
        adverse=getattr(error,'cutoff_adverse',None)
        if adverse is not None:


            try:
                adverse['clock_identity']=P.identity(a.inputs)
                refusal=a.out.with_name(a.out.name+'.REFUSED.json')
                if not refusal.exists():exclusive(refusal,adverse)
            except (P.Refusal,OSError,ValueError) as evidence_error:
                print('A8POST5 adverse receipt retained in input; publication refused: '+str(evidence_error),file=sys.stderr)
        print('A8POST5 REFUSED: '+str(error),file=sys.stderr);return 2


if __name__=='__main__':sys.exit(main())
