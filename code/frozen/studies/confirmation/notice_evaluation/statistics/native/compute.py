'Compute notice comparisons on complete scoring grids.'
import os
from copy import deepcopy
from evaluator.validation import require, validate_joint, pinned_joint_schema
from evaluator import _joint_comparisons as J
from . import reader as R
from . import delays as D


def condition_views(records, correction, *, gate, M):
    require(os.environ.get('SCORING_PHASE', 'prepare') in ('accept', 'source_runtime'),
            'Prepare: native view construction forbidden')
    main, view, substitutions = R.primary_view(records['seal'], correction)
    R.verify_prediction_rows(M, main, view, correction, gate)
    delayed, receipt = D.specified_delays(records)
    specified = {'5': records['seal']}
    aligned = {'5': view}
    views = {'5': dict(specified=main['predictions'], aligned=view['predictions'],
                       substitutions=substitutions)}
    for delay in (15, 60):
        a, b, substitutions = D.delayed_view(records['seal'], delayed[str(delay)],
                                             correction['delay_extension'], delay)
        D.verify_delay_rows(M, a, b, correction['delay_extension'], delay, gate)
        specified[str(delay)], aligned[str(delay)] = a, b
        views[str(delay)] = dict(specified=a['predictions'], aligned=b['predictions'],
                                substitutions=substitutions)
    return main, specified, aligned, views, receipt


def compute_notice(M, records, manifest, correction, specified_record, evidence, *, gate):
    require(os.environ.get('SCORING_PHASE', 'prepare') in ('accept', 'source_runtime'),
            'Prepare: numerical computation forbidden')
    gate()
    R.require_official_score(manifest)
    require(evidence['inputs'] == manifest['inputs'] and evidence['frozen_2000_parity'] == 'PASS'
        and evidence['current_draws'] == 100000 and specified_record['identities']['source_receipt_sha256']
        == manifest['inputs']['score_receipt']['sha256'], 'Specified reproduction timestamp_checks drift')
    main, specified, aligned, views, delay_receipt = condition_views(records, correction, gate=gate, M=M)
    permit = M.L.permit(M.sc, records['seal'])
    original = M.BS.task_parity(M.native, M.sc, permit, 'notice', main,
                              manifest['inputs']['seal'], records['score_receipt']['files'])
    original.update(R.specified_daily_parity(M, records['seal'], records['score_receipt']['files']))
    families, proofs = D.compute_delays(M, records['seal'], specified, aligned,
        records['batch']['DLY8']['primary'], gate, main_reference=specified_record['tasks']['notice'])
    gate()
    return dict(schema='RD_SCORING_NOTICE_NUMERICAL_KERNEL_V1', families=families, proofs=proofs,
        specified_official_parity=original, views=views, specified_dly8=delay_receipt,
        specified_main_as_5='MAIN_A0', corrected_main_as_5='CORRECTED_DELTA0',
        literal_dly8_deltas=[15, 60], production_authority=False)


def joint_from_native(M, families, authorities, bindings, *, alert, schema):
    'Use each comparison family and its recorded seed results.'
    require(os.environ.get('SCORING_PHASE', 'prepare') in ('accept', 'source_runtime'),
            'Prepare: numerical evaluation forbidden')
    expected = {o+'/'+str(d) for o in J.ORIGINS for d in J.DELAYS}
    require(set(families) == set(authorities) == expected, 'Six native-family census')
    schema = pinned_joint_schema(schema)
    rows = []
    for origin in J.ORIGINS:
        for delay in J.DELAYS:
            key = origin+'/'+str(delay)
            rows += J.reading_from_family(M, families[key], origin, delay, authorities[key], alert=alert)
    record = J.build_joint_record(rows, deepcopy(bindings))
    validate_joint(record, schema)
    return record
