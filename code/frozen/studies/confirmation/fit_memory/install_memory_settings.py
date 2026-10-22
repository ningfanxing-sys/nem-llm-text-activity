"""Install CONFX7 into CONF/CONFX2 from CONFX7/staging (archive first, never delete).

    python install_confx7.py --check [--with-a4]   # verify only: live files at their pre-CONFX7 identity, staging = manifest
    python install_confx7.py [--with-a4]           # install (refused while any process matches CONFX2/cli.py)

`--with-a4` installs the addendum-4 overlay (staging_a4: features_adapter.py replaced, notice_prefix_encoding.py and its
test added) on top of staging; without it CONFX7 installs exactly as staged in staging/.

The install:
1. checks that every live file to be replaced still has its pre-CONFX7 (CONFX6) identity;
2. copies those files to CONFX7/archive/pre_CONFX7/ and writes BEFORE_IDENTITIES.json;
3. copies the staged files in place and checks every hash against staging/STAGING_MANIFEST.json.

HOST_RUN.md is archived here; `update_host_run.py` changes it afterwards.
"""
import argparse, hashlib, json, shutil, subprocess
from pathlib import Path

HERE = Path(__file__).resolve().parent
CONF = HERE.parent
STAGING = HERE / 'staging' / 'CONFX2'
ARCHIVE = HERE / 'archive' / 'pre_CONFX7'
BEFORE = {   # pre-CONFX7 identities (SPEC_FREEZE.json, SPEC_ADDENDUM_2_FREEZE.json; tests from the T3 manifest)
    'CONFX2/execution_adapter.py': 'cc8bf20eefce3dc56b6b72f5a28870cc95662933f6af720795a4938d90155b2d',
    'CONFX2/runtime.py': '6da5d0c5a03d5d87378df4e3c782bd1d16c197a6c2cc7fe1be1b0bfedf510511',
    'CONFX2/features_adapter.py': 'd958d53e92fd40d800fdbdf9497a728b1cdc35775aa4437a0a9c3f69164a96fc',
    'CONFX2/tests/test_execution_amendment.py': '6830d6d31db227322e7c527703ba6b63f73e53c0b8bd96370e617459b2e6081f',
    'CONFX2/tests/test_confx5_lear.py': 'e0082a53b91543fc21802fac2053d94220da22ebaf12fef881106d26705b8a69',
    'CONFX2/tests/test_execution_adapters.py': '21a2a44ab0a21dd83d42ae6612d89600bd1ac8e3c5d344cba841ed201f2dc4a1',
    'CONFX2/ADAPTER_FREEZE.json': '51c4f1b8278be8a1fcb152f632ccab5f4c6e0722ee24ba4130822c040498c77c',
    'HOST_RUN.md': '511531dad23dfcb732d558ed965c9f4816c04131f48a4bad55501f08552f0192',
}
REPLACED = ['execution_adapter.py', 'runtime.py', 'features_adapter.py', 'tests/test_execution_amendment.py',
            'tests/test_confx5_lear.py', 'tests/test_execution_adapters.py']
NEW = ['anonymous_memory.py', 'lear_parallel.py', 'tests/test_confx7_memory.py', 'tests/test_confx7_panel_resume.py',
       'tests/test_confx7_throughput.py']
A4_STAGING = HERE / 'staging_a4' / 'CONFX2'
A4_OVERLAY = ['features_adapter.py']
A4_NEW = ['notice_prefix_encoding.py', 'tests/test_confx7_notice_prefix.py']


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def check(with_a4=False):
    problems = []
    for rel, digest in BEFORE.items():
        if sha(CONF / rel) != digest:
            problems.append('live file not at its pre-CONFX7 identity: ' + rel)
    for rel in NEW:
        if (CONF / 'CONFX2' / rel).exists():
            problems.append('new file already present: ' + rel)
    manifest = json.loads((HERE / 'staging' / 'STAGING_MANIFEST.json').read_text())['files']
    if sorted(manifest) != sorted(REPLACED + NEW):
        problems.append('staging manifest does not list exactly the CONFX7 files')
    for rel, item in manifest.items():
        if sha(STAGING / rel) != item['sha256']:
            problems.append('staged file differs from its manifest: ' + rel)
    if with_a4:
        for rel in A4_NEW:
            if (CONF / 'CONFX2' / rel).exists():
                problems.append('addendum-4 file already present: ' + rel)
        a4 = json.loads((HERE / 'staging_a4' / 'STAGING_A4_MANIFEST.json').read_text())['files']
        if sorted(a4) != sorted(A4_OVERLAY + A4_NEW):
            problems.append('addendum-4 manifest does not list exactly the overlay files')
        for rel, item in a4.items():
            if sha(A4_STAGING / rel) != item['sha256']:
                problems.append('addendum-4 staged file differs from its manifest: ' + rel)
        manifest = {**manifest, **{rel: dict(item, overlay=True) for rel, item in a4.items()}}
    return problems, manifest


def main():
    parser = argparse.ArgumentParser(description=__doc__); parser.add_argument('--check', action='store_true')
    parser.add_argument('--with-a4', action='store_true')
    args = parser.parse_args()
    running = subprocess.run(['/usr/bin/pgrep', '-f', 'CONFX2/cli.py'], capture_output=True, text=True).stdout.split()
    problems, manifest = check(args.with_a4)
    print(json.dumps({'cli_processes_running': running, 'problems': problems}, indent=1))
    if args.check or problems:
        raise SystemExit(1 if problems else 0)
    if running:
        raise SystemExit('a CONFX2/cli.py process is running; not installing')
    before = {}
    for rel, digest in BEFORE.items():
        target = ARCHIVE / rel
        if not target.exists():
            target.parent.mkdir(parents=True, exist_ok=True); shutil.copy2(CONF / rel, target)
        if sha(target) != digest:
            raise SystemExit('archive copy differs: ' + rel)
        before[rel] = {'archive_path': str(target), 'bytes': target.stat().st_size, 'sha256': digest}
    (HERE / 'BEFORE_IDENTITIES.json').write_text(json.dumps(before, indent=2, sort_keys=True) + '\n')
    installed = REPLACED + NEW + (A4_NEW if args.with_a4 else [])
    for rel in installed:
        source = (A4_STAGING if manifest[rel].get('overlay') else STAGING) / rel
        shutil.copyfile(source, CONF / 'CONFX2' / rel)
        if sha(CONF / 'CONFX2' / rel) != manifest[rel]['sha256']:
            raise SystemExit('copy mismatch: ' + rel)
    print(json.dumps({'archived': sorted(before), 'installed': sorted(installed), 'addendum_4': args.with_a4}, indent=1))


if __name__ == '__main__':
    main()
