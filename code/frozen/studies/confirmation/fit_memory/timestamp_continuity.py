"""CONFX7 continuity of the T3 timestamp (CONF/TIMESTAMPS/T3, 2026-10-02T07:29:30Z) (template: CONFX6/T2_CONTINUITY.json).

    python t3_continuity.py --out T3_CONTINUITY.json

For every entry of MANIFEST_T3.sha256 (sha256, bytes, path relative to autopilot/q1_audits):
- files under CONF/CONFX2/host_state/ and CONF/CONFX5/host_moved_out/ are never opened: only existence and size
  are compared (production data, possibly with window outcomes);
- every other file is hashed. A file that CONFX7 changed must have its T3-time bytes preserved under
  CONF/CONFX7/archive/pre_CONFX7/ (checked by hash). Other changes are listed with their current hash.
"""
from __future__ import annotations
import argparse, datetime as dt, hashlib, json
from pathlib import Path

HERE = Path(__file__).resolve().parent
CONF = HERE.parent
Q1 = CONF.parent
MANIFEST = CONF / 'TIMESTAMPS/T3/MANIFEST_T3.sha256'
ARCHIVE = HERE / 'archive/pre_CONFX7'
CONFX7_CHANGED = {'CONF/CONFX2/execution_adapter.py', 'CONF/CONFX2/runtime.py', 'CONF/CONFX2/features_adapter.py',
                  'CONF/CONFX2/tests/test_execution_amendment.py', 'CONF/CONFX2/tests/test_confx5_lear.py',
                  'CONF/CONFX2/tests/test_execution_adapters.py',
                  'CONF/CONFX2/ADAPTER_FREEZE.json', 'CONF/HOST_RUN.md'}
NOT_OPENED = ('CONF/CONFX2/host_state/', 'CONF/CONFX5/host_moved_out/')


def sha(path):
    h = hashlib.sha256()
    with Path(path).open('rb') as f:
        for block in iter(lambda: f.read(1 << 20), b''):
            h.update(block)
    return h.hexdigest()


def archived(rel):
    return ARCHIVE / rel[len('CONF/'):]


def main():
    parser = argparse.ArgumentParser(description=__doc__); parser.add_argument('--out', required=True)
    args = parser.parse_args()
    entries = []
    for line in MANIFEST.read_text().splitlines():
        if not line.strip() or line.startswith('#'):
            continue
        digest, size, rel = line.split(None, 2)
        entries.append((digest, int(size), rel))
    identical, changed_confx7, changed_other, not_opened = 0, [], [], {'same_size': 0, 'size_changed_or_missing': []}
    for digest, size, rel in entries:
        path = Q1 / rel
        if rel.startswith(NOT_OPENED):
            if path.is_file() and path.stat().st_size == size:
                not_opened['same_size'] += 1
            else:
                not_opened['size_changed_or_missing'].append({'t3_path': rel, 'exists': path.exists()})
            continue
        current = sha(path) if path.is_file() else None
        if current == digest:
            identical += 1
            continue
        item = {'t3_path': rel, 't3_sha256': digest, 't3_bytes': size, 'current_sha256': current}
        if rel in CONFX7_CHANGED:
            copy = archived(rel)
            item.update(archived_copy=str(copy), archived_copy_sha256_equals_t3=copy.is_file() and sha(copy) == digest)
            changed_confx7.append(item)
        else:
            changed_other.append(item)
    out = {'task': 'CONFX7', 'time_utc': dt.datetime.now(dt.timezone.utc).isoformat(),
           'purpose': 'Continuity of the T3 timestamp (CONF/TIMESTAMPS/T3, 2026-10-02T07:29:30Z) across CONFX7: which T3-listed '
                      'files CONFX7 changed and where their T3-time bytes are preserved.',
           't3_manifest': {'path': str(MANIFEST), 'sha256': sha(MANIFEST), 'entries': len(entries)},
           'entries_still_identical': identical, 'entries_changed_by_confx7': changed_confx7,
           'all_confx7_changes_preserved_in_archive': all(i['archived_copy_sha256_equals_t3'] for i in changed_confx7),
           'entries_changed_by_other_tasks': changed_other,
           # ADAPTER_FREEZE.json is replaced only by freeze_amendment.py freeze, after this record is written and bound.
           'adapter_freeze_replaced_at_freeze': {
               't3_path': 'CONF/CONFX2/ADAPTER_FREEZE.json',
               'archived_copy': str(archived('CONF/CONFX2/ADAPTER_FREEZE.json')),
               'archived_copy_sha256_equals_t3': next((sha(archived(rel)) == digest for digest, _, rel in entries
                                                       if rel == 'CONF/CONFX2/ADAPTER_FREEZE.json'), False)},
           'production_entries_not_opened': not_opened,
           'host_state_contents_read': False, 'moved_out_contents_read': False}
    Path(args.out).write_text(json.dumps(out, indent=2, sort_keys=True) + '\n')
    print(json.dumps({'identical': identical, 'confx7': len(changed_confx7), 'other': len(changed_other),
                      'preserved': out['all_confx7_changes_preserved_in_archive'],
                      'not_opened_same_size': not_opened['same_size'],
                      'not_opened_changed': len(not_opened['size_changed_or_missing'])}))


if __name__ == '__main__':
    main()
