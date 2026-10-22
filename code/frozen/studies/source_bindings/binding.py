'Check the source chain against saved hashes and metadata.'
from pathlib import Path
import ast
import hashlib
import importlib.util
import json
import re
import sys
import threading
import datetime as dt
from types import ModuleType

sys.dont_write_bytecode = True
Q = Path(__file__).resolve().parent.parent
confirmation = Q / 'confirmation'
LAUNCH_TIMESTAMP_LABELS = dict.fromkeys(('ISOBATCH', 'batch_scoring', 'label_scoring', 'matched_controls'), 'T5')
SPECIFIED_ROOT_SHA = 'de80c4e0c3450f3e4383c477c4a3a088cc7d3956835f8ba5e51cf5d78944b394'
_guard_local = getattr(sys, '_repin8_guard_local', threading.local())
sys._repin8_guard_local = _guard_local

def _read_guard(event, args):
    if getattr(_guard_local, 'active', False) and event == 'open' and isinstance(args[0], (str, bytes)):
        safe(args[0])

if not getattr(sys, '_repin8_read_guard_installed', False):
    sys.addaudithook(_read_guard)
    sys._repin8_read_guard_installed = True

def require(ok, message):
    if not ok:
        raise PermissionError(message)

def safe(path):
    p = Path(path).resolve()
    forbidden = {'host_state', 'scored', 'a2_scored', 'a3_scored',
                 'a4_scored', 'predictions', 'evaluation', 'run', 'seals', 'scores'}
    require(not forbidden.intersection(p.parts), 'Forbidden payload: ' + str(p))
    require('/semantic_validation/private/' not in str(p), 'Forbidden private review: ' + str(p))
    require('/Keychains/' not in str(p) and '/.aws/credentials' not in str(p) and
            '/huggingface/token' not in str(p), 'Forbidden credential path: ' + str(p))
    require(p.name not in {'SEAL.json', 'SCORE_RECEIPT.json', 'auth.json', '.env', '.netrc'}
            and not p.name.lower().startswith(('prediction', 'score_receipt', 'seal_attestation')),
            'Forbidden payload: ' + str(p))
    return p

def sha(path):
    h = hashlib.sha256()
    with safe(path).open('rb') as f:
        for block in iter(lambda: f.read(1 << 20), b''):
            h.update(block)
    return h.hexdigest()

def read(path):
    return json.loads(safe(path).read_text())

def verified_json(item):
    p = safe(item['path']); data = p.read_bytes()
    require(len(data) == item['bytes'] and hashlib.sha256(data).hexdigest() == item['sha256'], 'Verified JSON snapshot drift')
    return json.loads(data)


def identity(path):
    p = safe(path)
    return dict(path=str(p), sha256=sha(p), bytes=p.stat().st_size)

def checked(item):
    p = safe(item['path'])
    require(p.is_file() and sha(p) == item['sha256'] and
            ('bytes' not in item or p.stat().st_size == item['bytes']), 'Identity drift: ' + str(p))
    return p

def neutral(obj):
    if isinstance(obj, dict):
        return {k: neutral(v) for k, v in obj.items() if k != 'path'}
    if isinstance(obj, list):
        return [neutral(v) for v in obj]
    return obj

def latest(root):

    root = Path(root).resolve()
    task = read(root/'ADAPTER_FREEZE.json').get('execution_specification', {}).get('task', '')
    require(re.fullmatch('SPEC_\\d+', task), 'No installed specification chain')
    path = root.parent/task/'SPECIFIED_ADAPTER_CHAIN.json'
    require(path.is_file(), 'Missing installed chain record')
    return path

class Snapshot:

    def __init__(self):
        self.items, self.parsed = {}, {}
    def ident(self, path):
        p = safe(path)
        if str(p) not in self.items:
            self.items[str(p)] = identity(p)
        return self.items[str(p)]
    def bytes(self, path):
        p = safe(path); expected = self.ident(p)
        require(expected['bytes'] <= 2*1024*1024, 'Snapshot byte read exceeds small-code limit')
        data = p.read_bytes()
        require(hashlib.sha256(data).hexdigest() == expected['sha256'], 'Snapshot drift')
        return data
    def lines(self, path):
        p = safe(path); self.ident(p)
        with p.open('r') as stream:
            yield from stream
    def check(self, item):
        p = safe(item['path']); actual = self.ident(p)
        require(actual['sha256'] == item['sha256'] and
                ('bytes' not in item or actual['bytes'] == item['bytes']), 'Identity drift: ' + str(p))
        return p
    def json(self, path):
        p = safe(path)
        if str(p) not in self.parsed:
            self.parsed[str(p)] = json.loads(self.bytes(p))
        return self.parsed[str(p)]
    def finish(self):
        for item in self.items.values():
            checked(item)


