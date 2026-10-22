'Project saved numerical fields into export records.'
from copy import deepcopy
from ..input_checks import require, canonical
from .specified_scalars import validate_binding
from ..numeric.slots import native_census


def resolve(document, pointer):
    require(pointer == '' or pointer.startswith('/'), 'Invalid JSON pointer')
    value = document
    for part in pointer.split('/')[1:] if pointer else []:
        key = part.replace('~1', '/').replace('~0', '~')
        value = value[int(key)] if isinstance(value, list) else value[key]
    return value


def row(slot_id, scope, document, pointer, source, view, receipt, *, identity=None):
    return dict(slot_id=slot_id, scope=scope, identity=deepcopy(identity),
                view=view, source_receipt_sha256=receipt,
                timestamp_checks=dict(source, pointer=pointer),
                value=deepcopy(resolve(document, pointer)))


def project(record, rd, *, qualifications, qualification_source, census,
            numeric_source, rd_source, original_source, original_document, receipts):

    require(record['schema'] == 'AP_SCORING_NATIVE_NUMERIC_V1', 'Numeric source schema')
    require(rd['schema'] == 'RD_SCORING_NOTICE_SCALAR_PROJECTION_V1', 'notice_delays evaluator source schema')
    require(len(record['forest_slots']) == 110, 'Forest census')
    require([x['identity'] for x in record['forest_slots']] == census['forest'], 'Forest identity/order drift')
    require(record['native_comparison_census'] == native_census(record['current']), 'Complete native census drift')
    require(len(rd['notice_conditions']) == 18 and len(rd['joint_contrasts']) == 3, 'notice_delays complete census')
    pairs = [('L14', 'M_notice'), ('L_Laz', 'M_notice'), ('L_chen_notice', 'M_notice')]
    require([(r['arm'], r['reference']) for r in rd['joint_contrasts']] == pairs, 'Joint contrast identity/order drift')
    expected = [(arm, ref, origin, delay) for arm, ref in pairs
                for origin in ('specified', 'aligned') for delay in (5, 15, 60)]
    require([(r['arm'], r['reference'], r['origin'], r['delay_minutes'])
             for r in rd['notice_conditions']] == expected, 'Condition identity/order drift')
    require(record['source_receipt_sha256'] == receipts['r2'], 'Numeric/source receipt identity drift')


    require(rd['provenance']['source_receipt_sha256'] == receipts['specified_notice'], 'notice_delays specified receipt drift')
    validate_binding(record, rd, qualifications, numeric_source, rd_source, receipts)
    require(canonical(original_document) == canonical(record['original_news_214']),
            'Original214 attachment document/value drift')
    original = original_document
    require(original['days'] == 214 and len(original['contrasts']) == 2, 'Missing original attachment')
    require(original['source_receipt_sha256'] == receipts['original'], 'Original/source receipt drift')
    require({'RS8', 'N0', 'original_callable', 'original_destination'} <= set(original), 'Original native fields/provenance missing')
    require('limitations' in record, 'Explicit sourced limitations required')
    require([(r['arm'], r['reference']) for r in original['contrasts']] ==
            [('L_count', 'M'), ('L_chen', 'M')], 'Original contrast scope drift')
    out = []
    def numeric(slot, scope, pointer, view='R2_NEWS_135_NOTICE_61', identity=None):
        out.append(row(slot, scope, record, pointer, numeric_source, view,
                       receipts['r2'], identity=identity))
    for i, entry in enumerate(record['forest_slots']):
        numeric(entry['identity']['slot_id'], 'SPECIFIED_FOREST',
                '/forest_slots/' + str(i), entry['identity']['view'], entry['identity'])
    for entry in record['native_comparison_census']:
        numeric(entry['slot_id'], 'COMPLETE_NATIVE_CENSUS', entry['pointer'], entry['view'], entry['identity'])
    for task in ('news', 'notice'):
        numeric('primary-reading/' + task, 'SPECIFIED_PRIMARY', '/tasks/' + task)
        numeric('propagated-reading/' + task, 'FROZEN_PROPAGATION', '/propagation/details/' + task)
        numeric('original-primary-seed/' + task, 'ORIGINAL_PRIMARY_SEED', '/original_seed_native/' + task)
        for i, qualification in enumerate(qualifications['tasks'][task]):
            out.append(row('specified-qualification/' + task + '/' + str(i),
                'SPECIFIED_SCALAR_QUALIFICATION', qualifications, '/tasks/' + task + '/' + str(i),
                qualification_source, 'NEWS_ISSUE_135' if task == 'news' else 'NOTICE_TARGET_61',
                receipts['r2'] if task == 'news' else receipts['specified_notice'], identity={k: qualification[k] for k in ('arm', 'reference')}))
    for key in ('propagation', 'specified_reading_2000', 'stages', 'operational', 'deviations',
                'fill_clock', 'declarations', 'clk8', 'clipping', 'score_report_native', 'batch_native',
                'cps8_selection', 'dly8_r8', 'optional'):
        numeric('metadata/' + key, 'SCIENTIFIC_CONTEXT', '/' + key)
    for i, condition in enumerate(rd['notice_conditions']):
        out.append(row('notice-condition/%02d' % i, 'SPECIFIED_CORRECTED_NOTICE', rd,
                       '/notice_conditions/' + str(i), rd_source, 'NOTICE_TARGET_61', receipts['specified_notice'],
                       identity={k: condition[k] for k in ('arm', 'reference', 'origin', 'delay_minutes')}))
    for i, joint in enumerate(rd['joint_contrasts']):
        out.append(row('notice-joint/%d' % i, 'JOINT_WEAKER_READING', rd,
                       '/joint_contrasts/' + str(i), rd_source, 'NOTICE_TARGET_61', receipts['specified_notice'],
                       identity={k: joint[k] for k in ('arm', 'reference')}))


    out.append(row('original-news-214/attachment', 'ORIGINAL_WINDOW_ATTACHMENT', original,
                   '', original_source, 'ORIGINAL_NEWS_214', receipts['original']))
    for i, contrast in enumerate(original['contrasts']):
        out.append(row('original-news-214/%d' % i, 'ORIGINAL_WINDOW_ATTACHMENT', original,
                       '/contrasts/' + str(i), original_source, 'ORIGINAL_NEWS_214', receipts['original'],
                       identity={k: contrast[k] for k in ('arm', 'reference')}))
    require(len({r['slot_id'] for r in out}) == len(out), 'Export slot identity collision')
    return dict(schema='AP_SCORING_OFFICIAL_RESULTS_V1', rows=out,
                original_attachment_outside_primary_forest=True,
                production_authority=False, limitations=deepcopy(record['limitations']))
