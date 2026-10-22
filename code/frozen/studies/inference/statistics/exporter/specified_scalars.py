'Apply the frozen predicates to scalar comparison records.'
from copy import deepcopy
import json
from pathlib import Path
from ..input_checks import artificial_accept, require, source_identity, json_bytes

PAIRS = {'news': [('L_count', 'M'), ('L_chen', 'M')],
         'notice': [('L14', 'M_notice'), ('L_Laz', 'M_notice'), ('L_chen_notice', 'M_notice')]}


def validate_binding(record, rd, qualifications, numeric_source, rd_source, receipts):

    require(qualifications['schema'] == 'AP_SCORING_SPECIFIED_SCALARS_V1', 'Scalar schema')
    require(qualifications['numeric_source'] == numeric_source and
            qualifications['rd_source'] == rd_source, 'Scalar source identity drift')
    require(qualifications['source_receipt_sha256'] == receipts['r2'], 'Scalar receipt drift')
    require(rd['provenance']['specified_record'] == numeric_source and
            rd['provenance']['source_receipt_sha256'] == receipts['specified_notice'],
            'notice_delays specified numeric association drift')
    require([(c['arm'], c['reference']) for c in rd['joint_contrasts']] == PAIRS['notice'],
            'Notice joint identity/order drift')
    for task, pairs in PAIRS.items():
        rows = qualifications['tasks'][task]
        originals = record['tasks'][task]['contrasts']
        require([(c['arm'], c['reference']) for c in originals] == pairs, 'Specified primary census drift')
        require([(c['arm'], c['reference']) for c in rows] == pairs, 'Scalar census drift')
        for i, (original, item) in enumerate(zip(originals, rows)):
            pointer = '/tasks/' + task + '/contrasts/' + str(i)
            task_receipt = receipts['r2'] if task == 'news' else receipts['specified_notice']
            timestamp_checks = dict(numeric_source, pointer=pointer, source_receipt_sha256=task_receipt)
            require(item['input_authority'] == timestamp_checks, 'Scalar pointer drift')
            require(item['input'] == original and item['alert'] == record['tasks'][task]['alert'],
                    'Scalar input/alert drift')
            for field, schema in [('reliable_verdict', 'TABLE_RESULTS_DEC9B_RELIABLE_SUPPORT_V1'),
                                  ('seven_day_definedness', 'TABLE_RESULTS_A8_D6_DEFINEDNESS_V1'),
                                  ('specified_primary_seed', 'TABLE_RESULTS_A8_D2_ORIGINAL_SEED_V1')]:
                require(item[field]['schema'] == schema, 'Missing frozen scalar predicate output')
            seed = item['specified_primary_seed']
            require(seed['primary_class'] == original['class'] and seed['class'] == original['three_seed_class']
                    and seed['effect_percent'] == original['three_seed_effect'], 'Scalar seed input drift')
            require(seed['source_pointer'] == pointer and seed['timestamp_checks'] == dict(
                path=numeric_source['path'], sha256=numeric_source['sha256'],
                source_receipt_sha256=task_receipt, pointer=pointer), 'Scalar seed timestamp_checks drift')
            if task == 'notice':
                require(seed == rd['joint_contrasts'][i]['specified_primary_seed'], 'Notice seed must reuse notice_delays output')


def evaluate_artificial(record, rd, *, numeric_source, rd_source, receipts,
                        evaluator, runtime, fixture_root):

    root = artificial_accept(fixture_root)
    require(runtime.final_reviewed_contract is not None and evaluator.final_reviewed_contract is not None,
            'Pending reviewed C/notice_delays scalar capability')
    runtime.check_sources_and_authority()
    evaluator.check_sources_and_authority()
    runtime.reverify_official_views()
    runtime.verify_rd_eligibility(rd_source, numeric_source, receipts)


    for document, source in ((record, numeric_source), (rd, rd_source)):
        path = Path(source['path'])
        require(path.is_relative_to(root), 'Artificial source outside fixture')
        verified = runtime.checked_payload(source)
        require(verified == document and source_identity(path) == source and
                json.loads(path.read_bytes()) == document, 'Scalar verified payload drift')
    runtime.verify_specified_association(numeric_source, rd_source, receipts)
    require(rd['provenance']['specified_record'] == numeric_source and
            rd['provenance']['source_receipt_sha256'] == receipts['specified_notice'],
            'Pending exact notice_delays specified association')
    out = dict(schema='AP_SCORING_SPECIFIED_SCALARS_V1', numeric_source=deepcopy(numeric_source),
               rd_source=deepcopy(rd_source), source_receipt_sha256=receipts['r2'], tasks={},
               production_authority=False)
    for task, pairs in PAIRS.items():
        native = record['tasks'][task]
        require(type(native['alert']) is bool, 'Specified alert type')
        require([(c['arm'], c['reference']) for c in native['contrasts']] == pairs, 'Specified scope drift')
        rows = []
        for i, contrast in enumerate(native['contrasts']):
            evaluator.validate_scalar(contrast)
            pointer = '/tasks/' + task + '/contrasts/' + str(i)
            task_receipt = receipts['r2'] if task == 'news' else receipts['specified_notice']
            timestamp_checks = dict(path=numeric_source['path'], sha256=numeric_source['sha256'],
                             source_receipt_sha256=task_receipt)
            seed = (deepcopy(rd['joint_contrasts'][i]['specified_primary_seed']) if task == 'notice'
                    else evaluator.specified_primary_seed(contrast, native, timestamp_checks=timestamp_checks,
                                                            source_pointer=pointer))
            rows.append(dict(arm=contrast['arm'], reference=contrast['reference'],
                input=deepcopy(contrast), alert=native['alert'],
                input_authority=dict(numeric_source, pointer=pointer, source_receipt_sha256=task_receipt),
                reliable_verdict=evaluator.reliable_support(contrast, native['alert'], joint=False),
                seven_day_definedness=evaluator.seven_day_definedness(contrast, joint=False),
                specified_primary_seed=seed))
        out['tasks'][task] = rows
    validate_binding(record, rd, out, numeric_source, rd_source, receipts)
    evaluator.check_sources_and_authority()
    runtime.check_sources_and_authority()
    runtime.reverify_official_views()
    return out


def write_artificial(qualifications, output, *, fixture_root, reverify):
    root = artificial_accept(fixture_root)
    path = Path(output)
    require(path.is_absolute() and path.resolve() == path and path.is_relative_to(root)
            and not path.exists(), 'Fresh artificial scalar companion required')
    reverify()
    data = json_bytes(qualifications)
    with path.open('xb') as handle:
        handle.write(data)
    reverify()
    return source_identity(path)
