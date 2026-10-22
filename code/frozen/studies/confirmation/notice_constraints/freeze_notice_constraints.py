
'Check both notice-constraint branches and save their source hashes.'
import argparse
import datetime as dt
import hashlib
import importlib.util
import json
from pathlib import Path
import re
import sys
sys.dont_write_bytecode=True
HERE=Path(__file__).resolve().parent
HELPER=Path(__file__).resolve()
BASE_SHA='aa26eff243345fcf070ee7d8a27ea4b1f1081eedd841b7bdc6eca5a974f91036'
CANONICAL_SHA256='ff2d73bddd90981cac887ea479bfae6fd88e48690c32d4aafa3342e279c8231e'
PINS_SHA256='0c35d16345ac5db38926897658557002aa66a0f9162df9dcb8efd4ed1efa3a7a'
TEXT='ADDENDUM_A8_SPECIFICATION_3_REVIEW8_IDENTITIES.md'
RECEIPT='ADDENDUM_A8_SPECIFICATION_3_FREEZE.json'
LABEL='T4G'
SPECIFICATION='confirmation/ANCHORDIAG/SOURCE_DECISION_RULE_SPECIFICATION_1_DEADLINE_20261005.md'
specification2='confirmation/ANCHORDIAG/SOURCE_DECISION_RULE_SPECIFICATION_2_NO_CALENDAR_DEADLINE_20261005.md'
T4J_UTC='2026-10-05T10:32:37Z'
DEADLINE_AEDT=None
DEADLINE_UTC=None
base=HERE/'HISTORICAL_AM3DLC/freeze_a8_specification3.py.evidence.txt'
if base.is_symlink() or hashlib.sha256(base.read_bytes()).hexdigest()!=BASE_SHA:
    raise RuntimeError('Reviewed original AM3 helper drift')
import types
B=types.ModuleType('_am3dld_private_base');B.__file__=str(base)
exec(compile(base.read_bytes(),str(base),'exec'),B.__dict__)
B.TEXT=TEXT;B.CANONICAL_SHA256=CANONICAL_SHA256
require=B.require;sha=B.sha;identity=B.identity;strict=B.strict
utc=B.utc;now=B.now;resource_gate=B.resource_gate;exclusive_json=B.exclusive_json
manifest=B.manifest;checked=B.checked


CURRENT_POLICY_SHA256='9d3885d7f2c8d6d929c878ef76a028812e571dfe2ec41572dba7a86401b5f593'
CITATION_AUTHORITIES=[('confirmation/ANCHORDIAG/SOURCE_DECISION_RULE_SPECIFICATION_1_DEADLINE_20261005.md', 'T4I'), ('confirmation/ANCHORDIAG/SOURCE_DECISION_RULE_SPECIFICATION_2_NO_CALENDAR_DEADLINE_20261005.md', 'T4J'), ('confirmation/ANCHORDIAG/ERRATUM_SPECIFICATION_2_RECORDED_TIME_20261005.md', 'T4K'), ('confirmation/REVIEW8/SOURCE_DECISIONS_REVIEW8_20261005.md', 'T4K')]

def current_version(here=HERE, *, canonical=None, entry=None):
    here=Path(here).absolute()
    require(sha(here/'CURRENT_AM3_VERSION.json')==CURRENT_POLICY_SHA256,'Current-version policy drift or absent')
    p=strict(here/'CURRENT_AM3_VERSION.json')
    require(p['schema']=='A8_SPECIFICATION_3_CURRENT_VERSION_V1' and p['state']=='CURRENT_SOURCE_VERSION' and p['version']=='AM3DLE','Current AM3DLE version required')
    require(p['canonical']==TEXT and p['canonical_sha256']==CANONICAL_SHA256,'Current canonical identity mismatch')
    require(canonical is None or canonical==TEXT,'INACTIVE canonical cannot be current')
    require(entry is None or entry in p['entrypoints'].values(),'INACTIVE entry cannot be current')
    for name,item in p['blocked_entrypoints'].items():
        require(item['path']==name and Path(name).name==name,'Closed blocked-entry path required')
        checked(dict(item,path=str(here/name)),here/name)
    return p


