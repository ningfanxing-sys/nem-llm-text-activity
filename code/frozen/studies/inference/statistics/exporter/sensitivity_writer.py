'Write synthetic sensitivity losses and their input hashes.'
from pathlib import Path
from ..input_checks import artificial_accept, require, source_identity
from .formats import json_bytes


def write_artificial(exports, output, *, fixture_root, reverify):
    root = artificial_accept(fixture_root)
    out = Path(output)
    require(set(exports) == {'news', 'notice'}, 'Both task exports required')
    require(out.is_absolute() and out.resolve() == out and out.is_relative_to(root)
            and not out.exists(), 'Fresh detached artificial source_delivery required')
    reverify()
    payloads = {('SENS35_NEWS_LOSSES.json' if task == 'news' else 'SENS35_NOTICE_LOSSES.json'):
                json_bytes(value) for task, value in exports.items()}
    out.mkdir(parents=True, exist_ok=False)
    for name, data in payloads.items():
        with (out / name).open('xb') as handle:
            handle.write(data)
    reverify()
    receipt = dict(schema='AP_SCORING_SENS35_SOURCE_DELIVERY_RECEIPT_V1', synthetic_only=True,
                   state='ARTIFICIAL_SOURCE_DELIVERY_COMPLETE', production_authority=False,
                   files=[source_identity(out / name) for name in payloads],
                   replay_references={task:exports[task]['replay_binding'] for task in ('news','notice')},
                   separate_comparison_and_source_authorization_required=True)
    with (out / 'SENS35_SOURCE_DELIVERY_RECEIPT.json').open('xb') as handle:
        handle.write(json_bytes(receipt))
    return receipt
