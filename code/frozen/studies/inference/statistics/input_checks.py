'Check metadata paths for numerical inputs and synthetic tests.'
import hashlib
import json
import os
from pathlib import Path

HERE = Path(__file__).resolve().parent


class Pending(ValueError):
    pass


def require(condition, message):
    if not condition:
        raise Pending(message)


def canonical(value):
    return json.dumps(value, ensure_ascii=False, allow_nan=False,
                      sort_keys=True, separators=(',', ':'))


def json_bytes(value):
    return (canonical(value) + '\n').encode('utf-8')


def checked_bytes(path, checked_source):

    p = Path(path)
    require(p.is_absolute() and p.resolve() == p and not p.is_symlink(),
            'Aliased source path')
    data = checked_source(p)
    require(type(data) is bytes, 'Checked source must return exact bytes')
    require(p.read_bytes() == data, 'Source changed after independent verification')
    return data


def source_identity(path):
    p = Path(path)
    require(p.is_file() and not p.is_symlink(), 'Missing/aliased public source')
    data = p.read_bytes()
    return dict(path=str(p.resolve()), bytes=len(data), sha256=hashlib.sha256(data).hexdigest())


def verify_source(item):
    require(source_identity(item['path']) == item, 'Public source identity drift')


def artificial_accept(fixture_root):
    require(os.environ.get('SCORING_PHASE', 'prepare') == 'accept', 'Prepare: no numerical execution')
    p = Path(fixture_root)
    require(p.is_absolute() and not p.is_symlink() and
            p.resolve() == p and p.is_relative_to(Path('/private/tmp')) and
            p != Path('/private/tmp'), 'Explicit canonical artificial fixture root required')
    return p


def no_production_entry(*args, **kwargs):
    raise Pending('WAIT FOR reviewed C8B, RD7 clean receipt/REV6 and separate source release')
