"""HOST_RUN step 3 restart (CONFX5): move notice-derived feature files out of host_state, never delete.

    python move_out_notice_files.py --dry-run     # print the move-out list only
    python move_out_notice_files.py               # move the files and write a receipt

The list comes from file names only (features_adapter.notice_derived_feature_files; CONFX5/SPEC.md
section 5); no file under host_state is opened, hashed or read. Destination:
CONF/CONFX5/host_moved_out/<UTC time>/features/ on the same filesystem (a rename). News files,
W_Bai_selection.json, W2_D_selection.json, DISK_PLAN.json and embedding_cache/ stay in place.
Refuses while any process matching CONFX2/cli.py is running.
"""
from __future__ import annotations
import argparse, datetime as dt, json, os, subprocess, sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
ADAPTERS = HERE.parent / 'CONFX2'
FEATURES = ADAPTERS / 'host_state' / 'features'


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--dry-run', action='store_true')
    args = parser.parse_args()
    running = subprocess.run(['/usr/bin/pgrep', '-f', 'CONFX2/cli.py'], capture_output=True, text=True).stdout.split()
    if running:
        raise SystemExit('A CONFX2/cli.py process is running (PIDs ' + ', '.join(running) + '); nothing was moved.')
    sys.dont_write_bytecode = True
    sys.path.insert(0, str(ADAPTERS))
    from features_adapter import notice_derived_feature_files  # pure function over file names
    selected = notice_derived_feature_files(FEATURES)
    if (FEATURES / 'manifest.json').exists():
        raise SystemExit('features/manifest.json exists: the feature bank completed; this restart procedure does not apply.')
    names = [p.name for p in selected]
    print(json.dumps({'features_dir': str(FEATURES), 'move_out': names, 'count': len(names)}, indent=2))
    if args.dry_run or not selected:
        return
    stamp = dt.datetime.now(dt.timezone.utc).strftime('%Y-%m-%dT%H-%M-%SZ')
    destination = HERE / 'host_moved_out' / stamp / 'features'
    destination.mkdir(parents=True, exist_ok=False)
    moved = []
    for path in selected:
        target = destination / path.name
        if target.exists():
            raise SystemExit('Destination exists, refusing to overwrite: ' + str(target))
        os.rename(path, target)          # same filesystem: a rename, no copy and no deletion
        moved.append(path.name)
    receipt = {'state': 'MOVED_OUT_NOT_DELETED', 'time_utc': dt.datetime.now(dt.timezone.utc).isoformat(),
               'source_dir': str(FEATURES), 'destination_dir': str(destination), 'moved_file_names': moved,
               'rule': 'CONFX5/SPEC.md section 5; features_adapter.notice_derived_feature_files',
               'host_state_contents_read': False, 'kept_in_place': sorted(p.name for p in FEATURES.iterdir())}
    (destination.parent / 'MOVE_RECEIPT.json').write_text(json.dumps(receipt, indent=2) + '\n')
    print(json.dumps({'moved': len(moved), 'receipt': str(destination.parent / 'MOVE_RECEIPT.json')}))


if __name__ == '__main__':
    main()
