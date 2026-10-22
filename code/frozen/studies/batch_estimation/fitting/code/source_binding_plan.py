"""Pre-T4B launcher plan; future freeze bytes live in a separate T5 association."""
from a8_common import *

PYTHON = str(PROJ.parents[1]/'.venv/bin/python')

def expected_plan():
    label=Q/'A2LABEL/REPIN_CONFX8';pcx=CONF/'A4/PCX/REPIN_CONFX8'
    return dict(schema='A8_REPIN_PLAN_V1',association_path=str(OUT/'POSTSCORE_REPIN_ASSOCIATION.json'),
        seal_association_path=str(OUT/'PCX_SEAL_ASSOCIATION.json'),
        execution_root=str(OUT),steps={
        'A2LABEL':dict(stage=str(label),argv=[PYTHON,'-B',str(label/'a2label_turn.py'),'--execute','--state',str(ADAPTER/'host_state')]),
        'PC':dict(stage=str(pcx),argv=[PYTHON,'-B',str(OUT/'code/pcx_turn.py'),'--execute','--phase','base']),
        'PCX_extension':dict(stage=str(pcx),argv=[PYTHON,'-B',str(OUT/'code/pcx_turn.py'),'--execute','--phase','extension'])},
        freezes_by_T5=[str(Q/r/'REPIN_CONFX8/REPIN_FREEZE.json') for r in ('CONF/A4/PCX','A2LABEL')],
        arxiv_fit_turns=['A2LABEL','PC','PCX_extension'],journal_only=['ISOBATCH','A2BATCH'])

def mutable_repin_path(path):
    path=Path(path).resolve()
    return (Q/'REPIN8').resolve() in path.parents or 'REPIN_CONFX8' in path.parts

def plan_files():
    # Stable command patterns are batch inputs; REPIN8 bytes bind only at T5.
    return []

def validate_plan(binding):
    plan=binding.get('repin_launch_plan',{})
    require(plan==dict(expected_plan(),files=[]),'Exact pre-freeze REPIN8 argv/identity plan required')
    require(not any(mutable_repin_path(i['path']) for i in binding.get('input_files',[])),
            'Mutable REPIN8 bytes cannot be batch-start inputs; bind at T5')
    from runner import fitting_argv
    for row in plan['steps'].values():require(fitting_argv(row['argv']), 'A8 cannot see declared launcher argv')
    return []

def validate_effective(binding):
    validate_plan(binding)
    plan=binding['repin_launch_plan'];path=Path(plan['association_path']);value=read_json(path)
    require(value.get('state')=='A8_REPIN_ASSOCIATION_VERIFIED' and value.get('coordinator_verified') is True,'Separate reviewed post-score association required')
    require(value.get('batch_freeze')==identity(OUT/'CODE_FREEZE.json'),'Re-pin association/batch freeze drift')
    files=value['files'];steps=value['steps']
    require(set(steps)=={'A2LABEL','KCX','PC','PCX_extension'},'Effective turn inventory drift')
    for item in files:checked(item)
    for name,row in plan['steps'].items():
        actual=steps[name]
        require(actual['argv']==row['argv'] and actual['repin_verified'] is True and actual['authorised'] is True,'Effective re-pin argv drift: '+name)
        require(all(i in files for i in actual['bindings']),'Effective step bindings absent')
        freeze=identity(Path(row['stage'])/'REPIN_FREEZE.json')
        require(freeze in actual['bindings'],'Effective stage freeze not bound: '+name)
    require(steps['KCX'].get('authorised') is False,'R6: KCX is not run')
    require(all(identity(p) in files for p in plan['freezes_by_T5']),'PCX and A2LABEL freezes required; ISO/A2 deferred under A8.13')
    # Actual re-pin authority, never a coordinator boolean standing in for verification.
    sys.path.insert(0,str(Q/'REPIN8'))
    import binding as repin
    for p in plan['freezes_by_T5']:
        receipt=repin.verify_repin(Path(p).parent,full=True)
        require(all(i in files for i in receipt['delivery_files']),
                'T5 association must bind verified re-pin delivery bytes')
    # Use the frozen batch predicate, with stable patterns; no mutable overlap import.
    from runner import fitting_argv
    for name in plan['steps']:
        require(fitting_argv(steps[name]['argv']),'Effective launcher not visible: '+name)
    seal_path=Path(plan['seal_association_path']);seal=read_json(seal_path)
    require(seal.get('state')=='PCX_SEAL_ASSOCIATION_VERIFIED' and seal.get('coordinator_verified') is True,'Reviewed PCX seal-only association required')
    attestation=seal['seal_attestation'];checked(attestation)
    require(identity(seal_path) in files and attestation in files,'PCX seal-only identities absent from T5 association')
    return [identity(path),*files,*plan['files']]

def effective_steps(binding):
    validate_effective(binding)
    return read_json(binding['repin_launch_plan']['association_path'])['steps']
