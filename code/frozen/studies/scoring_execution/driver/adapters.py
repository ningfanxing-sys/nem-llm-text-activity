'Validate numerical entry points and serialize their result records.'
from copy import deepcopy
import csv
import io
import json
from pathlib import Path
from source_bytes import CoreStop, checked, document, identity, require


def exclusive_json(path, value):
    with Path(path).open('x', encoding='utf-8') as handle:
        json.dump(value, handle, ensure_ascii=False, indent=2, allow_nan=False)
        handle.write('\n')
    return identity(path)


def official_certificate(association, original, r2, execution):

    import sys
    module = sys.modules.get(type(association).__module__)
    require(module is not None and module.ACTIVE is association
            and module.Association is type(association), 'K2 installed Association required')
    certificate = association.official_views(original, r2, execution)
    association._check_official_score(certificate)
    require(certificate['view_inputs'] == dict(original=original, r2=r2, execution=execution),
            'K3 dual official view/certificate mismatch')
    require(original['score_receipt'] != r2['score_receipt'], 'K5 original receipt reused for R2')
    return certificate


def ap_entry(entry, association, request, scientific_scope):
    return entry.ap5_science(association=association, request=request, argv=[],
                             scientific_scope=scientific_scope)


def rd_entry(entry, association, request, scientific_scope):
    return entry.rd_joint(association=association, request=request, argv=[],
                          scientific_scope=scientific_scope)


def independent_eligibility(verifier, association, eligibility, numeric_source, rd_source, receipts):

    result = verifier(association=association, eligibility=eligibility,
        numeric_source=numeric_source, rd_source=rd_source, receipts=receipts)
    require(isinstance(result, dict) and result.get('schema') == 'C_SCORING_G42_VERIFIED_ASSOCIATION_V1'
        and result.get('numeric_source') == numeric_source and result.get('rd_source') == rd_source
        and result.get('receipts') == receipts and result.get('eligibility') == eligibility,
        'K6 independent eligibility association mismatch')
    return result


def original_attachment(value, original_receipt):
    require(value['days'] == 214 and value['source_receipt_sha256'] == original_receipt['sha256']
        and [(x['arm'], x['reference']) for x in value['contrasts']] == [('L_count', 'M'), ('L_chen', 'M')]
        and {'RS8', 'N0', 'original_callable', 'original_destination'} <= set(value),
        'K5 score_news_full_window native attachment/receipt missing or substituted')
    return deepcopy(value)


def full_census(record, rd):
    require(record['bootstrap_draws'] == 100000, 'K4 native B100000 required')
    require(len(record['forest_slots']) == 110, 'K4 forest110 missing')
    require(len(record['tasks']['news']['contrasts']) == 2
        and len(record['tasks']['notice']['contrasts']) == 3, 'K4 five primary census')
    require(len(rd['notice_conditions']) == 18 and len(rd['joint_contrasts']) == 3,
        'K4 RD18/3 missing')
    require(record.get('specified_reading_2000') is not None, 'K4 B2000 parity record missing')


def export_values(projection, formats, record, rd, kwargs, sens, attachment, out):

    full_census(record, rd)
    projected = projection.project(record, rd, **kwargs)
    rows = projected['rows']

    rows.append(dict(slot_id='SENS35/document', scope='SENSITIVITY_ONLY', identity=None,
        view='UNEXPOSED_NEWS_100_NOTICE_50', source_receipt_sha256=sens.get('receipt',sens['identity'])['sha256'],
        timestamp_checks=dict(sens['identity'], pointer=''), value=deepcopy(sens['document'])))
    for task, task_result in sens['document'].get('tasks',{}).items():
        for tag, family in task_result['series'].items():
            for i, value in enumerate(family['reports']):
                rows.append(dict(slot_id='SENS35/'+task+'/'+tag+'/'+str(i),scope='SENSITIVITY_ONLY',
                    identity=dict(task=task,series=tag,arm=value['arm'],reference=value['reference']),
                    view='UNEXPOSED_NEWS_100_NOTICE_50',source_receipt_sha256=sens['receipt']['sha256'],
                    timestamp_checks=dict(sens['identity'],pointer='/tasks/'+task+'/series/'+tag+'/reports/'+str(i)),
                    value=deepcopy(value)))
    require(len({r['slot_id'] for r in rows}) == len(rows), 'K7 export slot collision')
    require(set(sens['expected_slots']) <= {r['slot_id'] for r in rows}, 'K7 specified slots omitted')
    out = Path(out)
    out.mkdir(parents=True, exist_ok=False)
    payloads = {'OFFICIAL_RESULTS.json': (json.dumps(projected, ensure_ascii=False,
        indent=2, allow_nan=False)+'\n').encode(), 'OFFICIAL_RESULTS.csv': formats.csv_bytes(projected),
        'OFFICIAL_RESULTS_source.md': formats.chinese_bytes(projected),
        'SPECIFIED_NEWS_214.json': (json.dumps(attachment, ensure_ascii=False,
        indent=2, allow_nan=False)+'\n').encode()}

    attachment_rows = dict(projected, rows=[r for r in rows if r['scope'] == 'ORIGINAL_WINDOW_ATTACHMENT'])
    payloads['SPECIFIED_NEWS_214.csv'] = formats.csv_bytes(attachment_rows)
    payloads['SPECIFIED_ORIGINAL_NEWS_214_source.md'] = formats.chinese_bytes(attachment_rows)
    for name, data in payloads.items():
        with (out/name).open('xb') as handle:
            handle.write(data)
    receipt = dict(schema='MINRUN_EXPORT_RECEIPT_V1', files=[identity(out/n) for n in payloads],
        slot_ids=[r['slot_id'] for r in rows], original_attachment_outside_primary_forest=True)
    exclusive_json(out/'EXPORT_RECEIPT.json', receipt)
    return receipt


