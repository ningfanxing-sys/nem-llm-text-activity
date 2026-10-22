'Bind structural feature timing measurements to their source hashes.'
from contextlib import contextmanager
import hashlib
import json
import os
from pathlib import Path
import stat
import sys
import types

HERE = Path(__file__).absolute().parent
AF = HERE.parent
SPEED_ROOT = AF / 'overlap_cache'
F5_SOURCE = AF.parents[1] / 'batch_estimation/matrix_storage/eviction_patch.py'
MANIFEST_PIN = {'path': str(SPEED_ROOT / 'FINAL_DELIVERY_MANIFEST_C.json'),
                'bytes': 24898, 'sha256': '73dc2f11724ba293598581cfddc9decbb9a5f69309bea2b2a1f7e238d52706b0'}
F5_PIN = {'path': str(F5_SOURCE), 'bytes': 5784,
          'sha256': 'bd80165800befc0ecdaa2d2d54eb31bef690ad63d8c8b137cfb708d55e3928ec'}
SPEED_SUITE_COUNTS = {'test_speed_core':14,'test_integration':17,'test_eviction':1,
    'test_structural':1,'test_candidates':13,'test_pass_cache':17,'test_support_plan_b':17,
    'test_campaign_b':28,'test_support_plan_c':14,'test_measure_c':23,'test_summary_c':28,
    'test_summary_c_receipt_compat':24}
CASE_NAMES = tuple(f'{domain}_d{delta}_{reading}' for domain in ('synthetic','real')
                   for delta in (0,15,60) for reading in ('specified','aligned'))


def require(ok, message):
    if not ok:
        raise PermissionError('FORECAST_BINDING9 SPEED3 refused: ' + message)


def _key(info):
    return info.st_dev, info.st_ino, info.st_mode, info.st_uid, info.st_gid


def metadata(path, *, collect=False):

    raw = str(path); p = Path(raw)
    require(p.is_absolute() and str(p.absolute()) == raw and os.path.normpath(raw) == raw,
            'Canonical absolute metadata path required')
    parts = p.parts[2:] if p.is_relative_to(Path('/private/tmp')) else p.parts
    require(not {'host_state','state','models','predictions','scores','scored','evaluation','run',
                 '.ssh','.aws','Keychains','private'}.intersection(parts)
            and not p.name.startswith(('SEAL','SCORE')) and p.name not in ('.env','auth.json','.netrc'),
            'Protected content is not speed metadata')
    require(p.is_relative_to(SPEED_ROOT) or p == F5_SOURCE or p.is_relative_to(Path('/private/tmp')),
            'Speed metadata escaped exact speed/F5 or synthetic roots')
    from common import open_directory_metadata
    handles=[];edges=[];digest=hashlib.sha256();payload=[];total=0
    try:
        handles.append(open_directory_metadata('/')); parent_path='/'
        for part in p.parts[1:-1]:
            parent=handles[-1];reference_snapshot=os.stat(part,dir_fd=parent,follow_symlinks=False)
            require(stat.S_ISDIR(reference_snapshot.st_mode) and not stat.S_ISLNK(reference_snapshot.st_mode), 'Real metadata ancestry required')
            child=open_directory_metadata(part,dir_fd=parent,parent_path=parent_path);handles.append(child)
            require(_key(os.fstat(child))==_key(reference_snapshot),'Metadata directory identity drift')
            edges.append((parent,part,child,_key(reference_snapshot)));parent_path=str(Path(parent_path)/part)
        parent=handles[-1];reference_snapshot=os.stat(p.name,dir_fd=parent,follow_symlinks=False)
        require(stat.S_ISREG(reference_snapshot.st_mode) and not stat.S_ISLNK(reference_snapshot.st_mode)
                and reference_snapshot.st_size <= 32*1024*1024,'Regular bounded speed metadata required')
        fd=os.open(raw,os.O_RDONLY|os.O_NOFOLLOW|os.O_CLOEXEC);handles.append(fd)
        require(_key(os.fstat(fd))==_key(reference_snapshot),'Speed leaf changed before read')
        for par,name,child,key in edges:
            require(_key(os.fstat(child))==key and _key(os.stat(name,dir_fd=par,follow_symlinks=False))==key,
                    'Metadata ancestry changed before read')
        while True:
            block=os.read(fd,1<<20)
            if not block:break
            total+=len(block);require(total<=32*1024*1024,'Metadata grew beyond bound');digest.update(block)
            if collect:payload.append(block)
        after=os.fstat(fd)
        require(_key(after)==_key(reference_snapshot) and reference_snapshot.st_size==after.st_size==total
                and reference_snapshot.st_mtime_ns==after.st_mtime_ns and reference_snapshot.st_ctime_ns==after.st_ctime_ns,
                'Speed leaf changed during read')
        require(_key(os.stat(p.name,dir_fd=parent,follow_symlinks=False))==_key(reference_snapshot),'Metadata leaf drift')
        for par,name,child,key in edges:
            require(_key(os.fstat(child))==key and _key(os.stat(name,dir_fd=par,follow_symlinks=False))==key,
                    'Metadata ancestry changed during read')
        return {'path':raw,'bytes':total,'sha256':digest.hexdigest()}, b''.join(payload) if collect else None
    except (OSError,ValueError,TypeError,AttributeError) as exc:
        raise PermissionError('Cannot certify read-only speed metadata') from exc
    finally:
        for fd in reversed(handles):os.close(fd)


