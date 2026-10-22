"""CONFX8 non-switch install: archive first, then exact staging replacements; coordinator only.

python install_confx8.py --check    # read-only pre-install validation
python install_confx8.py            # NOT run during preparation
"""
import argparse, hashlib, json, shutil, subprocess
from pathlib import Path
HERE = Path(__file__).resolve().parent
CONF = HERE.parent
STAGING = HERE / 'staging/CONFX2'
ARCHIVE = HERE / 'archive/pre_CONFX8'
BEFORE = json.loads((HERE / 'PRE_IDENTITIES.json').read_text())
REPLACED = ['execution_adapter.py', 'runtime.py', 'tests/test_confx7_memory.py', 'tests/test_execution_amendment.py']
NEW = ['tests/test_confx8_resources.py']

def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()

def check():
    problems = []
    for rel, digest in BEFORE.items():
        if not (CONF / rel).is_file() or sha(CONF / rel) != digest:
            problems.append('live file not at its pre-CONFX8 identity: ' + rel)
    for rel in NEW:
        if (CONF / 'CONFX2' / rel).exists():
            problems.append('new file already present: ' + rel)
    manifest = json.loads((HERE / 'staging/STAGING_MANIFEST.json').read_text())['files']
    actual = {str(p.relative_to(STAGING)) for p in STAGING.rglob('*.py')}
    if set(manifest) != set(REPLACED + NEW) or actual != set(manifest):
        problems.append('staging does not list exactly the CONFX8 files')
    for rel, item in manifest.items():
        path = STAGING / rel
        if not path.is_file() or sha(path) != item['sha256'] or path.stat().st_size != item['bytes']:
            problems.append('staging manifest drift: ' + rel)
    spec = json.loads((HERE / 'SPEC_FREEZE.json').read_text())
    if sha(HERE / 'SPEC.md') != spec['spec']['sha256']:
        problems.append('SPEC drift')
    return problems, manifest

def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--check', action='store_true'); args = parser.parse_args()
    probe = subprocess.run(['/usr/bin/pgrep', '-f', 'CONFX2/cli.py'], capture_output=True, text=True)
    if probe.returncode not in (0, 1):
        raise SystemExit('cannot verify CONF process liveness; not installing: ' + probe.stderr.strip())
    running = probe.stdout.split()
    problems, manifest = check()
    print(json.dumps({'cli_processes_running': running, 'problems': problems}))
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
        before[rel] = {'archive_path': str(target.resolve()), 'bytes': target.stat().st_size, 'sha256': digest}
    (HERE / 'BEFORE_IDENTITIES.json').write_text(json.dumps(before, indent=2, sort_keys=True) + '\n')
    for rel in REPLACED + NEW:
        (CONF / 'CONFX2' / rel).parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(STAGING / rel, CONF / 'CONFX2' / rel)
        if sha(CONF / 'CONFX2' / rel) != manifest[rel]['sha256']:
            raise SystemExit('copy mismatch: ' + rel)
    print(json.dumps({'archived': sorted(before), 'installed': REPLACED + NEW}))

if __name__ == '__main__':
    main()
