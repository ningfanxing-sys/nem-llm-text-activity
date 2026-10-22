'Write the specified numerical outputs for synthetic tests.'
from pathlib import Path
from ..input_checks import artificial_accept, require, source_identity, json_bytes


def write_artificial(record, evidence, output, *, fixture_root, reverify):
    root = artificial_accept(fixture_root)
    out = Path(output)
    require(out.is_absolute() and out.resolve() == out and out.is_relative_to(root)
            and not out.exists(), 'Fresh artificial numeric destination required')
    reverify()
    from ..exporter.sensitivity_export import replay_binding
    require(json_bytes(replay_binding(record['sens35_detached_losses'],evidence)) ==
            json_bytes(record['sens35_replay_binding']), 'Numeric replay commitment drift')


    report = {k: v for k, v in record.items() if k != 'sens35_detached_losses'}
    payloads = {'SCORING_NUMERIC.json': json_bytes(report),
                'SCORING_NUMERIC_EVIDENCE.json': json_bytes(evidence)}
    out.mkdir(parents=True, exist_ok=False)
    for name, data in payloads.items():
        with (out / name).open('xb') as handle:
            handle.write(data)
    reverify()
    receipt = dict(schema='AP_SCORING_NUMERIC_OUTPUT_RECEIPT_V1',
                   state='ARTIFICIAL_NUMERIC_OUTPUT_COMPLETE', synthetic_only=True,
                   production_authority=False,
                   files=[source_identity(out / name) for name in payloads])
    with (out / 'SCORING_NUMERIC_RECEIPT.json').open('xb') as handle:
        handle.write(json_bytes(receipt))
    return receipt