def identity(path):
    return metadata(Path(path).absolute())[0]


def read(path):
    def pairs(items):
        out={}
        for k,v in items:
            require(k not in out,'Duplicate metadata key');out[k]=v
        return out
    return json.loads(metadata(Path(path).absolute(),collect=True)[1],object_pairs_hook=pairs,
        parse_constant=lambda value: (_ for _ in ()).throw(PermissionError('Nonfinite speed metadata')))


def validate_speed_test_receipt(value, eviction_identity):
    require(value.get('schema')=='AFSPEEDC2_COMPLETE_REGRESSION_RECEIPT_V1'
            and value.get('state')=='PASS' and value.get('tests_run')==197
            and all(type(value.get(k)) is int and value[k]==0 for k in ('failures','errors','skipped'))
            and value.get('selected_tests') is False and value.get('source_unchanged') is True
            and value.get('source_before') and value['source_before']==value.get('source_after')
            and value.get('compiled_sources_unchanged') is True
            and value.get('compiled_source_identities')
            and value['compiled_source_identities']==value.get('compiled_source_identities_current')
            and value.get('actual_module_test_counts')==SPEED_SUITE_COUNTS
            and value.get('expected_module_test_counts')==SPEED_SUITE_COUNTS
            and len(value.get('complete_unselected_test_ids',[]))==197
            and len(set(value['complete_unselected_test_ids']))==197
            and value.get('numerical_processes')==1 and value.get('synthetic_only') is True,
            'Exact clean unselected final C2 197-test evidence required; failed/old B is historical')
    require(value.get('source_only_import_hook') is True and value.get('bootstrap_harness_direct_source') is True
            and value.get('resources') and all(r.get('nice')==20 and r.get('memory_free_percent',0)>=25
                and r.get('peak_rss_bytes',1_500_000_000)<1_500_000_000 for r in value['resources']),
            'Actual compiled sources and unchanged production resource limits required')
    diagnostic=value.get('direct_reviewed_eviction_diagnostic',{})
    require(diagnostic.get('state')=='PASS' and diagnostic.get('bytes_preserved') is True
            and diagnostic.get('F5_preflight_run') is False and diagnostic.get('dependency')==eviction_identity
            and diagnostic.get('rss_drop_bytes',-1)>=diagnostic.get('required_drop_bytes',1),
            'Reviewed SET5 byte-preserving effective eviction evidence required')
    require(all(value.get(k) is False for k in ('host_executed','freeze','timestamp','real_state_or_locks_probed')),
            'Engineering receipt cannot claim real state operations or host eligibility')