def citation_rows(here=HERE):
    q=Path(here).absolute().parent.parent;rows=[]
    for rel,label in CITATION_AUTHORITIES:
        man=q/('confirmation/TIMESTAMPS/'+label+'/MANIFEST_'+label+'.sha256')
        _,covered=manifest(man,label,q);item=identity(q/rel)
        require(covered.get(rel)==item,'Authority citation not covered by its manifest: '+rel)
        rows.append(dict(timestamp_checks=item,timestamp_label=label,manifest=identity(man)))
    return rows


def citation_table(here=HERE):
    q=Path(here).absolute().parent.parent
    lines=['| Authority path (relative to Q) | SHA-256 | Timestamp manifest path (relative to Q) | Manifest SHA-256 |','|---|---|---|---|']
    for row in citation_rows(here):
        a=row['timestamp_checks'];m=row['manifest']
        lines.append('| `'+str(Path(a['path']).relative_to(q))+'` | `'+a['sha256']+'` | `'+str(Path(m['path']).relative_to(q))+'` | `'+m['sha256']+'` |')
    return '\n'.join(lines)


def verify_citations(here=HERE, *, text=None):
    here=Path(here).absolute()
    if text is None:text=(here/TEXT).read_text()
    begin='<!-- AM3_AUTHORITY_IDENTITIES_BEGIN -->';end='<!-- AM3_AUTHORITY_IDENTITIES_END -->'
    require(text.count(begin)==text.count(end)==1,'Exact single timestamp_checks-citation table required')
    block=text.split(begin,1)[1].split(end,1)[0].strip()
    require(block==citation_table(here),'Canonical timestamp_checks citation differs from actual bytes/manifest identity')
    return citation_rows(here)


def safe_metadata(path,q):
    p=Path(path).absolute()
    require('..' not in p.parts,'Parent traversal forbidden')
    require(p.is_relative_to(q.parents[1]),'Final source outside project')
    require(not any(x.lower() in {'host_state','state','sealed','seal','seals','scoring','score','scores','predictions','prediction','prices','truth','run','evaluation','private'} for x in p.relative_to(q.parents[1]).parts),'Outcome/runtime path forbidden')
    require(p.suffix in {'.py','.sh','.json','.md','.txt','.sha256','.log','.tex'} and not p.name.startswith(('SEAL_','SCORE_','PREDICTION_')),'Source/metadata file required')
    return p


def refs(value,q):

    result=set(); af=q/'confirmation/forecast_hashes'; overlay=af/'deadline_checks'
    def add(path,digest):
        if not isinstance(path,str) or not isinstance(digest,str) or not re.fullmatch('[0-9a-f]{64}',digest):return
        p=Path(path)
        candidates=[p] if p.is_absolute() else [q/p,q.parents[1]/p,af/p,overlay/p]
        result.update((str(v.absolute()),digest) for v in candidates)
    def walk(v):
        if isinstance(v,dict):
            add(v.get('path'),v.get('sha256'))
            for k,x in v.items():
                add(k,x)
                if isinstance(x,dict):add(k,x.get('sha256'))
                walk(x)
        elif isinstance(v,list):
            for x in v:walk(x)
    walk(value);return result


