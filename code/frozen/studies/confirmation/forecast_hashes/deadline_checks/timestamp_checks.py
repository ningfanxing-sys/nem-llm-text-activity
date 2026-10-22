'Check notice deadline timestamps and source certificates.'
import datetime as dt
import hashlib
import json
import os
from pathlib import Path, PurePosixPath
import re
import stat
import subprocess
import sys

HERE = Path(__file__).parent
AF = HERE.parent
Q = AF.parents[1]
TIMESTAMP_ROOT = Q / 'confirmation/TIMESTAMPS'
TRUST_ROOT = TIMESTAMP_ROOT / 'certs'
OPENSSL = '/opt/homebrew/bin/openssl'
SPECIFICATION_REL = 'confirmation/ANCHORDIAG/SOURCE_DECISION_RULE_SPECIFICATION_1_DEADLINE_20261005.md'
SPECIFICATION = {'path': str(Q / SPECIFICATION_REL), 'bytes': 4440,
             'sha256': 'd62decfb4904264c0aba816f749a00d288c6bef72fa88cea9b86b52236955680'}
SPECIFICATION_2_REL = 'confirmation/ANCHORDIAG/SOURCE_DECISION_RULE_SPECIFICATION_2_NO_CALENDAR_DEADLINE_20261005.md'
SPECIFICATION_2 = {'path': str(Q / SPECIFICATION_2_REL), 'bytes': 3643,
               'sha256': 'ff2b893f5c5bbdf6067cbd93311802bdd3a9cc25013d02442babca7f19905807'}
ERRATUM = {'path': str(Q / 'confirmation/ANCHORDIAG/ERRATUM_SPECIFICATION_2_RECORDED_TIME_20261005.md'), 'bytes': 625,
           'sha256': 'e697cd79d29b852f52757cab94e4948c8b68db69bbd9e3ba446f482c1ba1e1fb'}
CALENDAR_RULE = 'NO_CALENDAR_DEADLINE_CORRECTED_SEAL_PRECEDES_T5'
TSA_URLS = {'freetsa': 'https://freetsa.org/tsr', 'digicert': 'http://timestamp.digicert.com'}
TRUST_PINS = {
    'freetsa_cacert.pem': {'bytes': 2833, 'sha256': '2151b61137ffa86bf664691ba67e7da0b19f98c758e3d228d5d8ebf27e044438'},
    'freetsa_tsa.crt': {'bytes': 2273, 'sha256': '8bfb0305bb64e2571ca507552ef3245cb1c2fee8728e0ff8689225081ea13467'},
    'macos_system_roots.pem': {'bytes': 238530, 'sha256': 'b56413319de32344b67ffc389a8a1eef39b6f338618ff983d8bd086adac52584'},
}

TIMESTAMP_PINS = {
    'T4I': {
        'MANIFEST_T4I.sha256': {'bytes': 1401, 'sha256': '859b33c8cd7e4c09f823a297dc5413b3c72f92bf19adb46a5855680504ef8ee6'},
        'T4I_RESULT.json': {'bytes': 1558, 'sha256': 'a4d0ec20e98494f116896636325a9408c3d9ca361ae0e5dcbb58316624bc4f1e'},
        'T4I_freetsa.tsr': {'bytes': 4644, 'sha256': '01619888d0439fe4ff85fbcb1151f430cebd4215a81cc2ee6f681b22a89f066d'},
        'T4I_digicert.tsr': {'bytes': 6006, 'sha256': '92f022a9e68816c67c685ffdc922db7b88934748113aafad8f358181df8bb1d5'},
    },
    'T4F': {
        'MANIFEST_T4F.sha256': {'bytes': 6066, 'sha256': '77268688d588c4e790ff73e925908fa3b1d78dc71041dfec3ba8bfc923fbb54b'},
        'T4F_RESULT.json': {'bytes': 1560, 'sha256': 'd15b7ff524da2c44b3ca6312f3c7a46506d59441436aa0e96d1480f7c5199c6b'},
        'T4F_freetsa.tsr': {'bytes': 4645, 'sha256': 'e5e25380282e61025caeee41bde6dadc3d59a2093f328df2914f13d146bc4cb9'},
        'T4F_digicert.tsr': {'bytes': 6007, 'sha256': '191447278506cc07055fa731da5952113d2b487be827c1032a5e212118127805'},
    },
    'T4J': {
        'MANIFEST_T4J.sha256': {'bytes': 1011, 'sha256': '3297a87490755f8bb0fe4832407c9c856223c7dd6c6f9240accca3b321b1ef00'},
        'T4J_RESULT.json': {'bytes': 1557, 'sha256': '5a62aa149a1b98130b576b9daa2329dc7603662d5a06571e8c405eec99d538fd'},
        'T4J_freetsa.tsr': {'bytes': 4643, 'sha256': '0976d189fc64fb8aed094c26aa0d06990fe1c6e874eb3acd358781db62b84686'},
        'T4J_digicert.tsr': {'bytes': 6006, 'sha256': '3c785104e8ea377244369b80c085b6b615451af97ea260b8343e5194c5930504'},
    },
}


