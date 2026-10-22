"""Identity and retained I/O helpers. Import opens no study input."""
from pathlib import Path
import datetime as dt
import hashlib
import importlib.util
import json
import os
import sys
import uuid
import tempfile
import shutil

sys.dont_write_bytecode = True
OUT = Path(__file__).resolve().parents[1]
LEGACY_OUT = OUT.parent
Q = LEGACY_OUT.parent
CONF = Q / 'CONF'
ADAPTER = CONF / 'CONFX2'
PROJ = Q.parents[1]
SEED = 20260919
KEYS = ['origin', 'target_time', 'region', 'horizon']
R8_NEWS = ('M0', 'M+0', 'M+', 'L_count+', 'L_chen+')
R8_NOTICE = ('M0_n', 'M+0_n', 'M+_n', 'L14+', 'L_Laz+', 'L_chen_notice+')
PRIMARY_NOTICE = ('N', 'M_notice', 'L14', 'L_Laz', 'L_chen_notice')
DROP_ORDER = ('R8_news_seeds', 'R8_news', 'CPS8', 'PCX_extension')
STAGE_ORDER = ('B0', 'B1', 'B2', 'B3', 'B4', 'B5')
COMPLETE = ('COMPLETE', 'COMPLETE_WITH_UNAVAILABLE_CONFIGURATIONS')

def require(ok, message):
    if not ok:
        raise RuntimeError(message)

def now():
    return dt.datetime.now(dt.timezone.utc).isoformat()

def sha(path):
    h = hashlib.sha256()
    with Path(path).open('rb') as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b''):
            h.update(block)
    return h.hexdigest()

def identity(path, **extra):
    p = Path(path).resolve()
    return dict(path=str(p), bytes=p.stat().st_size, sha256=sha(p), **extra)

def checked(item):
    p = Path(item['path'])
    require(p.is_file() and p.stat().st_size == item['bytes'] and sha(p) == item['sha256'],
            'Identity drift: ' + str(p))
    return p

def read_json(path):
    return json.loads(Path(path).read_text())

def write_json(path, value, exclusive=False, retain_revision=True):
    """Durable atomic replacement; old receipts survive, ledger heartbeats do not multiply."""
    p = Path(path)
    p.parent.mkdir(parents=True, exist_ok=True)
    payload = json.dumps(value, indent=2, sort_keys=True, ensure_ascii=False, allow_nan=False) + '\n'
    if p.exists():
        if p.read_text() == payload:
            return p
        require(not exclusive, 'Preserve immutable evidence: ' + str(p))
        if retain_revision:
            history = p.parent / 'revisions'
            history.mkdir(exist_ok=True)
            shutil.copyfile(p, history / (p.name + '.' + uuid.uuid4().hex))
    fd, temporary = tempfile.mkstemp(prefix=p.name+'.atomic.', dir=p.parent)
    with os.fdopen(fd, 'w') as stream:
        stream.write(payload)
        stream.flush()
        os.fsync(stream.fileno())
    if exclusive:
        # Link publishes without a race that could overwrite an immutable receipt.
        os.link(temporary,p)
        history = p.parent/'revisions'
        history.mkdir(exist_ok=True)
        os.rename(temporary,history/Path(temporary).name)
    else:
        os.replace(temporary, p)
    return p

def atomic_copy(source, destination, bound=False):
    """Publish a complete copy; retain unbound interrupted bytes before repair."""
    source, destination = Path(source), Path(destination)
    destination.parent.mkdir(parents=True, exist_ok=True)
    if destination.exists():
        if sha(destination) == sha(source):
            return destination
        require(not bound, 'Bound copy drift: '+str(destination))
        retained = destination.parent/'failed_attempts'/uuid.uuid4().hex
        retained.mkdir(parents=True, exist_ok=True)
        old = identity(destination)
        os.rename(destination, retained/destination.name)
        write_json(retained/'IDENTITY.json', dict(original=old, retained=identity(retained/destination.name)), exclusive=True)
    temporary = destination.with_name(destination.name+'.atomic.'+uuid.uuid4().hex)
    with source.open('rb') as src, temporary.open('xb') as dst:
        shutil.copyfileobj(src, dst, 1024*1024)
        dst.flush(); os.fsync(dst.fileno())
    require(sha(temporary) == sha(source), 'Copy source changed during transfer')
    os.replace(temporary, destination)
    return destination

class RemedyInterrupted(RuntimeError):
    """The sole remedied attempt started but never reached a terminal receipt."""

class ParityFailure(RuntimeError):
    """Only an actual inequality or absent registered reference is a parity failure."""

class ResourceStop(RuntimeError):
    """Recoverable batch stop: never export/seal an unfinished mandatory stage."""

class OverlapRefusal(ResourceStop):
    pass

class BatchDeviation(RuntimeError):
    """B0 execution failed after its one documented remedy; terminal batch."""

def verify_bundle(bundle, adapters, seen=None):
    base = dict(bundle, arm=bundle['cps8_base_arm'], variant='main') if 'cps8_base_arm' in bundle else bundle
    return adapters.storage.verify_bundle(base, seen=seen)

def module(path, name):
    spec = importlib.util.spec_from_file_location(name, path)
    result = importlib.util.module_from_spec(spec)
    sys.modules[name] = result
    spec.loader.exec_module(result)
    return result

SCORER_ONLY = {'code/a8batch_score.py','code/postscore_host.py','code/loss_export.py',
               'code/scorer_freeze.py','tests/test_score_endtoend.py','tests/test_scorer_contract.py','tests/test_scorer_review.py',
               'freeze_a8scorer.py','host_postscore_a8batch.sh','code/repin_postscore_launch.py',
               'tests/test_scorer_round4.py','code/pcx_turn.py','code/cutoff_snapshot.py'}

def code_files(scope='batch'):
    files = [*OUT.joinpath('code').glob('*.py'), *OUT.joinpath('tests').glob('*.py'),
             OUT/'freeze_a8batch.py',OUT/'freeze_a8_amendment2.py',OUT/'host_run_a8batch.sh']
    files += [p for p in (OUT/'freeze_a8scorer.py',OUT/'host_postscore_a8batch.sh') if p.exists()]
    return sorted(p for p in files if (str(p.relative_to(OUT)) in SCORER_ONLY) == (scope == 'scorer'))

def code_hashes(scope='batch'):
    return {str(p.relative_to(OUT)): sha(p) for p in code_files(scope)}

def normalize(frame):
    import pandas as pd
    frame = frame.copy()
    for col in ('origin', 'target_time'):
        frame[col] = pd.to_datetime(frame[col], utc=True).astype('datetime64[ns, UTC]')
    frame['target_day'] = frame.target_day.astype(str).str[:10]
    require(not frame.duplicated(KEYS).any() and not frame[KEYS].isna().any().any(), 'Invalid prediction keys')
    return frame.sort_values(KEYS, kind='stable').reset_index(drop=True)

def bytes_equal(a, b):
    return a.dtype == b.dtype and a.shape == b.shape and a.tobytes() == b.tobytes()