def deadline_inputs(here=HERE):
    here=Path(here).absolute();q=here.parent.parent
    require(sha(here/'NO_CALENDAR_INPUT_PINS.json')==PINS_SHA256,'No-calendar pins drift')
    pins=strict(here/'NO_CALENDAR_INPUT_PINS.json');found={}
    for rel,digest in pins.items():
        p=Path(rel);require(not p.is_absolute() and '..' not in p.parts,'Unsafe deadline pin')
        item=identity(q/p);require(item['sha256']==digest,'Deadline/T4I input drift: '+rel);found[rel]=item
    header,rows=manifest(q/'confirmation/TIMESTAMPS/T4I/MANIFEST_T4I.sha256','T4I',q)
    require(rows.get(SPECIFICATION)==found[SPECIFICATION],'Deadline specification missing from T4I')
    note='confirmation/ANCHORDIAG/SOURCE_NOTE_CLAUSE5_NOT_RUN_20261005.md'
    require(rows.get(note)==found[note],'Inactive note must remain historical T4I evidence')
    _,jrows=manifest(q/'confirmation/TIMESTAMPS/T4J/MANIFEST_T4J.sha256','T4J',q)
    require(jrows.get(specification2)==found[specification2],'specification2 missing from T4J')
    return found


DECISION='confirmation/REVIEW8/SOURCE_DECISIONS_REVIEW8_20261005.md'
REVIEW8_PINS_SHA256='a902d69b8f517db2063b552dc0eb1325544d5c04df47d98abfd7e5bcbf6f4eba'


def review8_inputs(here=HERE):

    import subprocess
    q=Path(here).absolute().parent.parent
    require(sha(Path(here)/'REVIEW8_INPUT_PINS.json')==REVIEW8_PINS_SHA256,'REVIEW8 pins drift')
    pins=strict(Path(here)/'REVIEW8_INPUT_PINS.json');found={}
    for rel,digest in pins.items():
        p=Path(rel);require(not p.is_absolute() and '..' not in p.parts,'Unsafe REVIEW8 pin')
        item=identity(q/p);require(item['sha256']==digest,'DEC/T4K input drift: '+rel);found[rel]=item
    root=q/'confirmation/TIMESTAMPS';man=root/'T4K/MANIFEST_T4K.sha256'
    header,rows=manifest(man,'T4K',q)
    require(rows.get(DECISION)==found[DECISION],'DEC missing from T4K')
    note='confirmation/ANCHORDIAG/ERRATUM_SPECIFICATION_2_RECORDED_TIME_20261005.md'
    checked(rows[note],q/note)
    evidence={}
    for name in ('freetsa','digicert'):
        token=root/'T4K'/('T4K_'+name+'.tsr')
        certs=[root/'certs/freetsa_cacert.pem',root/'certs/freetsa_tsa.crt'] if name=='freetsa' else [root/'certs/macos_system_roots.pem']
        command=['/opt/homebrew/bin/openssl','ts','-verify','-data',str(man),'-in',str(token),'-CAfile',str(certs[0])]
        if name=='freetsa':command+=['-untrusted',str(certs[1])]
        result=subprocess.run(command,capture_output=True,text=True,timeout=30)
        require(result.returncode==0 and 'Verification: OK' in result.stdout+result.stderr,'T4K signature verification failed: '+name)
        result=subprocess.run(['/opt/homebrew/bin/openssl','ts','-reply','-in',str(token),'-text'],capture_output=True,text=True,timeout=30,check=True)
        stamps=[line.split(':',1)[1].strip() for line in result.stdout.splitlines() if line.startswith('Time stamp:')]
        require(len(stamps)==1,'T4K timestamp missing/duplicate')
        stamp=dt.datetime.strptime(stamps[0],'%b %d %H:%M:%S %Y GMT').replace(tzinfo=dt.timezone.utc)
        require(stamp>=utc(header['created_utc']),'T4K token predates manifest')
        evidence[name]=dict(token=identity(token),certificates=[identity(p) for p in certs],verified_utc=stamp.isoformat())
    return found,evidence


COMMIT_FIELDS={'schema','state','deadline_aedt','decision','historical_t4f_manifest','owner_interface_json','owner_interface_md','owner_final_source_commitment','owner_verifier','owner_schema','owner_state','source_inventory_pointers','final_sources','final_mapping','final_consumer_files','runtime_sources'}