def require(condition, message):
    if not condition:
        raise PermissionError(message)


def canonical(path):
    raw = os.fspath(path)
    require(isinstance(raw, str) and raw.startswith('/') and '\x00' not in raw
            and str(PurePosixPath(raw)) == raw and not any(part in ('.', '..') for part in raw.split('/')),
            'Absolute canonical metadata path required')
    return raw


def _metadata_key(value):
    return value.st_dev, value.st_ino, value.st_mode, value.st_uid, value.st_gid


def read_metadata(path):

    raw = canonical(path)
    parts_raw = PurePosixPath(raw).parts
    forbidden = {'host_state', 'state', 'dly8', 'cps8', 'scored', 'scoring', 'scores',
                 'predictions', 'models', 'evaluation', 'run', 'private', '.aws',
                 'keychains', '.ssh'}


    components = parts_raw[2:] if raw.startswith('/private/tmp/') else parts_raw
    require(not forbidden.intersection(part.lower() for part in components)
            and not any(part.upper().startswith(('SEAL', 'SCORE')) and not part.endswith('.py') for part in parts_raw)
            and not any(part in ('auth.json', '.netrc', '.env') or part.startswith('.env.') for part in parts_raw),
            'Study state, outcomes, credentials or private contents are forbidden metadata inputs')
    require(raw.startswith('/private/tmp/') or raw.startswith(str(AF) + '/')
            or raw.startswith(str(TIMESTAMP_ROOT) + '/')
            or raw in (SPECIFICATION['path'], SPECIFICATION_2['path'], ERRATUM['path']),
            'Metadata read escaped the exact source/timestamp timestamp_checks roots')
    directory_flags = os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW | os.O_CLOEXEC
    file_flags = os.O_RDONLY | os.O_NOFOLLOW | os.O_CLOEXEC
    handles, edges = [], []
    try:
        common = sys.modules.get('common')
        directory_open = getattr(common, 'open_directory_metadata', None)
        handles.append(directory_open('/') if directory_open else os.open('/', directory_flags))
        root_stat = os.fstat(handles[0])
        require(stat.S_ISDIR(root_stat.st_mode), 'Metadata filesystem root is not a directory')
        parts = PurePosixPath(raw).parts[1:]
        require(bool(parts), 'Metadata regular-file leaf required')
        parent_path = '/'
        for part in parts[:-1]:
            parent = handles[-1]
            previous = os.stat(part, dir_fd=parent, follow_symlinks=False)
            require(stat.S_ISDIR(previous.st_mode) and not stat.S_ISLNK(previous.st_mode),
                    'Metadata parent must be a real directory')
            descriptor = (directory_open(part, dir_fd=parent, parent_path=parent_path) if directory_open
                          else os.open(part, directory_flags, dir_fd=parent))
            handles.append(descriptor)
            require(_metadata_key(os.fstat(descriptor)) == _metadata_key(previous),
                    'Metadata directory changed while opening')
            edges.append((parent, part, descriptor, _metadata_key(previous)))
            parent_path = str(PurePosixPath(parent_path) / part)
        parent, leaf = handles[-1], parts[-1]
        previous = os.stat(leaf, dir_fd=parent, follow_symlinks=False)
        require(stat.S_ISREG(previous.st_mode) and not stat.S_ISLNK(previous.st_mode),
                'Metadata leaf must be a real regular file')
        require(previous.st_size <= (1 << 24), 'Metadata file exceeds bounded read allowance')


        descriptor = os.open(raw, file_flags)
        handles.append(descriptor)
        opened = os.fstat(descriptor)
        require(_metadata_key(opened) == _metadata_key(previous) and opened.st_size == previous.st_size,
                'Metadata file changed while opening')


        require(_metadata_key(os.stat(leaf, dir_fd=parent, follow_symlinks=False)) == _metadata_key(opened),
                'Metadata leaf binding changed before read')
        for edge_parent, name, child, expected in edges:
            require(_metadata_key(os.fstat(child)) == expected
                    and _metadata_key(os.stat(name, dir_fd=edge_parent, follow_symlinks=False)) == expected,
                    'Metadata directory ancestry changed before read')
        blocks = []
        while True:
            block = os.read(descriptor, 1 << 20)
            if not block:
                break
            blocks.append(block)
            require(sum(map(len, blocks)) <= (1 << 24), 'Metadata file grew beyond bounded read allowance')
        payload = b''.join(blocks)
        after = os.fstat(descriptor)
        require(_metadata_key(after) == _metadata_key(opened) and len(payload) == opened.st_size == after.st_size
                and after.st_mtime_ns == opened.st_mtime_ns and after.st_ctime_ns == opened.st_ctime_ns,
                'Metadata file changed during read')
        require(_metadata_key(os.stat(leaf, dir_fd=parent, follow_symlinks=False)) == _metadata_key(opened),
                'Metadata leaf binding changed during read')
        for edge_parent, name, child, expected in edges:
            require(_metadata_key(os.fstat(child)) == expected
                    and _metadata_key(os.stat(name, dir_fd=edge_parent, follow_symlinks=False)) == expected,
                    'Metadata directory ancestry changed during read')
        require(_metadata_key(os.fstat(handles[0])) == _metadata_key(root_stat), 'Metadata root identity drift')
        return payload
    except PermissionError:
        raise
    except (OSError, ValueError, TypeError, AttributeError) as exc:
        raise PermissionError('Cannot verify read-only metadata path') from exc
    finally:
        for descriptor in reversed(handles):
            os.close(descriptor)


