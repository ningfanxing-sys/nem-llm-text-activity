'Read and compare forecast metadata records.'
import contextlib
import datetime as dt
import hashlib
import json
import os
from pathlib import Path
import re


class ChainStop(RuntimeError):
    pass


def require(ok, reason):
    if not ok:
        raise ChainStop(reason)


UNRESOLVED_SENTINELS = frozenset({'PENDING', 'TBD', 'UNKNOWN', 'PROVISIONAL',
                                  'SOURCE_SETS_ACTUAL_TIME'})


def unresolved_value(value, *, field=None, required=True):

    if value is None:
        return required
    if isinstance(value, str):
        token = value.strip().upper()
        if not token:
            return required
        if token in UNRESOLVED_SENTINELS:
            return True

        if re.fullmatch(r'PENDING(?:_[A-Z0-9]+)+', token):
            return True
        if (field and (field in ('state', 'status') or field.endswith(('_state', '_status')))
                and re.fullmatch(r'[A-Z0-9_ -]+', token)):
            return bool(UNRESOLVED_SENTINELS.intersection(re.split(r'[-_ ]+', token)))
    return value is True and field is not None and (field == 'pending' or field.endswith('_pending'))


def unresolved_values(value, trail='$', *, field=None, required=True):
    if isinstance(value, dict):
        for key, item in value.items():
            yield from unresolved_values(item, trail + '.' + key, field=key, required=required)
    elif isinstance(value, list):
        for index, item in enumerate(value):
            yield from unresolved_values(item, trail + '[' + str(index) + ']', field=field, required=required)
    elif unresolved_value(value, field=field, required=required):
        yield trail, value


def pending(value):
    return any(unresolved_values(value))


def encoded(value):
    return json.dumps(value, sort_keys=True, ensure_ascii=False, separators=(',', ':'), allow_nan=False).encode()


def digest(value):
    return hashlib.sha256(encoded(value)).hexdigest()


def row(path, data=None):
    path = Path(path).absolute()
    data = path.read_bytes() if data is None else data
    return dict(path=str(path), bytes=len(data), sha256=hashlib.sha256(data).hexdigest())


def metadata_path(path):
    p = Path(path)
    parts = p.parts[2:] if p.is_relative_to('/private/tmp') else p.parts
    require(p.is_absolute() and str(p) == os.fspath(path) and '..' not in p.parts,
            'Exact absolute metadata path required')
    require(not {'host_state', 'seals', 'scores', 'predictions', 'outcomes'}.intersection(x.lower() for x in parts)
            and not (p.name.upper().startswith('SEAL') and p.suffix != '.py'), 'Protected payload is not a chain input')
    return p


def checked(item, sources=None):
    p = metadata_path(item['path'])
    data = sources.bytes(p) if sources and str(p) in sources.rows else p.read_bytes()
    require(row(p, data) == item, 'Exact metadata/source identity drift: ' + str(p))
    return data


def document(item, sources=None):
    return json.loads(checked(item, sources))


def exclusive(path, value):
    path = metadata_path(path)
    data = json.dumps(value, sort_keys=True, ensure_ascii=False, indent=2, allow_nan=False).encode() + b'\n'
    with path.open('xb') as f:
        f.write(data)
    return row(path, data)


def utc(value):
    v = dt.datetime.fromisoformat(value.replace('Z', '+00:00'))
    require(v.utcoffset() == dt.timedelta(0), 'UTC with zero offset required')
    return v


def now():
    return dt.datetime.now(dt.timezone.utc).isoformat()


def exact_union(left, right):
    require(left and right, 'Both verified identity lists required')
    out = {}
    for item in [*left, *right]:
        require(set(item) == {'path', 'bytes', 'sha256'}, 'Exact identity row required')
        p = metadata_path(item['path'])
        require(item['bytes'] >= 0 and len(item['sha256']) == 64, 'Invalid identity row')
        require(str(p) not in out or out[str(p)] == item, 'Conflicting exact-union member')
        out[str(p)] = item
    return [out[k] for k in sorted(out)]


def accepted(item, subject, *, sources=None, role=None):
    value = document(item, sources)
    require(value.get('accepted') is True and value.get('independent') is True and
            value.get('reviewer') and value['reviewer'] != value.get('producer') and
            value.get('subject') == subject and (role is None or value.get('role') == role),
            'Real independent same-source acceptance required')
    utc(value['utc'])

    return value


def acknowledged(item, subject, *, sources=None, role=None):
    value=document(item,sources)
    require(value.get('accepted') is True and (value.get('owner') or value.get('reviewer')) and
            value.get('subject')==subject and (role is None or value.get('role')==role),
            'Actual same-source owner acknowledgement required')
    utc(value['utc'])
    return value


def load_control(path, action, build_identity):
    value = json.loads(Path(path).read_bytes())
    require(not pending(value), 'PENDING CONTROL: source must fill every value')
    require(value['schema'] == 'MINRUN_AF_CHAIN_CONTROL_V1' and value['action'] == action,
            'Action-specific CONTROL required')
    require(value['build'] == build_identity, 'Accepted AF-chain build identity drift')
    permit = document(value['permit'])
    subject = digest({k: v for k, v in value.items() if k != 'permit'})
    require(permit.get('schema') == 'MINRUN_AF_CHAIN_RELEASE_V1' and permit.get('released') is True and
            permit.get('action') == action and permit.get('control_sha256') == subject and permit.get('source'),
            'Separate real source permit required')
    require(permit.get('quiet_host_disposition') == value['quiet_host_disposition'], 'Quiet-host evidence mismatch')
    quiet = document(value['quiet_host_disposition'])
    require(quiet.get('source') and quiet.get('all_project_jobs_disposed') is True and
            quiet.get('no_source_writers') is True and quiet.get('before_T5') is True and
            quiet.get('no_scoring') is True, 'Real quiet-host/source-write disposition required')
    utc(permit['utc']); utc(quiet['utc'])
    return value


@contextlib.contextmanager
def flags(names):
    saved = {n: os.environ.get(n) for n in ['SCORING_PHASE', *names]}
    os.environ['SCORING_PHASE'] = 'source_runtime'
    for n in names:
        os.environ[n] = '1'
    try:
        yield
    finally:
        for n, v in saved.items():
            if v is None:
                os.environ.pop(n, None)
            else:
                os.environ[n] = v
