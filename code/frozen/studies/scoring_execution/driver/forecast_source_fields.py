'List the source-record fields required by forecast validation.'
from forecast_check_helpers import row
from forecast_static_checks import unresolved

AF_COMMON=('reviewed_sources','test_receipt','root_mapping','owner','recorded_utc',
 'delay_overlay_reviewed_sources','delay_overlay_test_receipt','delay_resource_projection','speed_overlay_binding',
 'frozen_delay_sources','deadline_overlay_delivery','deadline_overlay_sources','historical_T4F','specification_authority',
 'review8_decision_authority','final_root_mapping','final_source_interface','final_source_commitment','corrected_delay_scope','calendar_rule')
AF_REVIEW=('independent','review_report','date_delay_joint_validation_reviewed','all_earlier_gates_preserved',
 'month_first_specified_delay_parity_reviewed','exact_delay_coverage_reviewed','single_corrected_seal_reviewed')
AF_CONSUMER=('scoring_interface','scientific_eligibility_changed','corrected_delay_interface_reviewed',
 'specified_and_corrected_readings_reported','joint_weakest_reading_rule_reviewed',
 'primary_seed_only_not_inherited_seed_checks','corrected_seal_must_precede_T5','t5_metadata_payload_split_reviewed')
AM_CONTRACT=('stable','owner_agreed','expected_native_mapping','expected_native_commitment','mapping_identity',
 'commitment_identity','publication_evidence','c_contract','historical_snapshot','T4F_final_rows','OV1_OV2_rows',
 'AF_scientific_source_rows','selected_speed_binding','actual_AF_acceptances','canonical','citations','am_policy',
 'am_policy_identity','blocked_entrypoints')


def sources(native,subject,own,write,out):
    records=[]
    def record(name,action,owner,fields,known,evidence):
        value={k:'PENDING_REAL_OWNER_'+k.upper() for k in fields}
        value.update(known,paper_only=True,independent_acceptance_created=False,evidence=evidence)
        item=write(out/'owner_records'/ (name+'.paper.json'),value)
        records.append(dict(name=name,action=action,owner=owner,paper=item,
            missing_fields=[p for p,v in unresolved(value) if isinstance(v,str) and v.startswith('PENDING_REAL_')],classification='A_OWNER_ACT'))
    def src(p):return row(p,native.sources.bytes(p))
    afsrc=src(native.af_root/'freeze_science.py')
    ovsrc=src(native.project/'studies/confirmation/forecast_hashes/availability_delays/freeze_delay.py')
    record('DRIVER_SOURCE_REVIEW','freeze-science','Final scoped reviewer',
      ('accepted','independent','reviewer','producer','utc'),
      dict(role='DRIVER_AF_CHAIN_FINAL_SOURCE_REVIEW',subject=subject),[src(__import__('pathlib').Path(__file__).parent/'forecast_check_helpers.py')])
    for kind,owner,extra in [('REVIEW','AFREV8B',AF_REVIEW),('CONSUMER','AFCONSACC',AF_CONSUMER)]:
        record('AF_'+kind,'af-source-freeze',owner,AF_COMMON+extra,
               dict(schema='FORECAST_BINDING5_'+kind+'_ACCEPTANCE_V1',state='ACCEPTED_FOR_SOURCE_FREEZE'),
               [afsrc,ovsrc,src(__import__('pathlib').Path(__file__).parent/'forecast_source_contracts.py')])
    policy=native.io.read_json(native.project/'studies/confirmation/notice_constraints/statistics/PREPARE_5/CURRENT_AM3_VERSION.json')
    record('AM3_CONTRACT','am3-source-freeze','AM3DLE',AM_CONTRACT,
       dict(canonical=policy['canonical'],am_policy=policy,am_policy_identity=src(native.project/'studies/confirmation/notice_constraints/statistics/PREPARE_5/CURRENT_AM3_VERSION.json'),blocked_entrypoints=policy['blocked_entrypoints']),
       [src(native.project/'studies/confirmation/notice_constraints/statistics/PREPARE_5/af_final_v2.py')])
    for name,role,owner,fields in [('AM3_SOURCE_ACCEPTANCE','AM3_SOURCE_ACCEPTANCE','AM3DLE',('accepted','owner','subject','utc')),
        ('AM3_PART_B','AM3_INDEPENDENT_PART_B','AM3REV4B',('accepted','independent','reviewer','producer','subject','utc','scientific_checks'))]:
        known=dict(role=role)
        if name=='AM3_PART_B':known['scientific_checks']={k:'PENDING_REAL_REVIEW' for k in
           ('D1_joint_correction_delay','D2_weakest_reading','D3_retained_joint_reporting')}
        record(name,'am3-source-freeze',owner,fields,known,[src(__import__('pathlib').Path(__file__).parent/'forecast_runtime_metadata.py')])
    record('AM3_ATTESTATION','am3-source-freeze','CLERK/source',
       ('source','utc','subject','source_acceptance','part_b','before_T5','no_calendar_deadline','no_production_or_scoring'),
       dict(schema='MINRUN_AM3_SOURCE_ATTESTATION_V1'),[src(__import__('pathlib').Path(__file__).parent/'forecast_runtime_metadata.py')])
    record('AF_ATTESTATION','af-source-freeze','CLERK/source',
       ('batch_finished','dly8_r8_finished','no_fit_or_rebuild_overlap','before_T5','no_scores_seen','recorded_by','recorded_utc'),
       dict(schema='FORECAST_BINDING8_SOURCE_PRE_FREEZE_ATTESTATION_V1',state='AFTER_BATCH_BEFORE_T5'),[ovsrc])
    activation=native.io.read_json(native.af_root/'ACTIVATION.template.json')
    fields=tuple(k for k,v in activation.items() if v is None or v is False or k in ('recorded_by','recorded_utc'))
    known={k:v for k,v in activation.items() if k not in fields and k!='deadline_aedt'}

    fields=tuple(k for k in fields if k!='deadline_aedt')
    record('AF_ACTIVATION','af-execute','AF9/CLERK',fields,known,[src(native.af_root/'forecast_wrapper.py'),src(native.af_root/'ACTIVATION.template.json')])
    return records
