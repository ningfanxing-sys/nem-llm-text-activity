
'Save the validated forecast input metadata.'
import os
import sys
import datetime as dt
from pathlib import Path
sys.dont_write_bytecode=True
sys.path.insert(0,str(Path(__file__).resolve().parent/'code'))
from common import *

def acceptance(path, schema, source_map, tests, mapping):

    p=Path(path).resolve()
    require(p.is_relative_to(OUT) and p.is_file() and not Path(path).is_symlink(),
            'Acceptance must be an exact regular metadata file in forecast_hashes')
    value=read_json(p)
    require(value.get('schema')==schema and value.get('state')=='ACCEPTED_FOR_SOURCE_FREEZE',
            'Fresh acceptance with the specified schema/state required')
    require(value.get('reviewed_sources')==source_map and value.get('test_receipt')==identity(tests)
            and value.get('root_mapping')==mapping,'Acceptance does not cover exact revised package')
    try:
        recorded=dt.datetime.fromisoformat(value['recorded_utc'].replace('Z','+00:00'))
    except (KeyError,TypeError,ValueError,AttributeError) as exc:
        raise RuntimeError('Acceptance needs actual dated UTC evidence') from exc
    require(recorded.utcoffset()==dt.timedelta(0) and
            recorded>=dt.datetime.fromisoformat('2026-10-05T06:25:00+11:00'),
            'Acceptance must be dated UTC after the binding AEDT Revision')
    require(isinstance(value.get('owner'),str) and bool(value['owner'].strip()),'Acceptance owner required')
    if schema=='FORECAST_BINDING5_REVIEW_ACCEPTANCE_V1':
        require(value.get('independent') is True and value.get('blocking_items_resolved')==[1,2,3,4,5]
                and value.get('review2_blocking_items_resolved')==[1,2]
                and value.get('review3_blocking_items_resolved')==[1]
                and value.get('review4_blocking_items_resolved')==[1],
                'Fresh independent acceptance must resolve REVIEW through REVIEW4 blockers')
        report=checked(value['review_report'])
        require(report.is_relative_to(OUT) and report.suffix=='.md' and
                report not in (OUT/'REVIEW_IMPLEMENTATION_CHECK_20261005_source.md',OUT/'REVIEW2_IMPLEMENTATION_CHECK_20261005_source.md',
                               OUT/'REVIEW3_IMPLEMENTATION_CHECK_20261005_source.md',OUT/'REVIEW4_IMPLEMENTATION_CHECK_20261005_source.md'),
                'Historical SET FIRST reports cannot be set acceptance')
    else:
        require(value.get('scoring_interface')==identity(OUT/'SCORING_REPORTING_PATH.md') and
                value.get('scientific_eligibility_changed') is False,
                'Consumer owner must accept exact additive interface without changing specified eligibility')
    return identity(p)