def pointer(value,path):
    require(isinstance(path,str) and path.startswith('/') and path!='/', 'Explicit source inventory pointer required')
    for part in path.split('/')[1:]:
        part=part.replace('~1','/').replace('~0','~')
        value=value[int(part)] if isinstance(value,list) else value[part]
    return value


def inventory_rows(value):
    rows=[]
    def walk(v):
        if isinstance(v,dict):
            if set(v)=={'path','bytes','sha256'}: rows.append(v)
            else:
                for item in v.values():walk(item)
        elif isinstance(v,list):
            for item in v:walk(item)
    walk(value);return rows


def verified_owner_source(overlay,inventory,contract):

    require(set(contract)=={'modules','entrypoint','function'},'Closed owner verifier contract required')
    modules=contract['modules'];require(isinstance(modules,dict) and modules,'Owner verifier source modules required')
    require(set(modules)=={'delay_authority','delay_root_mapping','delay_freeze','delay_final_source'} and contract['entrypoint']=='delay_final_source' and contract['function']=='verify_final_source','Exact AF8 source verifier entrypoint required')
    saved={name:sys.modules.get(name) for name in modules}
    try:
        for name,item in modules.items():
            require(re.fullmatch('[A-Za-z_][A-Za-z_0-9]*',name) is not None,'Unsafe owner module name')
            p=Path(item['path']);require(p==overlay/{'delay_authority':'timestamp_checks.py','delay_root_mapping':'root_mapping.py','delay_freeze':'freeze_delay.py','delay_final_source':'source_inventory.py'}[name],'Exact AF8 source module path required')
            require(inventory.get(str(p))==item,'Unpinned owner verifier source: '+name);checked(item,p)
            spec=importlib.util.spec_from_file_location(name,p);module=importlib.util.module_from_spec(spec)
            sys.modules[name]=module;spec.loader.exec_module(module)
        module=sys.modules[contract['entrypoint']]
        return getattr(module,contract['function'])(overlay/'FINAL_SOURCE_COMMITMENT.json')
    finally:
        for name in saved:
            if saved[name] is None:sys.modules.pop(name,None)
            else:sys.modules[name]=saved[name]


def mapping_requirements(mapping,q):

    import ast
    policy=current_version(q/'confirmation/notice_constraints')
    require(mapping['contract']['fill_relative_path']==policy['final_fill_relative_path'],'Final FILL path differs from current policy')
    require(mapping.get('consumer_task_revision')==policy['consumer_task_revision'],'Stale C TASK_REVISION in final mapping')
    item=mapping.get('consumer_tested_sources',{}).get('freeze_consumers.py')
    require(isinstance(item,dict),'Final mapping must bind C freeze_consumers.py')
    p=q/'batch_estimation/batch_checks/freeze_consumers.py';checked(item,p)
    values=[node.value for node in ast.parse(p.read_text()).body if isinstance(node,ast.Assign) and any(isinstance(t,ast.Name) and t.id=='TASK_REVISION' for t in node.targets)]
    require(len(values)==1 and ast.literal_eval(values[0])==policy['consumer_task_revision'],'Stale C TASK_REVISION in actual pinned source')


