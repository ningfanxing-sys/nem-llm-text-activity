'Bind timestamp tokens to the notice-delay specification.'
import argparse
import datetime as dt
import os
from pathlib import Path
import sys

HERE = Path(__file__).absolute().parent


def bind(label):
    from delay_authority import identity, require, verify_timestamp_bundle
    from delay_freeze import timestamp_required_identities, verify_delay_freeze, write_exclusive
    sys.path.insert(0, str(HERE.parent / 'code'))
    from common import resources
    require(os.environ.get('FORECAST_BINDING_SOURCE_TIMESTAMP_BIND') == '1', 'Source-only existing timestamp binding')
    resources()
    require(label not in ('T4F', 'T4I', 'T4J', 'T4K', 'T5'), 'Separate additive delay timestamp label required')
    frozen = verify_delay_freeze()
    verified = verify_timestamp_bundle(label, timestamp_required_identities(frozen))
    frozen_utc = dt.datetime.fromisoformat(frozen['utc'])
    require(frozen_utc.utcoffset() == dt.timedelta(0), 'Actual runtime freeze UTC required')
    require(all(dt.datetime.fromisoformat(row['utc']) > frozen_utc for row in verified['tsa'].values()),
            'Both established TSA receipts must follow the actual runtime delay freeze')
    value = {'schema': 'FORECAST_BINDING8_DELAY_OVERLAY_TIMESTAMP_BINDING_V1',
             'state': 'VERIFIED_EXISTING_SOURCE_TIMESTAMP', 'label': label,
             'overlay_freeze': identity(HERE / 'OVERLAY_FREEZE.json'),
             'final_source_commitment': frozen['final_source_commitment'],
             'review8_decision_authority': frozen['review8_decision_authority'],
             'speed_overlay_binding': frozen['speed_overlay_binding'],
             'verification': verified, 'timestamp_generated': False}
    write_exclusive(HERE / 'OVERLAY_TIMESTAMP_BINDING.json', value)
    return value


def main():
    import types
    for alias, name in [('delay_authority', 'timestamp_checks.py'), ('delay_root_mapping', 'root_mapping.py'),
                        ('delay_speed_binding', 'speed_binding.py'),
                        ('delay_final_source', 'source_inventory.py'), ('delay_freeze', 'freeze_delay.py')]:
        if alias not in sys.modules:
            module = types.ModuleType(alias)
            module.__file__ = str(HERE / name)
            sys.modules[alias] = module
            exec(compile((HERE / name).read_bytes(), str(HERE / name), 'exec'), vars(module))
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--source-bind', action='store_true')
    parser.add_argument('--label', required=True)
    args = parser.parse_args()
    if not args.source_bind:
        raise PermissionError('Explicit --source-bind required')
    bind(args.label)
    print('Existing joint-delay timestamp verified and bound; no timestamp generated')


if __name__ == '__main__':
    main()