def verify_speed_delivery(*, root=SPEED_ROOT, expected_manifest=MANIFEST_PIN,
                          eviction=F5_SOURCE, expected_eviction=F5_PIN):
    root=Path(root).absolute();eviction=Path(eviction).absolute()
    if root==SPEED_ROOT:
        require(expected_manifest==MANIFEST_PIN and eviction==F5_SOURCE and expected_eviction==F5_PIN,
                'Production uses only the pinned final SPEED3/F5 identities')
    else:
        require(root.is_relative_to(Path('/private/tmp')) and eviction.is_relative_to(Path('/private/tmp')),
                'Only private synthetic fixture roots may supply alternate metadata')
    manifest_path=root/'FINAL_DELIVERY_MANIFEST_C.json'
    require(identity(manifest_path)==expected_manifest,'Exact completed SPEED3 delivery identity drift')
    manifest=read(manifest_path)
    require(manifest.get('schema')=='AFSPEEDC_ENGINEERING_DELIVERY_MANIFEST_V1'
            and manifest.get('all24bytecomparisons') is True and manifest.get('clean_full_tests')==197
            and manifest.get('known_owned_processes_closed') is True and manifest.get('runtime_source_unchanged') is True
            and manifest.get('production_full_D_guard_unchanged') is True
            and all(manifest.get(k) is False for k in ('host_eligibility_granted','freeze','timestamp','production_run')),
            'Final AFV-B2 preparation and process closure required, never a release')
    source=manifest.get('source_identities'); evidence=manifest.get('evidence_identities')
    require(isinstance(source,dict) and source and isinstance(evidence,dict) and evidence,
            'Complete source and evidence inventories required')
    require(set(source)=={p.name for p in root.glob('*.py')},'Speed source census drift')
    def checked_relative(name,item):
        relative=Path(name)
        require(not relative.is_absolute() and '..' not in relative.parts and item.get('path')==str(root/relative),
                'Speed source/evidence path escaped the pinned root')
        require(identity(root/relative)==item,'Speed file drift: '+name)
        return item
    source={name:checked_relative(name,item) for name,item in source.items()}
    evidence={name:checked_relative(name,item) for name,item in evidence.items()}
    require(identity(eviction)==expected_eviction,'Reviewed frozen SET5 source drift')
    suite_rel='validation/run8_afspeedc2/TEST_RESULTS.json';summary_rel='EVIDENCE_SUMMARY_C_V5.json'
    campaign_rel='campaign/run6_afspeedc/RESULT.json';plan_rel='campaign/run6_afspeedc/PLAN.json'
    for name in (suite_rel,summary_rel,campaign_rel,plan_rel,'EFFECTIVE_SPEC_IDENTITY_C.json',
                 'AFSPEEDC_SAMPLE_DECLARATION.json','C_RECEIPT_COMPAT_SPEC_IDENTITY.json'):
        require(name in evidence,'Required SPEED3 final evidence omitted: '+name)
    suite=read(root/suite_rel);validate_speed_test_receipt(suite,expected_eviction)
    summary=read(root/summary_rel);campaign=read(root/campaign_rel)
    require(summary.get('schema')=='AFSPEED_COMPLETE_ENGINEERING_EVIDENCE_C_V5'
            and summary.get('state')=='PASS_COMPLETE_12_CASES_24_ARM_COMPARISONS'
            and {r.get('case') for r in summary.get('cases',[])}==set(CASE_NAMES)
            and len(summary['cases'])==12 and sum(len(r.get('comparisons',[])) for r in summary['cases'])==24
            and all(x.get('byte_equal') is True for r in summary['cases'] for x in r['comparisons'])
            and summary.get('comparison_scope_counts')=={'FULL_D':1,'FIXED_FIVE_ORIGIN_BLOCKS':3,'AFV_B2_EXACT_ORIGIN_SAMPLE':20}
            and summary.get('production_specified_baseline_full_D_frozen_bank_and_prediction_parity_are_full_D_guard') is True
            and summary.get('bounded_sample_is_not_full_D_frozen_oracle_proof') is True
            and summary.get('host_eligibility_granted') is False
            and summary.get('complete_unselected_regression',{}).get('receipt')==evidence[suite_rel]
            and summary.get('sample_plan_identity')==evidence['AFSPEEDC_SAMPLE_DECLARATION.json'],
            'Exact bounded 12-case/24-arm byte proof and full-D production guards required')
    require(campaign.get('schema')=='AFSPEEDC_OWNED_MEASUREMENT_CAMPAIGN_RESULT_V1'
            and campaign.get('state')=='PASS' and len(campaign.get('completed',[]))==12
            and {r.get('case') for r in campaign['completed']}==set(CASE_NAMES)
            and all(r.get('exit_code')==0 and r.get('state')=='PASS' for r in campaign['completed'])
            and campaign.get('pending')==[] and campaign.get('source_unchanged') is True
            and campaign.get('source_identities_before')==campaign.get('source_identities_after')
            and campaign.get('signals_sent') is False and campaign.get('max_actual_active_lanes',4)<=3,
            'Complete, reaped, source-identical engineering campaign required')
    for row in manifest.get('selected_case_receipt_identities',[]):
        checked=checked_relative(str(Path(row['receipt']['path']).relative_to(root)),row['receipt'])
        evidence['case/'+row['case']]=checked
    require({r.get('case') for r in manifest.get('selected_case_receipt_identities',[])}==set(CASE_NAMES)
            and len(manifest['selected_case_receipt_identities'])==12,'Exact twelve case receipt identities required')
    effective=read(root/'EFFECTIVE_SPEC_IDENTITY_C.json')
    require(effective.get('schema')=='AFSPEED_ENGINEERING_EFFECTIVE_SPEC_V5'
            and effective.get('sample_plan_identity')==evidence['AFSPEEDC_SAMPLE_DECLARATION.json']
            and set(effective.get('components',{}))=={'SPEC.md','SPEC_IDENTITY.json',
                'ENGINEERING_ADDENDUM_1_PRE_FULL_D.md','ENGINEERING_ADDENDUM_2_PASS_CACHE.md',
                'ENGINEERING_ADDENDUM_3_AFSPEEDB_BOUNDED_SUPPORT.md',
                'ENGINEERING_ADDENDUM_4_AFSPEEDC_AFV_B2_SAMPLE.md'},
            'Current V5 predeclared support identity required')
    for name,item in effective.get('components',{}).items():evidence['spec/'+name]=checked_relative(name,item)
    evidence['delivery_manifest']=expected_manifest
    source['SET5/eviction_patch.py']=expected_eviction
    runtime={name:source[name] for name in ('integration.py','speed_core.py','SET5/eviction_patch.py')}
    return dict(schema='FORECAST_BINDING9_SPEED_OVERLAY_BINDING_V1',root=str(root),source_inventory=source,
        evidence_inventory=evidence,runtime_sources=runtime,
        external_receipts={'clean_speed_suite':evidence[suite_rel],'twelve_case_byte_summary':evidence[summary_rel],
                           'campaign_plan':evidence[plan_rel],'campaign_result':evidence[campaign_rel]},
        speed_unselected_test_count=197,comparison_scope_counts=summary['comparison_scope_counts'],
        clock_coverage_parity_identity_before_T5_overlap_resources_unchanged=True,
        specified_baseline_full_D_bank_byte_check_and_prediction_parity_unchanged=True,
        eviction_installed_before_adapter_copy=True,restores_on_normal_exit_and_exception=True,
        historical_B_support_inactive_by_AFV_B2=True,host_eligibility_granted=False)


def speed_source_inventory():
    return verify_speed_delivery()['source_inventory']


@contextmanager
def install_speed_overlay(binding):

    require(binding==verify_speed_delivery(),'Committed/released speed binding drift')
    path=SPEED_ROOT/'integration.py';row=binding['runtime_sources']['integration.py']
    actual,data=metadata(path,collect=True);require(actual==row,'Integration changed before compile')
    module=types.ModuleType('_forecast_binding9_speed_integration');module.__file__=str(path)
    previous=sys.modules.get(module.__name__);sys.modules[module.__name__]=module
    try:
        exec(compile(data,str(path),'exec'),vars(module))
        with module.install() as proof:
            require(proof.get('speed_core')==binding['runtime_sources']['speed_core.py']
                    and proof.get('reviewed_eviction')==binding['runtime_sources']['SET5/eviction_patch.py']
                    and proof.get('gate_or_parity_functions_replaced') is False,
                    'Exact speed factory/eviction runtime proof required')
            yield proof
    finally:
        if previous is None:sys.modules.pop(module.__name__,None)
        else:sys.modules[module.__name__]=previous
