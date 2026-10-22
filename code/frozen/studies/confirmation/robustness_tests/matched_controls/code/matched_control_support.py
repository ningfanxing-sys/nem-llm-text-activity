"""Small identity, freeze and host gates; never open CONF host_state."""
import hashlib
import json
import os
import re
import subprocess
from pathlib import Path

OUT = Path(__file__).resolve().parents[1]
CONF = OUT.parents[1]
ADAPTER = CONF / 'CONFX2/ADAPTER_FREEZE.json'
PCX_FREEZE = OUT / 'PCX_FREEZE.json'


def sha256(path):
    p = Path(path).resolve()
    if 'host_state' in p.parts or 'private' in p.parts or p.name == 'auth.json' or p.name.startswith('.env'):
        raise PermissionError('Forbidden identity path: ' + str(p))
    h = hashlib.sha256()
    with p.open('rb') as f:
        for chunk in iter(lambda: f.read(1 << 20), b''):
            h.update(chunk)
    return h.hexdigest()


def output_path(path):
    p = Path(path).resolve()
    if p != OUT and OUT not in p.parents:
        raise PermissionError('PCX writes only below ' + str(OUT))
    return p


def identity(path):
    p = Path(path).resolve()
    return {'path': str(p), 'sha256': sha256(p), 'bytes': p.stat().st_size}


def immutable_json(path, obj):
    p = output_path(path)
    payload = json.dumps(obj, indent=2, sort_keys=True, allow_nan=False) + '\n'
    p.parent.mkdir(parents=True, exist_ok=True)
    if p.exists():
        if p.read_text() != payload:
            raise PermissionError('Refusing to replace existing receipt: ' + str(p))
        return
    with p.open('x') as f:
        f.write(payload)


def verify_identities(items):
    for item in items:
        if sha256(item['path']) != item['sha256']:
            raise PermissionError('Bound file mismatch: ' + item['path'])


def verify_binding(record, adapter=ADAPTER):
    if sha256(adapter) != record['adapter_freeze_sha256']:
        raise PermissionError('Adapter mismatch: PCX requires the pinned CONFX7 freeze')
    verify_identities(record['bound_files'])
    return record


def verify_freeze(path=PCX_FREEZE):
    return verify_binding(json.loads(Path(path).read_text()))


def verify_a4_freezes():
    root = CONF / 'A4'
    names = ['ADDENDUM_A4_FREEZE.json', 'ADDENDUM_A4_AMENDMENT_1_FREEZE.json',
             'ADDENDUM_A4_AMENDMENT_2_FREEZE.json', 'A4_CODE_AND_RULES_FREEZE.json']
    records = [json.loads((root / name).read_text()) for name in names]
    for rec in records:
        for name, ident in rec['files'].items():
            if sha256(root / name) != ident['sha256']:
                raise PermissionError('A4 frozen file mismatch: ' + name)
    if records[1]['addendum_freeze_sha256'] != sha256(root / names[0]):
        raise PermissionError('A4 amendment-1 binding mismatch')
    for rec in records[2:]:
        if rec['addendum_freeze_sha256'] != sha256(root / names[0]) or rec['amendment_1_freeze_sha256'] != sha256(root / names[1]):
            raise PermissionError('A4 amendment binding mismatch')
    if records[3]['amendment_2_freeze_sha256'] != sha256(root / names[2]):
        raise PermissionError('A4 code binding mismatch')
    imports = []
    for name, expected in records[3]['imports_frozen'].items():
        if sha256(CONF / name) != expected:
            raise PermissionError('A4 frozen import mismatch: ' + name)
        imports.append(CONF / name)
    return [root / name for name in names] + [root / name for rec in records for name in rec['files']] + imports


def verify_seal_attestation(attestation, expected_sha, adapter_sha):
    p = output_path(attestation)
    if sha256(p) != expected_sha:
        raise PermissionError('Seal-only attestation mismatch')
    rec = json.loads(p.read_text())
    if rec.get('state') != 'ALL_REGISTERED_PREDICTIONS_SEALED' or rec.get('sealed_before_outcome_scoring') is not True:
        raise PermissionError('CONF chain has not sealed')
    if rec.get('adapter_freeze_sha256') != adapter_sha:
        raise PermissionError('Seal attestation adapter mismatch')
    if not re.fullmatch('[0-9a-f]{64}', rec.get('seal_sha256', '')):
        raise PermissionError('Missing CONF seal identity')
    return rec


def assert_idle(process_text=None):
    if process_text is None:
        process_text = subprocess.check_output(['ps', '-axo', 'pid=,command='], text=True)
    pattern = re.compile(r'(CONFX2/cli\.py\s+(?:panels|features|counted-pilots|fit-bank|lear|seal)\b|'
                         r'(?:run_positive_control\.py|pcx_runner\.py)\s+(?:fit|build)\b|'
                         r'(?:A2BATCH|A2LABEL)/.*(?:fit|run)[^/]*\.py)')
    for line in process_text.splitlines():
        fields = line.strip().split(None, 1)
        if len(fields) == 2 and fields[0].isdigit() and int(fields[0]) != os.getpid() and pattern.search(fields[1]):
            raise PermissionError('Host fit/build still active; serialize batches: PID ' + fields[0])


def host_gate(attestation, expected_sha, freeze_path=PCX_FREEZE):
    binding = verify_freeze(freeze_path)
    assert_idle()
    return verify_seal_attestation(attestation, expected_sha, binding['adapter_freeze_sha256'])
