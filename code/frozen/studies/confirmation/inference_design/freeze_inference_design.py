#!/usr/bin/env python3
"""A8-style amendment helper: dry-run / verify only; never writes or reads outcomes."""
import argparse
import datetime
import hashlib
import json
from pathlib import Path
import re

HERE = Path(__file__).resolve().parent
FILES = ('ADDENDUM_A8_AMENDMENT_1_DRAFT.md', 'freeze_a8_amendment1.py')
BINDS = {
    'A8_FREEZE.json': '80e95c8db2c85ca38490f443612cda30d7ff33124f33ed87b70d8f8317909162',
    'RULES_FOR_FILL3F.json': 'a7490266709a5607f424154635b77bb8fafcc2139d705541612fa7ed7b00b048',
}
ADDITIONS = {'words.PFMIN_C3.NE': 'no evaluable reading',
             'words.PFMIN_INC_REASON.parity': 'reproduction check failed'}
BEFORE_ANY = ['T5', 'CONF score', 'A8 post-score output', 'FILL3F code freeze']

def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()

def strict(path):
    def pairs(items):
        out = {}
        for k, v in items:
            if k in out: raise ValueError('duplicate key: '+k)
            out[k] = v
        return out
    def bad(value): raise ValueError('non-finite JSON: '+value)
    return json.loads(Path(path).read_text(), object_pairs_hook=pairs, parse_constant=bad)

def record(here=HERE):
    here = Path(here)
    for name, digest in BINDS.items():
        if sha(here/name) != digest: raise ValueError('parent identity drift: '+name)
    blocks = re.findall(r'```json\n(.*?)\n```', (here/FILES[0]).read_text(), re.S)
    if len(blocks) != 1 or json.loads(blocks[0]) != ADDITIONS:
        raise ValueError('draft must contain exactly the two additions')
    rules = strict(here/'RULES_FOR_FILL3F.json')
    if rules['words']['PLAIN_C3']['NE'] != ADDITIONS['words.PFMIN_C3.NE']:
        raise ValueError('NE gloss differs from existing plain gloss')
    for key in ADDITIONS:
        _, group, member = key.split('.')
        if member in rules['words'][group]: raise ValueError('addition overwrites parent: '+key)
    return {'schema': 'A8_AMENDMENT_1_V1', 'state': 'A8_AMENDMENT_1_FROZEN_BEFORE_T5',
            'name': 'CONF-A8 amendment 1: only the missing NE and parity word forms',
            'frozen_by': 'coordinator from verified dry-run; separate timestamp/chronology verification required',
            'frozen_utc': datetime.datetime.now(datetime.timezone.utc).isoformat(timespec='seconds'),
            'before_any': BEFORE_ANY, 'timestamp_label': 'include in T5 before scoring',
            'files': {n: {'sha256': sha(here/n), 'bytes': (here/n).stat().st_size} for n in FILES},
            'binds': BINDS, 'additions': ADDITIONS, 'other_rule_changes': False,
            'outcome_access': 'none; local parent identities and draft only'}

def verify(path, here=HERE):
    current = record(here); frozen = strict(path)
    if set(frozen) != set(current): raise ValueError('amendment receipt field set differs')
    for key in current:
        if key != 'frozen_utc' and frozen[key] != current[key]:
            raise ValueError('amendment receipt drift: '+key)
    date = datetime.datetime.fromisoformat(frozen['frozen_utc'])
    if date.utcoffset() != datetime.timedelta(0): raise ValueError('freeze time must be UTC')
    return frozen

def main():
    p = argparse.ArgumentParser(description=__doc__)
    mode = p.add_mutually_exclusive_group(required=True)
    mode.add_argument('--dry-run', action='store_true'); mode.add_argument('--verify', type=Path)
    a = p.parse_args()
    if a.verify:
        verify(a.verify); print('A8 AMENDMENT 1 VERIFIED '+sha(a.verify))
    else:
        print(json.dumps(record(), indent=2, ensure_ascii=False))

if __name__ == '__main__':
    try: main()
    except (ValueError, OSError, KeyError) as exc: raise SystemExit('A8 AMENDMENT 1 REFUSED: '+str(exc))