def final_sources(path,q,historical,*,value=None):
    p=Path(path).absolute();require(p==q/'confirmation/notice_constraints/FINAL_AF_REVIEW8_COMMITMENT.json','Exact REVIEW8 final AF commitment path required')
    c=strict(p) if value is None else value
    require(set(c)==COMMIT_FIELDS and c['schema']=='A8_SPECIFICATION_3_REVIEW8_FINAL_AF_COMMITMENT_V1' and c['state']=='FINAL_IDENTITIES_VERIFIED','Complete REVIEW8 final AF commitment required')
    require(c['deadline_aedt'] is None,'Calendar deadline must remain null')
    checked(c['decision'],q/DECISION)
    checked(c['historical_t4f_manifest'],q/'confirmation/TIMESTAMPS/T4F/MANIFEST_T4F.sha256')
    af=q/'confirmation/forecast_hashes';old=af/'deadline_checks';overlay=af/'availability_delays'
    checked(c['owner_interface_json'],overlay/'AM3_FINAL_SOURCE_INTERFACE.json')
    checked(c['owner_interface_md'],overlay/'AM3_FINAL_SOURCE_INTERFACE.md')
    checked(c['owner_final_source_commitment'],overlay/'FINAL_SOURCE_COMMITMENT.json')
    interface=strict(c['owner_interface_json']['path'])
    require(interface.get('schema')=='FORECAST_BINDING_AM3_FINAL_SOURCE_INTERFACE_V2' and interface.get('state')=='CONTRACT_PENDING_FINAL_SOURCE_COMMITMENT','Exact AF8 interface schema/state required')
    require(interface.get('corrected_delay_minutes')==[5,15,60] and interface.get('corrected_arms')==['L14','L_Laz'],'AF8 interface scope drift')
    require((c['decision']['path'],c['decision']['sha256']) in refs(interface,q),'AF8 source interface lacks DEC identity')
    sources=c['final_sources'];require(isinstance(sources,list) and sources,'Final source inventory required')
    current={}
    for item in sources:
        source=safe_metadata(item['path'],q)
        require(source.is_relative_to(af) and str(source) not in current,'Final AF source path/duplicate')
        checked(item,source);current[str(source)]=item
    require(all(current.get(v['path'])==v for v in historical.values()),'Final sources do not preserve the complete T4F snapshot')

    for root in (old,overlay):
        code=[*root.glob('*.py'),*(root/'tests').glob('*.py')]
        require(code and all(current.get(str(v))==identity(v) for v in code),'Final AF sources omit an overlay or its code/tests')
    for item in (c['owner_interface_json'],c['owner_interface_md'],c['final_mapping']):
        require(current.get(item['path'])==item,'Final inventory omits interface/mapping identity')
    mappingpath=safe_metadata(c['final_mapping']['path'],q)
    require(mappingpath==overlay/'FINAL_ROOT_MAPPING.json','Exact AF8 final mapping path required');checked(c['final_mapping'],mappingpath)
    mapping=strict(mappingpath)
    require(mapping.get('schema')=='FORECAST_BINDING_FINAL_ROOT_MAPPING_V2' and mapping.get('state')=='FINAL_REVIEWED_SOURCE_MAPPING_NOT_FREEZE','Exact final accepted source mapping required')
    mapping_requirements(mapping,q)
    consumers=c['final_consumer_files'];require(isinstance(consumers,list) and consumers,'Final consumer source identities required')
    for item in consumers:
        source=safe_metadata(item['path'],q);require(source.is_relative_to(q),'Direct T4G consumer metadata must be under Q');checked(item,source)
    owner=verified_owner_source(overlay,current,c['owner_verifier'])
    require(owner==strict(c['owner_final_source_commitment']['path']),'AF8 owner verification disagreement')
    require(c['owner_schema']=='FORECAST_BINDING_FINAL_SOURCE_COMMITMENT_V2' and c['owner_state']=='SOURCE_COMMITMENT_NOT_RUNTIME_FREEZE','Exact AF8 source schema/state required')
    require(owner.get('schema')==c['owner_schema'] and owner.get('state')==c['owner_state'],'Owner source schema/state drift')
    require((c['decision']['path'],c['decision']['sha256']) in refs(owner,q),'AF8 final source record lacks DEC identity')
    pointers=c['source_inventory_pointers'];require(pointers==['/final_base_source_rows','/parent_overlay_source_rows','/parent_overlay_delivery','/parent_overlay_test_receipt','/overlay_sources','/test_receipt','/resource_projection','/final_root_mapping'],'Exact complete AF8 inventory pointers required')
    expected=[]
    for ref in pointers:expected+=inventory_rows(pointer(owner,ref))


    speed=af/'overlap_cache'
    speed_rows=[v for v in inventory_rows(owner) if Path(v['path']).is_relative_to(speed)]
    expected+=speed_rows
    if speed_rows:
        for name in ('integration.py','speed_core.py'):
            require(current.get(str(speed/name))==identity(speed/name),'Final speed commitment omits required runtime source')
    require(expected and current=={v['path']:v for v in expected},'Final inventory differs from verified owner inventories')
    owner_refs=refs(owner,q)
    require((c['final_mapping']['path'],c['final_mapping']['sha256']) in owner_refs,'Owner lacks final mapping identity')
    needed=inventory_rows(mapping)
    croot=q/'batch_estimation/batch_checks'
    needed=[v for v in needed if Path(v['path']).is_relative_to(croot)]
    byconsumer={v['path']:v for v in consumers}
    require(len(byconsumer)==len(consumers) and needed and all(byconsumer.get(v['path'])==v for v in needed),'Final consumer inventory omits reviewed source/metadata')
    require(all((v['path'],v['sha256']) in refs(mapping,q) for v in consumers),'Final mapping lacks exact consumer associations')
    pending=dict(af_code_freeze=None,delay_overlay_freeze=None,delay_overlay_timestamp_binding=None)
    require(c['runtime_sources']==owner['runtime_sources']==pending,'Source commitment cannot invent runtime authorities')
    require(owner['historical_snapshot']['manifest']==c['historical_t4f_manifest'] and {v['path']:v for v in owner['final_base_source_rows']}=={v['path']:v for v in historical.values()},'AF8 historical snapshot drift')
    require(owner.get('final_consumer_task_revision')==current_version(q/'confirmation/notice_constraints')['consumer_task_revision'],'Stale C TASK_REVISION in owner commitment')
    require(owner['corrected_delay_minutes']==[5,15,60] and owner['corrected_arms']==['L14','L_Laz'] and owner['models_refitted']==0 and owner['deadline_aedt'] is None,'AF8 source scope/zero-refit/calendar drift')
    delay=owner['frozen_delay_sources']
    expected_delay={'batch_estimation/fitting/code/'+n for n in ('rebuild_delayed_features.py','delay_cache.py','batch_inputs.py','runner.py')}|{'batch_estimation/disk_checks/disk_overlay.py','batch_estimation/disk_checks/forecast_wrapper.py'}
    require(set(delay)==expected_delay,'Exact six frozen DLY8 source identities required')
    for rel,item in delay.items():
        source=safe_metadata(item['path'],q);require(source==q/rel,'Exact specified DLY8 source path required');checked(item,source)
    return c