def identity(path):
    raw = canonical(path)
    payload = read_metadata(raw)
    return {'path': raw, 'bytes': len(payload), 'sha256': hashlib.sha256(payload).hexdigest()}


def row_identity(row):
    require(isinstance(row, dict) and set(row) == {'path', 'bytes', 'sha256'}, 'Exact metadata identity schema required')
    require(type(row['bytes']) is int and row['bytes'] >= 0 and isinstance(row['sha256'], str)
            and re.fullmatch('[0-9a-f]{64}', row['sha256']) is not None, 'Invalid metadata identity')
    return {'path': canonical(row['path']), 'bytes': row['bytes'], 'sha256': row['sha256']}


def parse_manifest(payload, label):
    require(isinstance(label, str) and re.fullmatch('[A-Z][A-Z0-9_]*', label) is not None,
            'Invalid timestamp label')
    headers, rows, paths = {}, [], set()
    for line in payload.decode('utf-8').splitlines():
        if line.startswith('# '):
            key, sep, value = line[2:].partition(': ')
            if sep:
                require(key not in headers, 'Duplicate timestamp manifest header')
                headers[key] = value
        elif line.strip():
            match = re.fullmatch(r'([0-9a-f]{64})  (\d+)  (.+)', line)
            require(match is not None, 'Invalid timestamp manifest row')
            digest, size, relative = match.groups()
            require(not relative.startswith('/') and str(PurePosixPath(relative)) == relative
                    and not any(part in ('.', '..') for part in relative.split('/')),
                    'Invalid timestamp manifest relative path')
            raw = canonical(str(Q / relative))
            require(raw not in paths, 'Duplicate timestamp manifest artifact path')
            paths.add(raw)
            rows.append({'path': raw, 'bytes': int(size), 'sha256': digest})
    require(headers.get('label') == label and headers.get('root') == str(Q), 'Timestamp root or label mismatch')
    require(bool(rows), 'Empty timestamp manifest cannot authorize release')
    return headers, rows


