'Check the complete forecast source inventory statically.'
from pathlib import Path
import json
from forecast_check_helpers import checked, document, metadata_path, row, unresolved_value, unresolved_values

CHAIN_FIELDS = {
 'c-v1-time_alignment-closure': (('evidence',),('closure','receipt')),
 'freeze-science': (('inventory','source_review','c'),('science_freeze','c_freeze','receipt')),
 'freeze-science-addendum': (('original_receipt','science_freeze','history','decision','inventory','changes','source_review'),('addendum','receipt')),
 'c-v1-association': (('science_freeze',),('receipt',)),
 'af-mapping-refresh': (('science_freeze',),('mapping','receipt')),
 'af-final-source-publish': (('science_freeze',),('commitment','receipt')),
 'am3-source-freeze': (('science_freeze','contract','payloads','source_acceptance','part_b','attestation'),('am3_freeze','receipt')),
 'af-source-freeze': (('science_freeze','am3_freeze','review_acceptance','consumer_acceptance','attestation'),('receipt',)),
 't4g-create-verify-bind': (('science_freeze','am3_freeze','af_freeze','description'),('am3_binding','af_union_binding','receipt')),
 'af-execute': (('activation','am3_t4g'),('receipt',)),
 'verify-seal': (('am3_t4g',),('receipt',)),
 't5-inventory': (('source_files','metadata_files','corrected_verification','am3_t4g','author_hrc'),('inventory','closure')),
 'scoring': ((),()),
}
OWNER_HINTS = {
 'source_review': 'Scoped final reviewer: three questions on actual primary_tests build/inventory',
 'review_acceptance': 'AFREV8B: actual AF independent Part B acceptance after mapping/publication',
 'consumer_acceptance': 'AFCONSACC: same-source scientific C/AF consumer acceptance',
 'source_acceptance': 'AM3DLE: same final contract source acceptance',
 'part_b': 'AM3REV4B: independent D1-D3 Part B',
 'contract': 'AM3DLE: actual supplied-byte contract after both real AF acceptances',
 'attestation': 'CLERK under delegation: actual same-source attestation and terminal/quiet evidence',
 'permit': 'CLERK/source: separate real action permit',
 'quiet_host_disposition': 'CLERK/source: real procedural quiet disposition',
 'quiet_host': 'CLERK/source: real procedural quiet disposition',
 'activation': 'AF9/CLERK: actual AF activation after source releases',
 'author_hrc': 'Source: existing author/HRC permit evidence, independently obtained without protected reads',
 'release': 'Source: real scoring release and capture-clock authorization',
}


def unresolved(v, trail='$'):
    yield from unresolved_values(v, trail)