def identities(obj):
    if isinstance(obj, dict):
        if {'path', 'sha256', 'bytes'} <= obj.keys():
            yield obj
        else:
            for v in obj.values():
                yield from identities(v)
    elif isinstance(obj, list):
        for v in obj:
            yield from identities(v)


def flags(chain):
    require(chain.get('original_input_freeze_and_authorization_retained') is True,
            'Original input authorization not retained')
    if 'primary_decision_rule_change' in chain:
        require(chain['primary_decision_rule_change'] is False, 'Primary decision rule changed')


def timestamp_binding(conf, wanted, prefix, snapshot=None, not_before=None):

    snap = snapshot or Snapshot()
    q = Path(conf).parent
    expected = {str(Path(i['path']).relative_to(q)): dict(sha256=i['sha256'], bytes=i['bytes']) for i in wanted}
    for folder in sorted((Path(conf) / 'TIMESTAMPS').glob(prefix)):
        label = folder.name; result = folder / (label + '_RESULT.json')
        if not result.is_file():
            continue
        rec = snap.json(result); manifest = folder / ('MANIFEST_' + label + '.sha256')
        if prefix == 'T4':
            anchors = read(Path(__file__).parent/'SPECIFIED_ANCHORS.json')
            for name, target in [('result', result), ('manifest', folder/('MANIFEST_'+label+'.sha256'))]:
                require(snap.ident(target)['sha256'] == anchors['T4'][name], 'Specified T4 identity drift')
        if prefix == 'T5':
            scored = Path(conf)/'execution/host_state/scored'
            if scored.exists():
                receipt = scored/'SCORE_RECEIPT.json'
                input_checks = receipt.stat().st_mtime_ns if receipt.exists() else scored.stat().st_mtime_ns
                require(result.stat().st_mtime_ns < input_checks, 'T5 must precede score')
        require(rec.get('label') == label and rec.get('manifest') == manifest.name, 'Timestamp label mismatch')
        require(snap.ident(manifest)['sha256'] == rec.get('manifest_sha256'), 'Timestamp manifest drift')
        found = {}
        for line in snap.lines(manifest):
            parts = line.rstrip('\n').split('  ', 2)
            if len(parts) == 3 and parts[2] in expected:
                require(parts[2] not in found, 'Duplicate timestamp identity')
                found[parts[2]] = dict(sha256=parts[0], bytes=int(parts[1]))
        if any(found.get(k) != v for k,v in expected.items()):
            continue
        tsa = rec.get('tsa', {})
        require(len(tsa) >= 2 and all(i.get('verified') is True for i in tsa.values()), 'Two verified TSA required')
        for name, item in tsa.items():
            require(re.fullmatch('[a-zA-Z0-9_-]+', name), 'Invalid TSA name')
            stamp = dt.datetime.strptime(item['time_stamp'], '%b %d %H:%M:%S %Y GMT').replace(tzinfo=dt.timezone.utc)
            require(not_before is None or stamp >= not_before, 'Timestamp predates freeze')
            snap.ident(folder / (label + '_' + name + '.tsr'))
        if snapshot is None:
            snap.finish()
        return dict(label=label, manifest=snap.ident(manifest), result=snap.ident(result))
    raise PermissionError('No verified ' + prefix + ' timestamp covers required identities')


