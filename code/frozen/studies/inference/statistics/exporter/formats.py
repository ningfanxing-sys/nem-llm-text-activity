'Serialize numerical result fields to JSON and CSV.'
import csv
import hashlib
import io
import json
from pathlib import Path
from ..input_checks import canonical, require, artificial_accept, source_identity, json_bytes

FIELDS = ('slot_id', 'scope', 'identity', 'view', 'source_receipt_sha256', 'timestamp_checks', 'value')


def csv_bytes(record):
    out = io.StringIO(newline='')
    writer = csv.DictWriter(out, fieldnames=FIELDS, lineterminator='\n')
    writer.writeheader()
    for row in record['rows']:
        writer.writerow({k: canonical(row[k]) for k in FIELDS})
    return out.getvalue().encode('utf-8')


def chinese_bytes(record):


    lines = ['#  Official results ： Values by result entry ', '', ' Each entry agrees with  JSON／CSV  the same ；null  denotes a missing value ， the record retains its reason 。', '']
    for row in record['rows']:
        lines.extend([' Entry ：' + row['slot_id'], '```json', canonical(row), '```', ''])
    lines.extend([' Limitations ：', '```json', canonical(record['limitations']), '```', ''])
    return '\n'.join(lines).encode('utf-8')


def write_artificial(record, output, *, fixture_root, reverify):

    root = artificial_accept(fixture_root)
    out = Path(output)
    require(out.is_absolute() and out.resolve() == out and out.is_relative_to(root)
            and not out.exists(), 'Fresh artificial detached output required')
    reverify()
    payloads = {'OFFICIAL_RESULTS.json': json_bytes(record),
                'OFFICIAL_RESULTS.csv': csv_bytes(record),
                'OFFICIAL_RESULTS_source.md': chinese_bytes(record)}
    out.mkdir(parents=True, exist_ok=False)
    for name, data in payloads.items():
        with (out / name).open('xb') as handle:
            handle.write(data)
    reverify()
    receipt = dict(schema='AP_SCORING_EXPORT_RECEIPT_V1', state='ARTIFICIAL_EXPORT_COMPLETE',
                   synthetic_only=True, production_authority=False,
                   slot_ids=[r['slot_id'] for r in record['rows']],
                   files=[source_identity(out / name) for name in payloads],
                   row_census_sha256=hashlib.sha256(canonical(record['rows']).encode()).hexdigest())
    with (out / 'EXPORT_RECEIPT.json').open('xb') as handle:
        handle.write(json_bytes(receipt))
    return receipt
