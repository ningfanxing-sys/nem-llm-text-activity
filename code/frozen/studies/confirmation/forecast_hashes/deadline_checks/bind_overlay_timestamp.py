'Bind a saved timestamp token to the deadline source record.'
import argparse
import datetime as dt
import os
from pathlib import Path
import sys

HERE = Path(__file__).absolute().parent


def bind(label):
    sys.path.insert(0, str(HERE.parent / 'code'))
    from timestamp_checks import identity, require, verify_timestamp_bundle
    from common import resources
    from freeze_overlay import (timestamp_required_identities, verify_overlay_freeze,
                                write_exclusive)
    require(os.environ.get('FORECAST_BINDING_SOURCE_TIMESTAMP_BIND') == '1', 'Source-only timestamp binding')
    require(os.getpriority(os.PRIO_PROCESS, 0) == 20, 'Existing timestamp binding requires nice20')
    resources()
    require(label not in ('T4F', 'T4I', 'T4J', 'T5'), 'Separate additive before-T5 overlay timestamp label required')
    frozen = verify_overlay_freeze()
    verified = verify_timestamp_bundle(label, timestamp_required_identities(frozen))
    frozen_utc = dt.datetime.fromisoformat(frozen['utc'])
    require(frozen_utc.utcoffset() == dt.timedelta(0), 'Runtime freeze must have actual UTC time')
    require(all(dt.datetime.fromisoformat(row['utc']) > frozen_utc for row in verified['tsa'].values()),
            'Both established TSA receipts must follow runtime overlay freeze')
    value = {'schema': 'FORECAST_BINDING7_OVERLAY_TIMESTAMP_BINDING_V1',
             'state': 'VERIFIED_EXISTING_SOURCE_TIMESTAMP', 'label': label,
             'overlay_freeze': identity(HERE / 'OVERLAY_FREEZE.json'),
             'final_source_commitment': frozen['final_source_commitment'], 'verification': verified,
             'timestamp_generated': False}
    write_exclusive(HERE / 'OVERLAY_TIMESTAMP_BINDING.json', value)
    return value


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--source-bind', action='store_true')
    parser.add_argument('--label', required=True)
    args = parser.parse_args()
    if not args.source_bind:
        raise PermissionError('Explicit --source-bind required')
    bind(args.label)
    print('Existing overlay timestamp verified and bound; no timestamp generated')


if __name__ == '__main__':
    main()