def af_freeze(path,q,sources,commitment=None):

    item=B.af_freeze(path,q,sources)
    require(commitment is not None,'Final source commitment required for corrected AF timestamp_checks')
    freeze=strict(path);association=refs(freeze,q)
    mapping=strict(commitment['final_mapping']['path'])
    mapped=freeze.get('root_mapping')==mapping.get('root_mapping',mapping.get('mapping',mapping))
    require(mapped or (commitment['final_mapping']['path'],commitment['final_mapping']['sha256']) in association,'AF freeze does not bind final root mapping')
    return item


NR_TERMINAL_CAUSES=('TERMINAL_PARITY_FAILURE','TERMINAL_COVERAGE_FAILURE','TERMINAL_IDENTITY_FAILURE','UNREPAIRABLE_WITHOUT_FROZEN_COMPUTATION_CHANGE')

def nr_cause_allowed(cause,*,terminal=False,requires_computation_change=False):

    return (cause in NR_TERMINAL_CAUSES[:3] and terminal is True) or (
        cause==NR_TERMINAL_CAUSES[3] and requires_computation_change is True)


def record(here=HERE,helper=HELPER,*,attestation_path,final_source_commitment_path=None,af_code_freeze=None):
    here=Path(here).absolute();q=here.parent.parent
    require(Path(helper).absolute()==here/'freeze_notice_constraints.py','Effective REVIEW8 helper required')
    current_version(here,entry=Path(helper).name)
    found=deadline_inputs(here)
    review8,evidence=review8_inputs(here)
    citations=verify_citations(here)
    value=B.record(here,here/'freeze_a8_specification3.py',attestation_path=attestation_path)
    require(utc(value['author_attestation_recorded_utc'])>=max(utc(v['verified_utc']) for v in evidence.values()),'REVIEW8 attestation must follow both T4K TSAs')
    p=Path(final_source_commitment_path or here/'FINAL_AF_REVIEW8_COMMITMENT.json').absolute()
    commit=final_sources(p,q,value['af_sources'])
    owner=strict(commit['owner_final_source_commitment']['path'])
    bound_af=af_freeze(af_code_freeze,q,value['af_sources'],commit) if af_code_freeze else None
    value.update(schema='A8_SPECIFICATION_3_REVIEW8_V1',state='A8_SPECIFICATION_3_REVIEW8_FROZEN_BEFORE_SCORING',frozen_utc=now(),
        review8_inputs=review8,review8_timestamp_evidence=evidence,
        authority_citations=citations,current_version_policy=identity(here/'CURRENT_AM3_VERSION.json'),current_version='AM3DLE',
        corrected_delay_minutes=[5,15,60],joint_claim_rule='DEC D1/D2: weakest available specified/aligned +5/+15/+60; no pooled estimate; no inherited seed checks',
        deadline_inputs=found,effective_deadline_aedt=DEADLINE_AEDT,effective_deadline_utc=DEADLINE_UTC,
        historical_af_snapshot=dict(manifest=commit['historical_t4f_manifest'],files=value['af_sources']),
        af_historical_snapshot=owner['historical_snapshot'],
        af_parent_overlay_snapshot=dict(delivery=owner['parent_overlay_delivery'],files=owner['parent_overlay_source_rows'],test_receipt=owner['parent_overlay_test_receipt'],runtime_eligibility=False),
        af_frozen_delay_sources=owner['frozen_delay_sources'],
        af_final_source_commitment=dict(identity=commit['owner_final_source_commitment'],verified=strict(commit['owner_final_source_commitment']['path'])),
        af_runtime_authorities=dict(af_code_freeze=bound_af,delay_overlay_freeze=None,delay_overlay_timestamp_binding=None),
        final_af_source_commitment=commit,final_af_source_commitment_identity=identity(p),
        af_code_freeze=bound_af,branches=['CORRECTED_RUN_BEFORE_T5','NOT_RUN_IF_FROZEN_PROCEDURE_CANNOT_COMPLETE'],
        nr_fallback_rule=dict(causes=list(NR_TERMINAL_CAUSES),independent_state_authority_required=True,no_time_or_resource_delay_inference=True),
        changes=dict(value['changes'],effective_deadline_aedt=DEADLINE_AEDT,not_run_only_if_frozen_procedure_cannot_complete=True,corrected_delay_minutes=[5,15,60],other_rule_changes=True,rule_changes_authority=review8[DECISION],reporting='DEC D1/D2/D3 weakest available specified/aligned +5/+15/+60; each reading and joint statement; no pooled estimate'),
        af_binding_order='final consumer identities -> AF8 final mapping/reviews -> reviewed additive-overlay owner final source commitment -> AM3 REVIEW8 final AF adapter and freeze -> after batch/DLY8-R8: actual AF CODE_FREEZE and reviewed owner runtime overlay freeze -> both T4G TSAs covering AM3 and owner root union -> AM3 and owner timestamp bindings -> corrected run/verified seal -> T5 -> score')
    value['files'] += [identity(helper),identity(here/'bind_notice_constraints.py'),identity(here/'NO_CALENDAR_INPUT_PINS.json'),identity(here/'AM3DLE_TEXT.diff'),identity(here/'prepare_notice_constraints.py'),identity(here/'REVIEW8_INPUT_PINS.json'),identity(here/'NR_FORMS_REVIEW8.json'),identity(here/'NR_AUTHORITY_INTERFACE_REVIEW8.json'),identity(p)]
    value['files'] += list(owner['frozen_delay_sources'].values())
    value['files'] += [identity(base),identity(here/'CURRENT_AM3_VERSION.json'),identity(here/'CANONICAL_CHANGE_AM3DLE.json'),identity(here/'notice_constraint_sources.py')]
    value['files'] += [identity(here/name) for name in current_version(here)['blocked_entrypoints']]
    return value


