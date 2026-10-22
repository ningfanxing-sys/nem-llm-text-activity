'Check source dependencies before reading numerical test inputs.'
import ast
import hashlib
import json
import math
import os
from pathlib import Path
from evaluator.validation import exact_identity, require
from forecast_metadata import reviewed_sources

HERE = Path(__file__).absolute().parent


def public_metadata(item, roots):
    exact_identity(item)
    path = Path(item['path'])
    require(path.resolve() == path and all(not x.is_symlink() for x in (path,*path.parents))
        and any(path.is_relative_to(r) for r in roots), 'Finite owner metadata root')
    require(not any(s.lower() in {'host_state','sealed','predictions','scores','run','evaluation'} for s in path.parts)
        and not path.name.upper().startswith(('SEAL_','SCORE_')), 'No production payload identity exception')
    data = path.read_bytes()
    require(len(data) == item['bytes'] and hashlib.sha256(data).hexdigest() == item['sha256'], 'Owner metadata drift')
    return json.loads(data)


def verify_dependencies():
    require(os.environ.get('SCORING_PHASE','prepare') == 'accept', 'Prepare cannot run acceptance preflight')
    bindings = json.loads((HERE/'DEPENDENCY_ACCEPTANCE_BINDINGS.pending.json').read_text())
    require(bindings.get('status') == 'OWNER_DELIVERED_INDEPENDENTLY_REVIEWED_SOURCE_CONTRACT',
            'WAIT: AF same-source clean acceptance + stable reviewed C source interface')
    AF = HERE.parent.parent/'forecast_hashes/statistics'
    C = HERE.parents[4]/'studies/batch_estimation/batch_checks/statistics'
    rows = reviewed_sources()
    observation=json.loads((HERE/'C_INTERFACE_SOURCE_OBSERVATION.json').read_text())
    require(observation.get('AF_snapshot_source_drift') == [],
            'C drift against AF reviewed snapshot: source repair/re-association/review required')
    c_pins=json.loads((AF/'C_INTERFACE_SOURCE_PINS.json').read_text())['files']
    for item in c_pins.values():
        exact_identity(item);path=Path(item['path'])
        require(path.is_relative_to(C) and path.resolve()==path and not path.is_symlink(),
                'Exact finite C source root')
        data=path.read_bytes()
        require(len(data)==item['bytes'] and hashlib.sha256(data).hexdigest()==item['sha256'],
                'C drift against AF reviewed snapshot; no identity waiver')
    acceptance = public_metadata(bindings['AF_clean_receipt'], [AF])
    spec = json.loads((AF/'SCIENTIFIC_ACCEPTANCE_SPEC.json').read_text())
    node_source = rows['science_contract.py']
    data = Path(node_source['path']).read_bytes()
    require(len(data) == node_source['bytes'] and hashlib.sha256(data).hexdigest() == node_source['sha256'],
            'AF receipt predicate identity drift')
    nodes = [n for n in ast.parse(data).body if isinstance(n,ast.FunctionDef)
             and n.name in {'require','resource_receipt','clean_receipt'}]
    require(len(nodes) == 3, 'Exact AF clean-receipt helper closure')
    namespace = {'math':math}
    exec(compile(ast.Module(body=nodes,type_ignores=[]),node_source['path'],'exec'),namespace)
    namespace['clean_receipt'](acceptance, schema='AF_SCORING_SOURCE_ONLY_ACCEPTANCE_V1',
        revision='AF9_statistics_V3', sources=rows, test_ids=spec['test_ids'])
    contract = public_metadata(bindings['C_source_interface'], [C,AF])
    require(contract.get('stable') is True and contract.get('owner_agreed') is True
        and contract.get('source_inventory_finalization_pending') is False, 'Stable agreed C source interface pending')
    require(bindings.get('source_accept_release') is True and
        bindings.get('reviewed_AF_source_pin') == hashlib.sha256((HERE/'AF9_REVIEWED_SOURCE_PINS.json').read_bytes()).hexdigest(),
        'Separate accept release and exact reviewed AF source association required')
    require(bindings.get('C_source_observation') == hashlib.sha256((HERE/'C_INTERFACE_SOURCE_OBSERVATION.json').read_bytes()).hexdigest(),
            'C source interface observation drift')
    observation=json.loads((HERE/'C_INTERFACE_SOURCE_OBSERVATION.json').read_text())
    for item in observation['sources'].values():
        exact_identity(item);data=Path(item['path']).read_bytes()
        require(len(data)==item['bytes'] and hashlib.sha256(data).hexdigest()==item['sha256'],
                'C source drift; repair/review before notice_delays acceptance')
    return {'source_dependencies_ready':True,'production_authority':False,'actual_T5_grant':False}