def verify_timestamp_bundle(label, required_identities, expected_metadata=None):

    try:
        require(isinstance(label, str) and re.fullmatch('[A-Z][A-Z0-9_]*', label) is not None,
                'Invalid timestamp label')
        require(isinstance(required_identities, list) and bool(required_identities), 'Timestamp required identity list required')
        required = [row_identity(row) for row in required_identities]
        require(len({row['path'] for row in required}) == len(required), 'Duplicate required timestamp identity')
        bundle = TIMESTAMP_ROOT / label
        names = ['MANIFEST_' + label + '.sha256', label + '_RESULT.json',
                 label + '_freetsa.tsr', label + '_digicert.tsr']
        actual = {name: identity(bundle / name) for name in names}
        if expected_metadata is not None:
            require(isinstance(expected_metadata, dict) and set(expected_metadata) == set(names),
                    'Exact pinned timestamp metadata inventory required')
            require(all({key: actual[name][key] for key in ('bytes', 'sha256')} == expected_metadata[name] for name in names),
                    'Timestamp timestamp_checks metadata drift')
        manifest_path = bundle / names[0]
        headers, entries = parse_manifest(read_metadata(manifest_path), label)
        for row in required:
            require(row in entries, 'Timestamp manifest does not bind exact required artifact')
        result = json.loads(read_metadata(bundle / names[1]))
        require(result.get('label') == label and result.get('manifest') == names[0]
                and result.get('manifest_sha256') == actual[names[0]]['sha256'], 'Timestamp result association mismatch')
        require(type(result.get('files')) is int and result['files'] == len(entries)
                and type(result.get('bytes')) is int and result['bytes'] == sum(row['bytes'] for row in entries),
                'Timestamp result census mismatch')
        require(isinstance(result.get('tsa'), dict) and set(result['tsa']) == set(TSA_URLS),
                'Both established TSA result entries required')
        for filename, expected in TRUST_PINS.items():
            require({key: identity(TRUST_ROOT / filename)[key] for key in ('bytes', 'sha256')} == expected,
                    'Established timestamp trust material drift')
        evidence = {}
        for tsa, url in TSA_URLS.items():
            recorded = result['tsa'][tsa]
            require(isinstance(recorded, dict) and recorded.get('url') == url and recorded.get('http_ok') is True
                    and recorded.get('verified') is True and isinstance(recorded.get('verify_output'), str)
                    and 'Verification: OK' in recorded['verify_output'].splitlines(), 'Recorded TSA verification evidence absent')
            receipt = bundle / (label + '_' + tsa + '.tsr')
            command = [OPENSSL, 'ts', '-verify', '-data', str(manifest_path), '-in', str(receipt)]
            command += ['-CAfile', str(TRUST_ROOT / ('freetsa_cacert.pem' if tsa == 'freetsa' else 'macos_system_roots.pem'))]
            if tsa == 'freetsa':
                command += ['-untrusted', str(TRUST_ROOT / 'freetsa_tsa.crt')]
            verified = subprocess.run(command, capture_output=True, text=True, timeout=30)
            require(verified.returncode == 0 and 'Verification: OK' in (verified.stdout + verified.stderr).splitlines(),
                    'Actual RFC3161 receipt does not verify against the bound manifest')
            reply = subprocess.run([OPENSSL, 'ts', '-reply', '-in', str(receipt), '-text'],
                                   capture_output=True, text=True, timeout=30)
            times = [line.split(':', 1)[1].strip() for line in reply.stdout.splitlines() if line.startswith('Time stamp:')]
            require(reply.returncode == 0 and len(times) == 1 and times[0] == recorded.get('time_stamp'),
                    'Actual RFC3161 time disagrees with bound result')
            stamp = dt.datetime.strptime(times[0], '%b %d %H:%M:%S %Y GMT').replace(tzinfo=dt.timezone.utc)
            evidence[tsa] = {'receipt': actual[receipt.name], 'verified': True, 'time_stamp': times[0], 'utc': stamp.isoformat()}

        require(all(identity(bundle / name) == actual[name] for name in names), 'Timestamp metadata changed during verification')
        require(all(identity(row['path']) == row for row in required), 'Required timestamp artifact drift')
        return {'schema': 'FORECAST_BINDING7_VERIFIED_RFC3161_V1', 'label': label, 'manifest': actual[names[0]],
                'result': actual[names[1]], 'required_identities': required, 'manifest_rows': entries,
                'headers': headers, 'tsa': evidence}
    except PermissionError:
        raise
    except (OSError, ValueError, TypeError, KeyError, AttributeError, subprocess.SubprocessError) as exc:
        raise PermissionError('Cannot verify exact timestamp timestamp_checks') from exc