def verify(path,here=HERE,helper=HELPER,*,require_timestamp=False,require_af_freeze=False):
    here=Path(here).absolute();require(Path(path).absolute()==here/RECEIPT,'Effective REVIEW8 receipt path required')
    current_version(here)
    frozen=strict(path)
    require(frozen.get('schema')=='A8_SPECIFICATION_3_REVIEW8_V1' and frozen.get('current_version')=='AM3DLE','INACTIVE receipt cannot be verified as current')
    expected=record(here,helper,attestation_path=frozen['author_attestation']['path'],final_source_commitment_path=frozen['final_af_source_commitment_identity']['path'],af_code_freeze=frozen['af_code_freeze']['path'] if frozen['af_code_freeze'] else None)
    require(set(frozen)==set(expected),'REVIEW8 receipt field set mismatch')
    for k in expected:require(k=='frozen_utc' or frozen[k]==expected[k],'REVIEW8 receipt drift: '+k)
    require(utc(frozen['author_attestation_recorded_utc'])<=utc(frozen['frozen_utc'])<=dt.datetime.now(dt.timezone.utc),'REVIEW8 freeze chronology')
    if require_timestamp or require_af_freeze:
        s=importlib.util.spec_from_file_location('_am3dl_binding',here/'bind_notice_constraints.py')
        m=importlib.util.module_from_spec(s);s.loader.exec_module(m)
        m.verify_binding(here/'T4G_BINDING.json',here=here,specification=frozen,require_af_freeze=require_af_freeze)
    return frozen