class NativeAdapters:

    def __new__(cls, control, sources):
        from backend import NativeAdapters as Backend
        return Backend(control, sources)


def ap_native_build(bridge, association, contract, scientific_scope):

    from types import SimpleNamespace
    P = bridge.parent(association)
    runtime = bridge.Runtime(association, contract)
    validator = __import__('runtime_entries')._entry(association, 'author_validation')[0]
    runtime.author_validator = validator
    old_dependencies, old_assembly, old_build = P.dependencies, P.assemble_output, P.build
    def dependencies(*args, **kwargs):
        kwargs['consumer'] = False
        return old_dependencies(*args, **kwargs)
    def assemble(*args, **kwargs):
        return bridge.assemble(association=association, args=args, kwargs=kwargs,
            scientific_contract=contract, author_validator=validator)
    P.dependencies, P.assemble_output = dependencies, assemble
    try:
        runtime.reverify_official_views()
        with bridge.specified_scope(P, runtime) as producer:
            with scientific_scope(producer, contract):
                result = P.build(Path(contract['manifest']['path']), contract['manifest']['sha256'],
                    chunk=contract['chunk'], gate=P.resource_gate, synthetic=False, production=True)
        runtime.reverify_official_views()
        return result
    finally:
        P.dependencies, P.assemble_output, P.build = old_dependencies, old_assembly, old_build


def rd_native_projection(api, record, specified_task, provenance, schema, project_root):

    import os
    from types import FunctionType
    require(os.environ.get('SCORING_PHASE') == 'source_runtime', 'K2 actual notice_delays phase required')
    require(type(provenance.get('synthetic_only')) is bool, 'K2 explicit notice_delays provenance required')
    root = Path(project_root).resolve()
    for item in [*record['bindings'].values(), *provenance['native_rows'].values(),
                 provenance['specified_record']]:
        payload = Path(item['path']).read_bytes()
        import hashlib
        require(hashlib.sha256(payload).hexdigest() == item['sha256'], 'K6 native row/binding bytes drift')
        if 'bytes' in item:
            require(len(payload) == item['bytes'], 'K6 native row/binding length drift')
        require(Path(item['path']).resolve().is_relative_to(root), 'K6 native timestamp_checks outside project')
    require(document(provenance['specified_record'])['tasks']['notice'] == specified_task,
            'K6 actual specified-task pointer mismatch')
    def real_boundary(path, prov):
        require(Path(path).resolve() == root and prov == provenance, 'K6 notice_delays native input_checks mismatch')
        return root


    fn = FunctionType(api.project_joint.__code__,
        dict(api.project_joint.__globals__, _artificial_boundary=real_boundary),
        api.project_joint.__name__, api.project_joint.__defaults__, api.project_joint.__closure__)
    fn.__kwdefaults__ = api.project_joint.__kwdefaults__
    result = fn(record, specified_task, provenance, schema, fixture_root=root)
    require(result['production_authority'] is False and result['external_eligibility'] == 'NOT_GRANTED',
            'K6 notice_delays projection cannot grant own eligibility')
    return result