def verify_adapter(root=None, specified_sha=None):
    root = Path(root or confirmation / 'execution').resolve()
    ancestor_sha = specified_sha or SPECIFIED_ROOT_SHA
    snap = Snapshot(); path = latest(root); chain = snap.json(path)
    require(int(path.parent.name[5:]) >= 8, 'news_memory or newer installed chain required')
    require(chain.get('state') == 'EXECUTION_SPECIFICATION_CHAIN_FROZEN', 'Unfrozen latest chain')
    anchors = read(Path(__file__).parent/'SPECIFIED_ANCHORS.json')
    require(snap.ident(path)['sha256'] == anchors['chain'] and
            snap.ident(root/'ADAPTER_FREEZE.json')['sha256'] == anchors['freeze'], 'Specified installation identity drift')
    flags(chain)
    steps = chain.get('steps', []); tasks = [s['task'] for s in steps]
    require(tasks == ['SPEC_' + str(n) for n in range(3, int(path.parent.name[5:]) + 1)], 'Broken specified sequence')
    require(chain.get('specified_chain') == ['input-bound original', *tasks], 'Specified chain mismatch')
    require(chain['input_bound_root']['sha256'] == ancestor_sha, 'Specified ancestor mismatch')
    require(steps[-1]['adapter_freeze'] == chain['specified_adapter_freeze'] and
            Path(chain['specified_adapter_freeze']['path']).resolve() == root / 'ADAPTER_FREEZE.json', 'Installed adapter mismatch')

    records = {tasks[-1]: chain}
    for n in range(int(path.parent.name[5:]) - 1, 2, -1):
        task = 'SPEC_' + str(n); successor = records['SPEC_' + str(n + 1)]
        ref = successor.get(task.lower() + '_chain_record')
        if ref is None:
            ref = next(s for s in successor['steps'] if s['task'] == task).get('chain_record')
        history = root.parent / task / 'SPECIFIED_ADAPTER_CHAIN.json'
        require(ref is not None and Path(ref['path']).resolve() == history, 'Missing successor record pin: ' + task)
        snap.check(ref); records[task] = snap.json(history); flags(records[task])
    for rec in records.values():
        for item in identities(rec):
            p = safe(item['path']); require(p.is_relative_to(root.parent), 'Chain path escaped confirmation')

            if p == root / 'ADAPTER_FREEZE.json' and item['sha256'] != chain['specified_adapter_freeze']['sha256']:
                require(any(s['adapter_freeze']['sha256'] == item['sha256'] for s in steps), 'Unknown historical freeze')
            else:
                snap.check(item)
    current_path = snap.check(chain['specified_adapter_freeze']); current = snap.json(current_path)
    require(current.get('state') == 'SPEC_2_FROZEN_SYNTHETICALLY_VERIFIED' and
            current.get('execution_specification', {}).get('task') == tasks[-1], 'Installed task mismatch')
    for rel, item in current['files'].items():
        p = (root / rel).resolve(); require(p.is_relative_to(root.parent), 'Adapter path escaped confirmation')
        snap.check(dict(path=str(p), **item))
    for index, step in enumerate(steps):
        previous = ancestor_sha if index == 0 else steps[index - 1]['adapter_freeze']['sha256']
        require(step['parent_adapter_freeze']['sha256'] == previous, 'Broken ancestor freeze link')
        specification = snap.json(step['adapter_freeze']['path']).get('execution_specification', {})
        require(specification.get('task') == step['task'] and neutral(specification.get('parent_adapter_freeze')) == neutral(step['parent_adapter_freeze']), 'Step/manifest ancestry mismatch')
        require(all(specification.get(k) == v for k,v in step['declaration'].items()), 'Chain/manifest declaration mismatch')
        if int(step['task'][5:]) >= 8:
            require(specification.get('no_statistical_design_or_feature_content_change') is True and
                    'feature_content_change' not in specification, 'Non-resource descendant refused')
        historical = records[step['task']]
        if index == 0:
            require(historical['state'] == 'EXECUTION_ONLY_SPECIFICATION_FROZEN' and
                    neutral(historical['parent_adapter_freeze']) == neutral(step['parent_adapter_freeze']) and
                    neutral(historical['specified_adapter_freeze']) == neutral(step['adapter_freeze']) and
                    historical.get('no_statistical_design_or_feature_content_change') is True, 'shared_storage record drift')
        else:
            expected = neutral(steps[:index + 1])
            if 'chain_record' not in historical['steps'][-1]:
                expected[-1].pop('chain_record', None)
            require(historical.get('state') == chain['state'] and
                    neutral(historical['input_bound_root']) == neutral(chain['input_bound_root']) and
                    neutral(historical.get('steps')) == expected and
                    historical.get('specified_chain') == ['input-bound original', *tasks[:index + 1]] and
                    neutral(historical['specified_adapter_freeze']) == neutral(step['adapter_freeze']), 'Historical prefix drift')

    runtime_path = root / 'runtime.py'; runtime = ModuleType('_repin8_verified_runtime')
    runtime.__file__ = str(runtime_path)
    exec(compile(snap.bytes(runtime_path), str(runtime_path), 'exec'), runtime.__dict__)
    runtime.sha256 = lambda p: snap.ident(p)['sha256']
    runtime.read_json = snap.json
    runtime.verify_identities = lambda items: [snap.check(i) for i in items]
    _guard_local.active = True
    try:
        _, verified = runtime.adapter_specification_chain(root, ancestor_sha)
        for index, step in enumerate(verified):
            for rel, item in step['ancestor']['files'].items():
                original = (root / rel).resolve(); key = str(original.relative_to(root.parent))
                archived = [later['reference_snapshot'][key] for later in verified[index:] if key in later['reference_snapshot']]
                candidate = Path(archived[0]['archive_path']) if archived else original
                require(safe(candidate).is_relative_to(root.parent), 'Ancestor escaped confirmation')
                snap.check(dict(path=str(candidate), **item))
    finally:
        _guard_local.active = False
    wanted = [snap.ident(root.parent / task / 'SPECIFIED_ADAPTER_CHAIN.json') for task in tasks]
    stamp = dt.datetime.fromisoformat(chain['time_utc'].replace('Z', '+00:00'))
    require(stamp.utcoffset() == dt.timedelta(0), 'Chain must carry UTC time')
    timestamp = timestamp_binding(root.parent, wanted + [snap.ident(current_path)], 'T4', snap, stamp)
    snap.finish()
    require(latest(root) == path, 'Tip changed during verification')
    return dict(task=tasks[-1], chain=snap.ident(path), adapter_freeze_sha256=snap.ident(current_path)['sha256'],
                adapter_root=str(root), adapter_files=list(snap.items.values()), ancestor_sha256=ancestor_sha, timestamp=timestamp)