def create(review_acceptance, consumer_acceptance):
    require(os.environ.get('FORECAST_BINDING_SOURCE_FREEZE')=='1','Source-only freeze action')
    resources()
    require(not (OUT/'CODE_FREEZE.json').exists(),'Never replace an forecast_hashes code freeze')
    from anchor_patch import source_ast_receipt
    from run_bound_forecasts import affected_arms
    from forecast_inputs import root_mapping_contract, verify_root_mapping
    ast_receipt=source_ast_receipt(X2/'notice_label_adapter.py',X2/'features_adapter.py')
    result=read_json(AD/'RESULT.json'); arms=affected_arms(result)
    tests_path=OUT/'TEST_RESULTS_FORECAST_BINDING5.json'
    tests=read_json(tests_path); source=read_json(OUT/'SOURCE_ANCHOR_CHECK.json')
    require(tests['state']=='PASS_SYNTHETIC_TESTS' and tests.get('task')=='FORECAST_BINDING5'
            and tests['failures']==0 and tests['errors']==0 and tests['skipped']==0
            and tests.get('numerical_processes')==1 and tests.get('full_suite_runs')==1
            and tests.get('review_blockers_covered')==[1,2,3,4,5]
            and tests.get('review2_blockers_covered')==[1,2]
            and tests.get('review3_blockers_covered')==[1] and tests.get('review4_blockers_covered')==[1]
            and tests.get('activity_guard_covered') is True and tests.get('before_t5_guard_covered') is True
            and tests.get('production_state_paths_or_locks_probed') is False,
            'Current passing FORECAST_BINDING5 tests, activity and before-T5 guard coverage required')
    require(source['state']=='PASS_SOURCE_ONLY_ANCHOR_PARITY' and all(source['checks'].values()),'Source parity required')


    current={str(p.relative_to(OUT)):sha(p) for p in sorted([*OUT.joinpath('code').glob('*.py'),*OUT.joinpath('tests').glob('*.py'),OUT/'freeze_forecast_binding.py'])}
    require(tests['own_code_sha256']==current,'Final FORECAST_BINDING5 code changed since its sole full suite')
    files=[*OUT.joinpath('code').glob('*.py'),*OUT.joinpath('tests').glob('*.py'),OUT/'freeze_forecast_binding.py',
           OUT/'SPEC.md',OUT/'HOST_PROCEDURE.md',OUT/'SCORING_REPORTING_PATH.md',
           OUT/'ADDENDUM_A8_SPECIFICATION_3_PAPER.md',OUT/'ACTIVATION.template.json',
           OUT/'TEST_RESULTS.json',OUT/'TEST_RESULTS_FORECAST_BINDING2.json',OUT/'TEST_RESULTS_FORECAST_BINDING3.json',
           OUT/'TEST_RESULTS_FORECAST_BINDING4.json',tests_path,
           OUT/'SOURCE_ANCHOR_CHECK.json',OUT/'REPORT.md',
           OUT/'SOURCE_ACTIVITY_CHECK_FORECAST_BINDING4.json',
           OUT/'validation_inputs/activity_guard_92_test_snapshot.py',
           OUT/'REVIEW_IMPLEMENTATION_CHECK_20261005_source.md',OUT/'REVIEW2_IMPLEMENTATION_CHECK_20261005_source.md',
           OUT/'REVIEW3_IMPLEMENTATION_CHECK_20261005_source.md',OUT/'REVIEW4_IMPLEMENTATION_CHECK_20261005_source.md',
           OUT/'TEST_BOOTSTRAP_NOTE_FORECAST_BINDING2.json']
    mapping=root_mapping_contract()
    verify_root_mapping(mapping)
    source_map={str(p.relative_to(OUT)):sha(p) for p in sorted(set(files))}
    review=acceptance(review_acceptance,'FORECAST_BINDING5_REVIEW_ACCEPTANCE_V1',source_map,tests_path,mapping)
    consumer=acceptance(consumer_acceptance,'FORECAST_BINDING5_CONSUMER_ACCEPTANCE_V1',source_map,tests_path,mapping)


    from check_prescoring_state import capture_timestamp_identity, prove_before_t5
    timestamp_pin=capture_timestamp_identity(mapping['before_t5_guard'])
    before_t5_proof=prove_before_t5(mapping['before_t5_guard'],timestamp_pin)
    ad_files=[AD/name for name in ('SPEC.md','NOTICE_DIFF.json','CLOCK_PATHS.md','OPTIONS_source.md','RESULT.json','REPORT.md',
              'SOURCE_DECISION_RULE_20261005.md','diagnose.py','D_FEATURE_DIFF.json','LAZ_FEATURE_DIFF.json',
              'OUTPUT_MANIFEST.json')]
    ad_files += [AD/(arm+'_changed_keys.parquet') for arm in arms]
    directories=[B/'code',X2,confirmation/'code',Q/'notice_records/source_relations/assembler',Q/'notice_records/closing_windows/assembler',
                 Q/'notice_records/event_assembly',PROJ/'notice_assembly',Q/'parser_checks/parser_review']
    require(all(p.is_dir() for p in directories),'Missing frozen projection dependency directory')
    dependencies=[p for directory in directories for p in directory.glob('*.py')]
    dependencies += [PROJ.parent/'notice_forecasting/nw_notices.py',
                     Q/'notice_extraction/scope.jsonl',Q/'notice_extraction/results_1_3/labels.parquet']
    value=dict(state='FORECAST_BINDING_CODE_FROZEN_FOR_SOURCE',task='FORECAST_BINDING5',
               files=[identity(p) for p in sorted(set(files))],dependencies=[identity(p) for p in sorted(set(dependencies))],
               ad_inputs=[identity(p) for p in ad_files],affected_arms=arms,ast_patch_contract=ast_receipt,
               root_mapping=mapping,independent_review=review,consumer_acceptance=consumer,
               timestamp_root_identity=timestamp_pin,before_t5_at_freeze=before_t5_proof,
               models_refitted=0,predictions_run=False,scoring_run=False,
               registration='Separate dated pre-score deviation record; no specification of existing frozen bytes')
    write_json(OUT/'CODE_FREEZE.json',value)
    return value

if __name__=='__main__':
    import argparse
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--source-freeze',action='store_true')
    parser.add_argument('--review-acceptance',type=Path,required=True)
    parser.add_argument('--consumer-acceptance',type=Path,required=True)
    args=parser.parse_args()
    require(args.source_freeze,'Explicit --source-freeze required')
    value=create(args.review_acceptance,args.consumer_acceptance)
    print(json.dumps({'state':value['state'],'affected_arms':value['affected_arms']}))