def inspect(control, action, sources=None, *, build=None, catalog=None, inventory=None, c61=None):

    blockers=[]; deferred=[]
    aliases={}
    here=Path(__file__).absolute().parent
    if sources is None and control.get('project')==str(here.parents[3]):
        selected=json.loads((here/'AF_CHAIN_SOURCES.json').read_bytes())
        aliases={str(here.parents[3]/r['logical_path']):dict(path=str(here.parents[3]/r['path']),bytes=r['bytes'],sha256=r['sha256']) for r in selected['files']}
    def issue(field, reason, kind='A_OWNER_ACT', owner=None):
        blockers.append(dict(field=field,classification=kind,reason=reason,owner=owner or OWNER_HINTS.get(field.rsplit('.',1)[-1],'CLERK: real release inputs/owner evidence')))
    if action not in CHAIN_FIELDS:
        issue('action','Unsupported action','A_INTERFACE_ERROR');return blockers,deferred
    expected = CHAIN_FIELDS[action]
    keys = ('schema','project','driver_build','release','t5','quiet_host','sources') if action=='scoring' else ('schema','action','project','build','source_catalog','permit','quiet_host_disposition','inputs','outputs')
    for key in keys:
        if key not in control: issue(key,'Required CONTROL field absent','A_INTERFACE_ERROR')
    for group,fields in zip(('inputs','outputs'),expected):
        obj=control.get(group,{})
        if not isinstance(obj,dict):obj={}
        for key in fields:
            if key not in obj: issue(group+'.'+key,'Required stage field absent','A_INTERFACE_ERROR')
    if action in ('af-execute','verify-seal'):
        output=control.get('outputs',{})
        target=output.get('receipt') if isinstance(output,dict) else None
        if target and not any(unresolved(target)) and control.get('project'):
            from forecast_receipts import receipt_directory
            try:receipt_directory(control['project'],action,target)
            except (RuntimeError,ValueError,TypeError) as exc:issue('outputs.receipt',str(exc),'A_INTERFACE_ERROR')
    if action=='scoring':
        template=json.loads((Path(__file__).parent/'CONTROL.template.json').read_bytes())
        def shape(expected,actual,trail='$'):
            if isinstance(expected,dict):
                if not isinstance(actual,dict): issue(trail,'Required object absent','A_INTERFACE_ERROR');return
                for k,v in expected.items():
                    if k not in actual:issue(trail+'.'+k,'Required score CONTROL field absent','A_INTERFACE_ERROR')
                    else:shape(v,actual[k],trail+'.'+k)
        shape(template,control)
    for trail,value in unresolved(control):
        if trail.startswith('$.dependencies'):continue
        dep=control.get('dependencies',{}).get(trail)
        kind=dep.get('classification','A_OWNER_ACT') if dep else 'A_OWNER_ACT'
        issue(trail,'Real value not available: '+str(value),kind,dep.get('owner') if dep else None)
    def identities(value,trail='$'):
        if isinstance(value,dict):
            if {'path','bytes','sha256'}<=set(value):
                if any(unresolved(value)):return
                try:
                    metadata_path(value['path'])
                except RuntimeError:
                    deferred.append(dict(field=trail,reason='PROTECTED_RUNTIME_REFERENCE_NOT_OPENED'));return
                item={k:value[k] for k in ('path','bytes','sha256')}
                if item['path'] in aliases:
                    physical=aliases[item['path']]
                    if any(item[k]!=physical[k] for k in ('bytes','sha256')):issue(trail,'Selected archived source identity differs','A_SOURCE_DRIFT');return
                    item=physical
                try:checked(item,sources)
                except (OSError,RuntimeError,ValueError) as exc:issue(trail,str(exc),'A_SOURCE_DRIFT')
            else:
                for k,w in value.items():


                    if k not in ('dependencies','outputs') and not (k=='reference_snapshot' and '.changes[' in trail):identities(w,trail+'.'+k)
        elif isinstance(value,list):
            for i,w in enumerate(value):identities(w,trail+'['+str(i)+']')
    identities(control)

    expected_schema='MINRUN_CONTROL_V1' if action=='scoring' else 'MINRUN_AF_CHAIN_CONTROL_V1'
    if 'schema' in control and not any(unresolved(control['schema'])) and control['schema']!=expected_schema:
        issue('schema','Wrong action CONTROL schema','A_INTERFACE_ERROR')
    if action!='scoring' and 'action' in control and not any(unresolved(control['action'])) and control['action']!=action:
        issue('action','Wrong action CONTROL','A_INTERFACE_ERROR')
    def doc(item):
        if not isinstance(item,dict) or not {'path','bytes','sha256'}<=set(item) or any(unresolved(item)):return None
        try:
            metadata_path(item['path'])
            return document({k:item[k] for k in ('path','bytes','sha256')},sources)
        except (OSError,RuntimeError,ValueError,TypeError):return None
    def fields(value,trail,required,expected=None):
        if value is None:return
        for key in required:
            if key not in value or unresolved_value(value[key],field=key):issue(trail+'.'+key,'Required real metadata field missing')
        for key,want in (expected or {}).items():
            if value.get(key)!=want:issue(trail+'.'+key,'Required actual metadata value differs')
    if action!='scoring':
        permit=doc(control.get('permit'));quiet=doc(control.get('quiet_host_disposition'))
        fields(permit,'permit',('schema','released','action','source','utc','control_sha256','quiet_host_disposition'),
               dict(schema='MINRUN_AF_CHAIN_RELEASE_V1',released=True,action=action))
        if permit:
            from forecast_check_helpers import digest
            if permit.get('control_sha256')!=digest({k:v for k,v in control.items() if k!='permit'}):issue('permit.control_sha256','Actual CONTROL release digest mismatch')
            if permit.get('quiet_host_disposition')!=control.get('quiet_host_disposition'):issue('permit.quiet_host_disposition','Actual quiet evidence mismatch')
        fields(quiet,'quiet_host_disposition',('source','utc'),dict(all_project_jobs_disposed=True,no_source_writers=True,before_T5=True,no_scoring=True))
        inp=control.get('inputs',{})
        if not isinstance(inp,dict):inp={}
        if action in ('c-v1-association','af-mapping-refresh','af-final-source-publish',
                      'am3-source-freeze','af-source-freeze','t4g-create-verify-bind'):
            original=doc(inp.get('science_freeze'))
            if original and original.get('schema')=='MINRUN_LIMITED_SCIENCE_SOURCE_FREEZE_V1' and original.get('build')!=control.get('build') and 'science_addendum' not in inp:
                issue('inputs.science_addendum','Changed driver bytes require actual additive record/fresh E GO','A_RUN_OUTPUT')
        for key,role in [('source_review','DRIVER_AF_CHAIN_FINAL_SOURCE_REVIEW'),('part_b','AM3_INDEPENDENT_PART_B')]:
            value=doc(inp.get(key));fields(value,'inputs.'+key,('reviewer','producer','subject','utc'),dict(accepted=True,independent=True,role=role))
            if value and value.get('reviewer')==value.get('producer'):issue('inputs.'+key+'.reviewer','Actual independent reviewer required')
            if value and value.get('paper_only') is True:issue('inputs.'+key,'A paper is not actual owner acceptance')
        value=doc(inp.get('source_acceptance'));fields(value,'inputs.source_acceptance',('subject','utc'),dict(accepted=True,role='AM3_SOURCE_ACCEPTANCE'))
        if value and not (value.get('owner') or value.get('reviewer')):issue('inputs.source_acceptance.owner','Actual owner acknowledgement required')
        for key,schema in [('review_acceptance','FORECAST_BINDING5_REVIEW_ACCEPTANCE_V1'),('consumer_acceptance','FORECAST_BINDING5_CONSUMER_ACCEPTANCE_V1')]:
            value=doc(inp.get(key))
            if value:
                from forecast_source_fields import AF_COMMON,AF_REVIEW,AF_CONSUMER
                fields(value,'inputs.'+key,AF_COMMON+(AF_REVIEW if key=='review_acceptance' else AF_CONSUMER),
                       dict(schema=schema,state='ACCEPTED_FOR_SOURCE_FREEZE'))
                if value.get('paper_only') is True:issue('inputs.'+key,'A paper is not actual owner acceptance')
    if action!='scoring':
        if build and control.get('build')!=build:issue('build','Actual compiled build mismatch','A_SOURCE_DRIFT')
        if catalog and control.get('source_catalog')!=catalog:issue('source_catalog','Accepted source catalog mismatch','A_SOURCE_DRIFT')
    if action=='freeze-science':
        inp=control.get('inputs',{})
        if not isinstance(inp,dict):inp={}
        c=inp.get('c',{})
        if not isinstance(c,dict):c={}
        for k in ('files','time_alignment_closure','callable_ast_inventory','numeric_ancestor_contract','release_binding'):
            if k not in c:issue('inputs.c.'+k,'Required scientific C member absent','A_INTERFACE_ERROR')
        if inventory is not None and inp.get('inventory')!=inventory:issue('inputs.inventory','Exact scientific source inventory mismatch','A_SOURCE_DRIFT')
        if c61 is not None and c.get('files')!=c61:issue('inputs.c.files','Exact archived C61 identities mismatch','A_SOURCE_DRIFT')
    if action=='freeze-science-addendum':
        inp=control.get('inputs',{})
        if isinstance(inp,dict) and all(k in inp and not any(unresolved(inp[k])) for k in
                 ('original_receipt','science_freeze','history','inventory','changes')):
            try:
                from forecast_context import baseline,delta
                original=baseline(inp['original_receipt'],inp['science_freeze'],sources)
                expected=delta(original['inventory'],inp['inventory'],here,document(inp['history'],sources))
                if inp['changes']!=expected:issue('inputs.changes','Complete original/current additive delta mismatch','A_SOURCE_DRIFT')
                if inventory is not None and inp['inventory']!=inventory:issue('inputs.inventory','Addendum current inventory mismatch','A_SOURCE_DRIFT')
            except (OSError,RuntimeError,ValueError,KeyError) as exc:issue('inputs.changes',str(exc),'A_SOURCE_DRIFT')
    return blockers,deferred


def check(control,action,**kw):
    blockers,deferred=inspect(control,action,**kw)
    return dict(schema='MINRUN_TIME_ALIGNMENT_A2_STATIC_GATE_CHECK_V1',action=action,
                state='BLOCKED' if blockers else 'STATIC_FIELDS_READY', blockers=blockers,
                deferred=deferred, runtime_validation_performed=False,
                limitations='Static source/control check; no owner action, crypto, host probe, payload read or scientific freeze.')
