'Check computation records against independently saved source identities.'
import ast
import datetime as dt
import hashlib
import json
from pathlib import Path
import stat

OBLIGATIONS = (
    'ap_scientific_inputs_and_author_validation',
    'ap_native_numeric_assembly',
    'rd_native_provenance_and_evaluator',
    'explicit_r2_dispatch_full214_before135',
    'original214_separate_attachment_every_branch',
    'optional_and_cached_helper_closure',
    'scientific_operational_history_and_refusals',
)

def identity(path):
    path=Path(path)
    if not path.is_absolute() or '..' in path.parts or any(x.is_symlink() for x in (path,*path.parents)) or not stat.S_ISREG(path.lstat().st_mode):
        raise ValueError('Unsafe identity path')
    blob=path.read_bytes()
    return dict(path=str(path),bytes=len(blob),sha256=hashlib.sha256(blob).hexdigest())

def _utc(value):
    value=dt.datetime.fromisoformat(value.replace('Z','+00:00'))
    if value.utcoffset()!=dt.timedelta(0):raise ValueError('Closure UTC required')
    return value

def _unique(values):
    if not isinstance(values,list) or not values or len(values)!=len(set(values)):
        raise ValueError('Empty/duplicate evidence census')
    return values

def _file(root,pin):
    if set(pin)!={'path','bytes','sha256'}:raise ValueError('Exact artifact identity required')
    raw=pin['path'];p=Path(raw)
    if not isinstance(raw,str) or not p.is_absolute() or str(p)!=raw or '..' in p.parts or not p.is_relative_to(root):
        raise ValueError('Artifact outside exact evidence root/alias')
    if any(x.is_symlink() for x in (p,*p.parents)) or not stat.S_ISREG(p.lstat().st_mode):
        raise ValueError('Artifact symlink/directory')
    blob=p.read_bytes()
    if len(blob)!=pin['bytes'] or hashlib.sha256(blob).hexdigest()!=pin['sha256']:
        raise ValueError('Closure artifact identity drift')
    return blob

def _json(root,pin):
    def pairs(rows):
        result={}
        for k,v in rows:
            if k in result:raise ValueError('Duplicate evidence key')
            result[k]=v
        return result
    return json.loads(_file(root,pin),object_pairs_hook=pairs,
                      parse_constant=lambda _:(_ for _ in ()).throw(ValueError('Nonfinite evidence')))

def boundary_evidence(test_pin,test,*,read_paths,executed_source_paths,declared_writing):

    writing_reads=sorted(p for p in read_paths if any(x in Path(p).parts for x in ('tables','REMOVED_WRITING_ROOT')))
    writing_imports=sorted(p for p in executed_source_paths if any(x in Path(p).parts for x in ('tables','REMOVED_WRITING_ROOT')))
    return dict(schema='C_SCORING_BOUNDARY_EXECUTION_EVIDENCE_V1',
                scope='C_BOUNDARY_PARITY_AND_UNIT_PREMISES_ONLY',
                test_receipt=test_pin,case_ids=test['case_ids'],delivered_sources=test['delivered_sources'],
                read_paths=sorted(read_paths),executed_source_paths=sorted(executed_source_paths),
                declared_writing=sorted(declared_writing),writing_runtime_reads=writing_reads,
                FILL_runtime_imports=writing_imports,full_numeric_chain=False,
                unit_premises=['R2 original-reader mock','artificial release/timestamp_checks fixtures',
                               'G42 interface counts are not native eligibility'],
                production_authority=False)