def delivery(stage, shared=None):
    stage = Path(stage).resolve(); shared = Path(shared or Path(__file__).resolve().parent).resolve()
    listing = read(stage/'DELIVERY_SET.json')
    paths = [stage/rel for rel in listing['code_and_specs']]
    for p in paths:
        require(p.resolve().is_relative_to(stage), 'Delivery symlink escaped stage')
    paths += [shared/name for name in listing['shared']]
    return [identity(p) for p in sorted(paths)]

def verify_repin(stage, full=None):
    stage = Path(stage).resolve()
    rec = read(stage/'REPIN_FREEZE.json')

    if full is None:
        from overlap import trusted_control
        full = not trusted_control(stage)
    for i in rec['delivery_files'] + rec['source_files'] + rec['retained_files'] + rec['adapter_files']:
        checked(i)
    for name in ('old_freeze', 'tests'):
        checked(rec[name])
    config = verified_json(next(i for i in rec['delivery_files'] if Path(i['path']).resolve() == stage/'SOURCE_BINDING.json'))
    require(rec['batch'] == config['batch'] and rec['source_files'] == config['source_files'] and
            rec['old_freeze'] == config['old_freeze'] and
            Path(rec['tests']['path']).resolve() == stage/config['test_receipt'], 'Re-pin batch/source timestamp_checks mismatch')
    require(rec['delivery_files'] == delivery(stage), 'Re-pin delivery set drift')
    if full:
        allowed = {Path(i['path']).resolve() for i in rec['delivery_files']}
        require(all(p.resolve() in allowed for p in stage.glob('*.py')), 'New importable delivery module at stage root')
        for directory in ('code', 'tests'):
            require(all(p.resolve() in allowed for p in (stage/directory).rglob('*.py')
                        if '__pycache__' not in p.parts), 'New importable delivery module')
        verify_legacy(config)
    require(rec['state'] == 'REPIN_SPEC_8_FROZEN', 'Wrong re-pin freeze state')
    aliases = {'batch_scoring': ['CODE_FREEZE.json'], 'label_scoring': ['CODE_FREEZE.json', 'CODE_FREEZE_A2X.json'], 'matched_controls': ['PCX_FREEZE.json']}
    for name in aliases.get(rec['batch'], []):
        require(sha(stage/name) == sha(stage/'REPIN_FREEZE.json'), 'Re-pin alias drift: ' + name)
    if full:
        live = verify_adapter(rec['adapter_root'])
        require(live['adapter_freeze_sha256'] == rec['adapter_freeze_sha256'] and
                live['chain'] == rec['chain'] and live['adapter_files'] == rec['adapter_files'], 'Installed adapter changed; new additive re-pin required')
    rec['_verified_config'] = config
    return rec