def verify_specification():
    require(identity(SPECIFICATION['path']) == SPECIFICATION, 'Exact pre-outcome deadline specification SHA-256 required')
    require(identity(SPECIFICATION_2['path']) == SPECIFICATION_2, 'Exact pre-outcome no-calendar-deadline specification required')
    require(identity(ERRATUM['path']) == ERRATUM, 'Exact recorded-time erratum identity required')
    first = verify_timestamp_bundle('T4I', [SPECIFICATION], TIMESTAMP_PINS['T4I'])
    second = verify_timestamp_bundle('T4J', [SPECIFICATION_2], TIMESTAMP_PINS['T4J'])
    require(first['tsa']['freetsa']['utc'] == '2026-10-05T10:28:35+00:00'
            and first['tsa']['digicert']['utc'] == '2026-10-05T10:28:36+00:00', 'Pinned T4I timestamp time mismatch')
    require(second['tsa']['freetsa']['utc'] == '2026-10-05T10:32:36+00:00'
            and second['tsa']['digicert']['utc'] == '2026-10-05T10:32:37+00:00', 'Pinned T4J timestamp time mismatch')
    require(max(row['utc'] for row in first['tsa'].values()) < min(row['utc'] for row in second['tsa'].values()),
            'Specification 1 must precede specification 2 in both verified TSA responses')
    return {'schema': 'FORECAST_BINDING7_DEADLINE_AUTHORITY_V2',
            'ordered_specifications': [{'specification': SPECIFICATION.copy(), 'timestamp': first},
                                   {'specification': SPECIFICATION_2.copy(), 'timestamp': second}],
            'erratum': {'identity': ERRATUM.copy(), 'timestamp_binding': None, 'content_changed': False},
            'calendar_rule': CALENDAR_RULE, 'clauses_1_through_4_unchanged': True,
            'before_T5_required': True, 'new_calendar_deadline': None,
            'authoritative_T4J_utc': '2026-10-05T10:32:36+00:00',
            'rounded_specification_2_recorded_utc_is_authority': False}


def historical_snapshot(verify_current=True, verify_tsa=True):

    manifest = TIMESTAMP_ROOT / 'T4F/MANIFEST_T4F.sha256'
    expected = TIMESTAMP_PINS['T4F'][manifest.name]
    current = identity(manifest)
    require({key: current[key] for key in ('bytes', 'sha256')} == expected, 'Exact T4F manifest identity drift')
    headers, rows = parse_manifest(read_metadata(manifest), 'T4F')
    require(len(rows) == 47 and sum(row['bytes'] for row in rows) == 674446
            and all(row['path'].startswith(str(AF) + '/') for row in rows), 'Exact T4F AF historical inventory required')
    if verify_current:
        require(all(identity(row['path']) == row for row in rows), 'T4F-committed AF source bytes changed')
    evidence = verify_timestamp_bundle('T4F', rows, TIMESTAMP_PINS['T4F']) if verify_tsa else None
    return {'schema': 'FORECAST_BINDING7_T4F_HISTORICAL_SNAPSHOT_V1', 'label': 'T4F', 'manifest': current,
            'files': rows, 'created_utc': headers['created_utc'], 'verified_current_bytes': verify_current,
            'timestamp_verification': evidence,
            'includes_overlay': False, 'includes_final_root_mapping': False}