def verify(root,closure,test,spec,review):

    root=Path(root)
    if closure.get('schema')!='C_SCORING_SOURCE_CLOSURE_V2' or closure.get('state')!='INDEPENDENT_SCIENTIFIC_CHAIN_VERIFIED':
        raise ValueError('Full independently verified closure pending; old/bounded evidence refused')
    test_pin=identity(root/'SCIENTIFIC_ACCEPTANCE_RECEIPT.json')

    if _json(root,test_pin)!=test or test.get('schema')!='C_statistics_ACCEPTANCE_V1' or test.get('state')!='CLEAN_FULL_PASS':
        raise ValueError('Current clean receipt required')
    if any(test.get(k)!=[] for k in ('failures','errors','skipped')) or test.get('case_ids')!=spec['case_ids']:
        raise ValueError('Full current case census required')
    _unique(test['case_ids'])
    if closure.get('task_revision')!=test['task_revision'] or closure.get('test_receipt')!=test_pin or \
       closure.get('case_ids')!=test['case_ids'] or closure.get('delivered_sources')!=test['delivered_sources'] or \
       set(test['delivered_sources'])!=set(spec['tested_source_files']):
        raise ValueError('Closure receipt/case/source census drift')
    for name,pin in test['delivered_sources'].items():
        _file(root,dict(path=str(root/name),**pin))
    if closure.get('production_authority') is not False or closure.get('full_numeric_chain') is not True or \
       closure.get('writing_roots_unavailable') is not True or closure.get('FILL_runtime_imports')!=[] or \
       closure.get('writing_completion_gates')!=[]:
        raise ValueError('Writing dependency or invalid closure scope')
    trace=_json(root,closure['boundary_evidence'])
    if trace.get('schema')!='C_SCORING_BOUNDARY_EXECUTION_EVIDENCE_V1' or trace.get('full_numeric_chain') is not False or trace.get('scope')!='C_BOUNDARY_PARITY_AND_UNIT_PREMISES_ONLY' or \
       trace.get('test_receipt')!=test_pin or trace.get('case_ids')!=test['case_ids'] or \
       trace.get('delivered_sources')!=test['delivered_sources'] or any(trace.get(k)!=[] for k in ('declared_writing','writing_runtime_reads','FILL_runtime_imports')):
        raise ValueError('Actual current bounded execution artifact required')
    for field in ('read_paths','executed_source_paths'):
        for raw in _unique(trace[field]):
            path=Path(raw)
            if not path.is_absolute() or str(path)!=raw or '..' in path.parts:
                raise ValueError('Noncanonical observed execution/read path')
    relations=closure.get('owner_relations',{})
    if set(relations)!=set(OBLIGATIONS) or review.get('closure_relations')!=relations or \
       review.get('closure_boundary_evidence')!=closure['boundary_evidence'] or \
       review.get('independent') is not True or review.get('reviewer_role')!='C_REVIEWER' or review.get('verdict')!='ACCEPT':
        raise ValueError('Exact independent C adoption of all scientific relations required')
    for obligation,row in relations.items():
        if set(row)!={'acceptance','independent_review','execution','helpers','sources','specification'}:
            raise ValueError('Owner relation artifact census incomplete/extra')
        accepted=_json(root,row['acceptance']);owner_review=_json(root,row['independent_review'])
        execution=_json(root,row['execution']);helpers=_json(root,row['helpers']);sources=_json(root,row['sources']);owner_spec=_json(root,row['specification'])
        if accepted.get('schema')!='C_SCORING_OWNER_CHAIN_ACCEPTANCE_RELATION_V1' or accepted.get('state')!='CLEAN_FULL_PASS' or \
           accepted.get('obligation')!=obligation or accepted.get('c_test_receipt')!=test_pin or \
           accepted.get('c_delivered_sources')!=test['delivered_sources'] or accepted.get('artifacts')!={k:row[k] for k in ('execution','helpers','sources','specification')} or \
           any(accepted.get(k)!=[] for k in ('failures','errors','skipped')) or accepted.get('synthetic_only') is not True:
            raise ValueError('Independent same-version owner acceptance relation pending')
        cases=_unique(accepted['case_ids'])
        if owner_spec.get('schema')!='C_SCORING_OWNER_CHAIN_SPECIFICATION_V1' or owner_spec.get('obligation')!=obligation or \
           owner_spec.get('scope')!='FULL_NATIVE_SCIENTIFIC_OBLIGATION' or owner_spec.get('case_ids')!=cases or \
           owner_spec.get('public_sources')!=sources.get('files') or owner_spec.get('required_helpers')!=helpers.get('required_helpers'):
            raise ValueError('Exact full owner scientific specification/census/helper closure required')
        if owner_review.get('schema')!='C_SCORING_OWNER_CHAIN_INDEPENDENT_REVIEW_V1' or \
           owner_review.get('independent') is not True or owner_review.get('verdict')!='ACCEPT' or \
           owner_review.get('reviewer_role') not in ('C_REVIEWER','INDEPENDENT_SCIENTIFIC_REVIEWER') or \
           not isinstance(owner_review.get('reviewed_by'),str) or not owner_review['reviewed_by'].strip() or \
           owner_review['reviewed_by']==accepted.get('producer') or owner_review.get('acceptance')!=row['acceptance'] or \
           owner_review.get('artifacts')!=accepted['artifacts'] or _utc(owner_review['reviewed_utc'])<_utc(accepted['utc']) or \
           _utc(review['reviewed_utc'])<_utc(owner_review['reviewed_utc']) or _utc(accepted['utc'])<_utc(test['utc']):
            raise ValueError('Producer self-certification/owner review identity or chronology drift')
        if execution.get('schema')!='C_SCORING_OWNER_EXECUTION_EVIDENCE_V1' or execution.get('case_ids')!=cases or \
           execution.get('writing_runtime_reads')!=[] or execution.get('FILL_runtime_imports')!=[] or \
           execution.get('writing_completion_gates')!=[] or execution.get('writing_roots_unavailable') is not True:
            raise ValueError('Owner full execution without writing roots required')
        if sources.get('schema')!='C_SCORING_OWNER_PUBLIC_SOURCE_EVIDENCE_V1' or not sources.get('files') or \
           helpers.get('schema')!='C_SCORING_OWNER_HELPER_CLOSURE_V1' or not helpers.get('required_helpers') or \
           execution.get('source_manifest')!=row['sources'] or execution.get('helper_inventory')!=row['helpers']:
            raise ValueError('Executed source/helper closure missing')
        blobs={name:_file(root,pin) for name,pin in sources['files'].items()}
        helper_rows=helpers['required_helpers'];keys=[(x['source'],x['line'],x['name']) for x in helper_rows]
        if len(keys)!=len(set(keys)):raise ValueError('Duplicate helper obligation')
        calls=execution.get('helper_calls',[])
        if not calls or len({(x['source'],x['line'],x['name']) for x in calls})!=len(calls):raise ValueError('Missing/duplicate executed helpers')
        for helper in helper_rows:
            name=helper['source']
            if name not in blobs or not name.endswith('.py'):raise ValueError('Unverified helper source')
            node=next((n for n in ast.walk(ast.parse(blobs[name])) if isinstance(n,(ast.FunctionDef,ast.AsyncFunctionDef)) and n.lineno==helper['line'] and n.name==helper['name']),None)
            if node is None or hashlib.sha256(ast.dump(node,include_attributes=False).encode()).hexdigest()!=helper['ast_sha256']:
                raise ValueError('Required helper AST identity drift')
            call=next((x for x in calls if all(x.get(k)==helper[k] for k in ('source','line','name'))),None)
            if call is None or call.get('calls',0)<1 or call.get('source_identity')!=sources['files'][name] or not set(_unique(call['case_ids']))<=set(cases):
                raise ValueError('Required helper not executed in accepted source/case closure')
        if execution.get('executed_sources')!=sources['files'] or not execution.get('read_evidence'):
            raise ValueError('Complete actual source/read evidence required')
        for observation in execution['read_evidence']:
            if observation.get('origin') not in ('PUBLIC_SOURCE','ARTIFICIAL_FIXTURE') or not observation.get('identity') or not set(_unique(observation['case_ids']))<=set(cases):
                raise ValueError('Unscoped/non-artificial read evidence')


            if observation['origin']=='PUBLIC_SOURCE' and observation['identity'] not in sources['files'].values():
                raise ValueError('Read source outside independently accepted census')
        if any(doc.get(k)!=0 for doc in (accepted,owner_review,execution) for k in ('production_state_reads','production_commands_run')):
            raise ValueError('Non-source-only owner evidence')
    return dict(state='INDEPENDENT_SCIENTIFIC_CHAIN_VERIFIED',production_authority=False,freeze_permitted=False)