def pinned_adapter(stage, root):

    if not (Path(stage)/'REPIN_FREEZE.json').exists():
        return verify_adapter(root)
    rec = verify_repin(stage, full=False)
    require(Path(rec['adapter_root']).resolve() == Path(root).resolve(), 'Wrong pinned adapter root')
    return rec


R11_SHA = 'a9616ede2595020bbcf5df9e524993376acf5c618c97b6837c34d7ec1d77455e'

def legacy_item(item, config):
    if config['batch'] == 'label_scoring' and Path(item['path']).name == 'STATE_SOURCE_DELIVERY.md':
        require(item['sha256'] == R11_SHA and item['bytes'] == 5188 and
                Path(item['path']).resolve() == confirmation/'fit_memory/STATE_SOURCE_DELIVERY.md', 'R11 identity not specified')
        archived = dict(item, path=str(confirmation/'fit_memory/archive/inactive/STATE_SOURCE_DELIVERY_2026-10-02T2350.md'))
        checked(archived)
        return archived
    checked(item)
    return item


def verify_legacy(config):

    old = read(checked(config['old_freeze'])); base = Path(config['old'])
    items = []
    if config['batch'] == 'ISOBATCH':
        items += [old[k] for k in ('original_spec_freeze', 'original_freeze', 'spec', 'specification', 'logic_check', 'diff')]
        current = {str(p.relative_to(base)): sha(p) for p in sorted(base.rglob('*.py')) if '__pycache__' not in p.parts}
        require(current == old['code_sha256'], 'Original ISOBATCH code set drift')
    if config['batch'] == 'batch_scoring':
        paths = sorted([*(base/'code').rglob('*.py'), *(base/'tests').rglob('*.py'), base/'freeze_a2batch.py', base/'host_run_a2batch.sh'])
        require({str(p.relative_to(base)): sha(p) for p in paths} == old['code_sha256'], 'Original batch_scoring code set drift')
        items += [old['spec'], old['tests'], *old['external_files']]
    if config['batch'] == 'label_scoring':
        items += old['files'] + old['upstream_helpers'] + [old['tests']]
        extra = read(checked(config['original_a2x_freeze']))
        items += [extra['original_code_freeze'], *extra['files'], extra['tests']]
        paths = sorted([*(base/'code').glob('*.py'), *(base/'tests').glob('*.py'), base/'freeze_a2label_a2x.py', base/'RUNBOOK_A2X.md'])
        require({i['path'] for i in extra['files']} == {str(p.resolve()) for p in paths}, 'Original A2X code set drift')
    if config['batch'] == 'matched_controls':
        parent = read(read(latest(confirmation/'execution'))['steps'][-1]['parent_adapter_freeze']['path'])
        replaced = {str((confirmation/'execution'/rel).resolve()) for rel in parent['files']}
        replaced.add(str(confirmation/'execution/ADAPTER_FREEZE.json'))
        items += [i for i in old['bound_files'] if str(Path(i['path']).resolve()) not in replaced]
    summary = [i for i in items if not isinstance(i, dict) or not {'path','sha256','bytes'} <= i.keys()]
    config['_legacy_non_identity'] = summary
    items = [legacy_item(i, config) for i in items if isinstance(i, dict) and {'path','sha256','bytes'} <= i.keys()]

    items += [identity(base/rel) for rel in old.get('code_sha256', {})]
    return items


def launch_timestamp(stage, rec=None):
    rec = rec or verify_repin(stage)
    items = [identity(Path(stage)/'REPIN_FREEZE.json')]
    items += rec['delivery_files'] + [rec['tests']]
    aliases = {'batch_scoring':['CODE_FREEZE.json'],'label_scoring':['CODE_FREEZE.json','CODE_FREEZE_A2X.json'],'matched_controls':['PCX_FREEZE.json']}
    items += [identity(Path(stage)/name) for name in aliases.get(rec['batch'],[])]
    stamp = dt.datetime.fromisoformat(rec['created_utc'])
    return timestamp_binding(Path(rec['adapter_root']).parent, items, LAUNCH_TIMESTAMP_LABELS[rec['batch']], not_before=stamp)


def replace_function(source, name, replacement):

    tree = ast.parse(source)
    node = next(n for n in tree.body if isinstance(n, ast.FunctionDef) and n.name == name)
    lines = source.splitlines(True)
    return ''.join(lines[:node.lineno - 1]) + replacement.rstrip() + '\n' + ''.join(lines[node.end_lineno:])
