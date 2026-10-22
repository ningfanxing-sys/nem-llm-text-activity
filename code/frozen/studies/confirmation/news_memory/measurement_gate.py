"""CONFX8 gate: successful full-shape pairs, unchanged speed proofs, current code binding and feasibility.
Only CONFX8 synthetic measurement records/code manifests are read. Exit 5 until all requirements pass.
"""
import hashlib, json, sys
from pathlib import Path
HERE = Path(__file__).resolve().parent
IDENTITY_FIELDS = ('model_sha256', 'model_text_sha256', 'prediction_sha256', 'prediction_key_sha256',
                   'train_indices_sha256', 'train_rows', 'prediction_rows', 'features')
CASES = {
    'news_L_chen_last_origin_full_shape': (131472, 1258, ('old', 'new')),
    'news_N_last_origin_full_shape': (131472, 872, ('new',)),
    'notice_L_chen_notice_R225000': (357511, 448, ('old', 'new')),
    'notice_L_chen_notice_R450000': (715021, 448, ('new',)),
    'notice_L14_R450000': (715021, 78, ('new',)),
    'notice_L_chen_notice_full_rows': (1421941, 448, ('new',)),
}

def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()

def binding():
    return {name: sha(HERE / name) for name in ('SPEC_FREEZE.json', 'staging/STAGING_MANIFEST.json',
            'measure_fit_memory.py', 'measure_speed_a3.py', 'feasibility_24h.py', 'feasibility_24h_a3.py',
            'measurement_gate.py')}

def validate_memory(memory, expected_binding=None):
    errors = []
    if memory.get('task') != 'CONFX8' or memory.get('synthetic_only') is not True:
        errors.append('not CONFX8 synthetic measurements')
    if memory.get('binding') != (binding() if expected_binding is None else expected_binding):
        errors.append('memory measurements bound to stale code/spec')
    entries = memory.get('cases') or []
    names = [e.get('case', {}).get('name') for e in entries]
    if len(names) != len(CASES) or set(names) != set(CASES):
        errors.append('memory case census differs from frozen six cases')
    for entry in entries:
        case = entry.get('case') or {}; name = case.get('name')
        if name not in CASES: continue
        rows, cols, labels = CASES[name]
        if entry.get('data') != {'rows': rows, 'columns': cols}:
            errors.append('memory shape mismatch: ' + name)
        if name.startswith('news_') and case.get('origin') != '2026-09-30':
            errors.append('news last origin mismatch: ' + name)
        runs = entry.get('runs') or {}
        if set(runs) != set(labels): errors.append('worker census mismatch: ' + name)
        for label in labels:
            run = runs.get(label) or {}; rec = run.get('result') or {}
            if run.get('returncode') != 0 or rec.get('state') != 'COMPLETE':
                errors.append('worker not COMPLETE: ' + name + '/' + label)
            if rec.get('features') != cols:
                errors.append('worker feature count mismatch: ' + name + '/' + label)
            expected_train = 131328 if name.startswith('news_') else case.get('train_rows')
            expected_query = 72 if name.startswith('news_') else case.get('query_rows')
            if rec.get('train_rows') != expected_train or rec.get('prediction_rows') != expected_query:
                errors.append('worker train/query count mismatch: ' + name + '/' + label)
            override = rec.get('measurement_only_limit_override')
            if label == 'old' and override != {'scope': 'MEASUREMENT_ONLY', 'old_guard_measure': 'RSS', 'limit_bytes': 3758096384}:
                errors.append('old measurement-only override missing: ' + name)
            if label == 'new' and override is not None:
                errors.append('override leaked to new worker: ' + name)
        if 'old' in labels:
            identity = entry.get('bit_identity') or {}
            if set(identity) != set(IDENTITY_FIELDS) or not all(v is True for v in identity.values()):
                errors.append('old/new bit identity missing or false: ' + name)
            old, new = (runs.get('old') or {}).get('result') or {}, (runs.get('new') or {}).get('result') or {}
            if any(old.get(k) is None or old.get(k) != new.get(k) for k in IDENTITY_FIELDS):
                errors.append('old/new identity values disagree: ' + name)
    return errors

def problems():
    found = []
    def load(name):
        try: return json.loads((HERE / name).read_text())
        except (OSError, ValueError) as exc:
            found.append(name + ' missing or unreadable: ' + type(exc).__name__); return None
    memory = load('MEMORY_MEASUREMENTS.json')
    if memory is not None: found.extend(validate_memory(memory))
    speed = load('SPEED_MEASUREMENTS_A3.json')
    if speed is not None:
        if speed.get('task') != 'CONFX8' or speed.get('binding') != binding(): found.append('stale speed measurement binding')
        if memory is None or speed.get('memory_measurements_sha256') != sha(HERE / 'MEMORY_MEASUREMENTS.json'):
            found.append('speed memory record binding mismatch')
        findings=speed.get('findings') or {}
        if set(findings) != {'news_identical_4_vs_7', 'lear_identical_serial_vs_1_and_3'} or not all(v is True for v in findings.values()):
            found.append('speed findings not all identical')
        waves = (speed.get('news') or {}).get('waves') or {}
        if set(waves) != {'primary_seed_robustness_news', 'secondary_news'}:
            found.append('speed wave census mismatch')
        for name, wave in waves.items():
            runs = wave.get('runs') or {}
            if set(runs) != {'4', '7'} or wave.get('all_identical') is not True:
                found.append('speed comparison incomplete: ' + name)
            for run in runs.values():
                tasks = run.get('tasks') or {}
                if not tasks or any(t.get('state') != 'COMPLETE' for t in tasks.values()):
                    found.append('speed task not COMPLETE: ' + name)
        issues = (speed.get('lear') or {}).get('issues') or {}
        if set(issues) != {'2026-03-01', '2026-09-30'}: found.append('LEAR issue census mismatch')
        for issue, entry in issues.items():
            if (entry.get('serial') or {}).get('state') != 'COMPLETE': found.append('LEAR serial failed: ' + issue)
            parallel = entry.get('parallel') or {}
            if set(parallel) != {'1', '3'} or any(v.get('state') != 'COMPLETE' or v.get('identical_to_serial') is not True for v in parallel.values()):
                found.append('LEAR parallel incomplete/nonidentical: ' + issue)
    for name in ('FEASIBILITY_24H.json', 'FEASIBILITY_24H_A3.json'):
        r = load(name)
        if r is not None:
            if r.get('task') != 'CONFX8' or r.get('binding') != binding(): found.append('stale feasibility binding: ' + name)
            if memory is None or r.get('memory_measurements_sha256') != sha(HERE / 'MEMORY_MEASUREMENTS.json'):
                found.append('feasibility memory binding mismatch: ' + name)
            if name.endswith('_A3.json') and (speed is None or r.get('speed_measurements_sha256') != sha(HERE / 'SPEED_MEASUREMENTS_A3.json')):
                found.append('feasibility speed binding mismatch')
    return found

def main():
    try: found = problems()
    except (KeyError, TypeError, ValueError) as exc: found = ['malformed measurement record: ' + str(exc)]
    print(json.dumps({'measurement_records_accepted': not found, 'problems': found}))
    return 0 if not found else 5

if __name__ == '__main__':
    sys.exit(main())