def create(here=HERE,*,attestation_path,final_source_commitment_path=None,af_code_freeze=None):
    resource_gate();here=Path(here).absolute()
    value=record(here,here/'freeze_notice_constraints.py',attestation_path=attestation_path,final_source_commitment_path=final_source_commitment_path,af_code_freeze=af_code_freeze)
    require(utc(value['frozen_utc'])>=utc(value['author_attestation_recorded_utc']),'Future attestation refused')
    exclusive_json(here/RECEIPT,value);verify(here/RECEIPT,here,here/'freeze_notice_constraints.py')
    return value


def main():
    p=argparse.ArgumentParser(description=__doc__);m=p.add_mutually_exclusive_group(required=True)
    m.add_argument('--source-freeze',action='store_true');m.add_argument('--dry-run',action='store_true');m.add_argument('--verify',type=Path)
    p.add_argument('--attestation',type=Path);p.add_argument('--final-source-commitment',type=Path);p.add_argument('--af-code-freeze',type=Path)
    p.add_argument('--require-timestamp',action='store_true');p.add_argument('--require-af-freeze',action='store_true');a=p.parse_args();resource_gate()
    if a.verify:verify(a.verify,require_timestamp=a.require_timestamp,require_af_freeze=a.require_af_freeze);print('AM3 REVIEW8 VERIFIED '+sha(a.verify));return
    require(a.attestation is not None and not a.require_timestamp and not a.require_af_freeze,'Actual --attestation required')
    kwargs=dict(attestation_path=a.attestation,final_source_commitment_path=a.final_source_commitment,af_code_freeze=a.af_code_freeze)
    if a.source_freeze:create(**kwargs);print('AM3 REVIEW8 FROZEN; T4G still required')
    else:print(json.dumps(record(**kwargs),indent=2))

if __name__=='__main__':
    try:main()
    except (ValueError,RuntimeError,OSError,KeyError,TypeError) as e:raise SystemExit('AM3 REVIEW8 REFUSED: '+str(e))
