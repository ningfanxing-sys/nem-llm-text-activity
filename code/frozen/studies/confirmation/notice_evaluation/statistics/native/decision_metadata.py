'Check decision timestamps and source identities.'
from copy import deepcopy
from pathlib import Path
from . import reader as R

BINDING = dict(schema='ANCHORREADER_REVIEW8_AUTHORITY_V1', timestamp_label='T4K',
    timestamp_utc='2026-10-05T11:28:31Z', clauses=['D1.1', 'D1.2', 'D2', 'D4'],
    decision=dict(path=str(R.confirmation/'REVIEW8/SOURCE_DECISIONS_REVIEW8_20261005.md'),
        sha256='0c755ff3f08ab62d8c2b913088027fc7f10f0a8e923ddb561578185ef486303f'),
    manifest=dict(path=str(R.confirmation/'TIMESTAMPS/T4K/MANIFEST_T4K.sha256'),
        sha256='50cbca84beadaa3f031a290c89f79b5fc8acb47ac50d448610c54cf36ea462d1'),
    timestamp_result=dict(path=str(R.confirmation/'TIMESTAMPS/T4K/T4K_RESULT.json'),
        sha256='386bae50d907fc1ca0ea9ae54c1aa0c5e2f38b6134f7c4beca995905165a8dc1'))
IDENTITY_FIELDS = ('decision', 'manifest', 'timestamp_result')
METADATA_SOURCES = tuple(Path(BINDING[key]['path']) for key in IDENTITY_FIELDS)


def verify_decision(t5=None):
    paths = {key:R.checked(BINDING[key]) for key in IDENTITY_FIELDS}
    lines = paths['manifest'].read_text().splitlines()
    decision = BINDING['decision']
    row = '{}  {}  {}'.format(decision['sha256'], paths['decision'].stat().st_size,
                              paths['decision'].relative_to(R.Q).as_posix())
    R.require(lines.count(row) == 1 and '# label: T4K' in lines and
              '# created_utc: 2026-10-05T11:28:31+00:00' in lines, 'REVIEW8 T4K manifest binding drift')
    result = R.read_json(paths['timestamp_result'])
    R.require(result.get('label') == 'T4K' and result.get('manifest') == paths['manifest'].name and
              result.get('manifest_sha256') == BINDING['manifest']['sha256'], 'REVIEW8 T4K result binding drift')
    R.require(all(result.get('tsa', {}).get(tsa, {}).get('verified') is True and
                  result['tsa'][tsa].get('time_stamp') == 'Oct  5 11:28:31 2026 GMT'
                  for tsa in ('freetsa', 'digicert')), 'REVIEW8 T4K recorded TSA verification missing')
    if t5 is not None:
        R.require(all(R.t5_contains(t5, BINDING[key]) for key in IDENTITY_FIELDS), 'REVIEW8 exact T5 metadata row missing')
    return deepcopy(BINDING)
