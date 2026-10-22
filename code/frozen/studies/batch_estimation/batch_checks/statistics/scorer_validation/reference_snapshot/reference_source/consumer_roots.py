
'Associate scoring input paths with their saved source records.'
from __future__ import annotations
import output_lifecycle
import scorer_metadata
import science_contract
import argparse
import builtins
import ast
import contextlib
import datetime as dt
import functools
import hashlib
import importlib
import importlib.machinery
import importlib.util
import json
import os
from pathlib import Path
import re
import stat
import sysconfig
import sys
import types
import runtime_sources
sys.dont_write_bytecode = True
HERE = Path(__file__).resolve().parent
LIVE = HERE.parents[4]
B_REL = 'studies/batch_estimation/fitting'
D_REL = 'studies/batch_estimation/disk_checks'
O_REL = 'studies/batch_estimation/batch_checks/statistics'
F1_REL = 'studies/batch_estimation/A8BATCHDISKSET1'
F2_REL = 'studies/batch_estimation/A8BATCHDISKSET2'
F3_REL = 'studies/batch_estimation/A8BATCHDISKSET3'
F4_REL = 'studies/batch_estimation/A8BATCHDISKSET4'
F5_REL = 'studies/batch_estimation/matrix_storage'
HOST_LAYERS = ((1, F1_REL, 'T4D'), (2, F2_REL, 'T4E'), (3, F3_REL, 'T4H'), (4, F4_REL, 'T4N'), (5, F5_REL, 'T4Q'))
REMEDY_PAIRS = {'DLY8_mode1': (2, 'T4E', 'dly8/mode1/STOPPED_FOR_REMEDY.json'), 'R8_build': (3, 'T4H', 'state/stages/R8_build.json'), 'CS8_primary_seed_robustness_news': (4, 'T4N', 'state/stages/CS8_primary_seed_robustness_news.json'), 'DLY8_mode2': (5, 'T4Q', 'dly8/mode2/STOPPED_FOR_REMEDY.json')}
ENTRIES = {name: B_REL + '/code/' + name + '.py' for name in ('score_batch', 'scorer_freeze', 'loss_export', 'check_scoring_context', 'check_scoring_bindings', 'check_matched_controls', 'batch_inputs', 'runner', 'batch_export', 'freeze_batch_sources', 'cutoff_snapshot')}
ENTRIES.update(read_comparisons='studies/inference/code/read_comparisons.py', repin_outer='studies/source_bindings/dispatch_scoring.py', t5_listing='studies/source_bindings/t5_listing.py')
ENTRIES['cps8_projection'] = 'studies/inference/code/prescore_metadata.py'
FIT_SHIMS = {'check_scoring_context': 'check_scoring_context.py', 'check_scoring_bindings': 'check_scoring_bindings.py', 'check_matched_controls': 'check_matched_controls.py', 'repin_outer': 'source_bindings/dispatch_scoring.py'}
PRESCORE_ENTRIES = {'batch_inputs', 'batch_export', 'runner', 'scorer_freeze', 'freeze_batch_sources', 'cutoff_snapshot', 't5_listing', 'cps8_projection'}
RUNNER_SUPPORT = {'finish_sealed', 'prediction_parity', 'optional_admission', 'fitting_argv'}
SIDECARS = {'SCORER_BINDINGS.json', 'SCORER_CODE_FREEZE.json', 'T5_BINDING.json', 'PCX_SEAL_ASSOCIATION.json', 'POSTSCORE_CLOCK_ASSOCIATION.json', 'POSTSCORE_REPIN_ASSOCIATION.json'}
POST_OUTPUTS = {'POSTSCORE_HOST_LOG.jsonl', 'POSTSCORE_TURN_STATE.json'}
ACTIVE = None

class Refusal(RuntimeError):
    pass

def require(ok, why):
    if not ok:
        raise Refusal(why)

def _no_symlink_path(path):

    literal = os.fsdecode(os.fspath(path))
    raw = Path(literal)
    require('..' not in raw.parts and literal==str(raw), 'Read path lexical alias refused')
    if not raw.is_absolute():
        raw = Path.cwd() / raw
    cursor = Path(raw.anchor)
    for part in raw.parts[1:]:
        require(not cursor.is_symlink(), 'Read path symlink component: ' + str(cursor))
        cursor = cursor.parent if part == '..' else cursor / part
        require(not cursor.is_symlink(), 'Read path symlink component: ' + str(cursor))
    return Path(os.path.normpath(str(raw)))

def _sha(path):
    h = hashlib.sha256()
    with _no_symlink_path(path).open('rb') as f:
        for block in iter(lambda: f.read(1 << 20), b''):
            h.update(block)
    return h.hexdigest()

def _identity(path):
    p = _no_symlink_path(path)
    return dict(path=str(p), bytes=p.stat().st_size, sha256=_sha(p))

def _read(path):

    def pairs(rows):
        value = {}
        for key, item in rows:
            require(key not in value, 'Duplicate JSON key: ' + key)
            value[key] = item
        return value
    return json.loads(Path(path).read_text(), object_pairs_hook=pairs, parse_constant=lambda x: (_ for _ in ()).throw(Refusal('Nonfinite JSON')))

def _checked(item):
    p = _no_symlink_path(item['path'])
    require(str(p) == item['path'], 'Noncanonical bound file path: ' + str(item['path']))
    require(p.is_absolute() and p.is_file() and (not p.is_symlink()), 'Missing/unsafe bound file: ' + str(p))
    require(re.fullmatch('[0-9a-f]{64}', item['sha256']) is not None, 'Bad identity digest')
    require(_sha(p) == item['sha256'] and ('bytes' not in item or p.stat().st_size == item['bytes']), 'Bound file drift: ' + str(p))
    return p

def _write(path, value):
    p = Path(path)
    p.parent.mkdir(parents=True, exist_ok=True)
    with p.open('x') as f:
        f.write(json.dumps(value, ensure_ascii=False, sort_keys=True, indent=2, allow_nan=False) + '\n')

def _contained(path, root):
    p, r = (_no_symlink_path(path), _no_symlink_path(root))
    require(Path(path).is_absolute() and p.is_relative_to(r), 'Output escaped associated root: ' + str(p))
    require(not any((a.is_symlink() for a in [p, *p.parents] if a.is_relative_to(r))), 'Output symlink: ' + str(p))
    return p

def _frozen_metadata_member(root,timestamp_checks,name):

    require(isinstance(name,str),'Frozen metadata name type')
    raw=Path(timestamp_checks).parent/name
    canonical=Path(os.path.abspath(raw))
    require(canonical.is_relative_to(root),'Frozen metadata escaped study root')
    cursor=Path(raw.anchor)
    for part in raw.parts[1:]:
        require(not cursor.is_symlink(),'Frozen metadata symlink component')
        cursor=cursor.parent if part=='..' else cursor/part
        require(not cursor.is_symlink(),'Frozen metadata symlink component')
    return _no_symlink_path(canonical)

class Association:

    def __init__(self, project=LIVE, *, synthetic=False):
        self.project = _no_symlink_path(project)
        self.synthetic = synthetic
        self.b, self.d, self.out = (self.project / r for r in (B_REL, D_REL, O_REL))
        self.q = self.project / 'studies'
        self.f1, self.f2 = (self.project / F1_REL, self.project / F2_REL)
        self.f3, self.f4, self.f5 = (self.project / r for r in (F3_REL, F4_REL, F5_REL))
        self.sealed = set()
        self._parsed = set()
        self.imported = set()
        self.old_modules = {}
        self._released = False
        self._preparing = False
        self._metadata_only = False
        self._validation_depth = 0
        self._metadata_depth = 0
        self._guard_depth = 0
        self._guard_t5 = False
        self._verified_files = {}
        self._sealed_roots = set()
        self._authority_files = {}
        self._ap_runtime = runtime_sources._RuntimeAuthorities(self, runtime_sources._Core(globals()))
        self._runtime_loading_paths = set()
        self._runtime_roots = {_no_symlink_path(sysconfig.get_path(k)) for k in ('stdlib', 'purelib', 'platlib')}
        self._helper_copy = None
        self._output_scope = None
        self._derived_files = {}
        self._official_files = {}
        self._producer_official = None
        self._live_controls = set()
        self._reader_originals = []
        self._source_loading_depth = 0
        self._producer_entry = None
        self._producer_paths = set()
        self._producer_seal = None
        self._ambiguity_depth = 0
        self.lock = _read(HERE / 'SOURCE_LOCK.json')
        if synthetic:
            require(self.project.is_relative_to(Path('/private/tmp')) and _read(self.project / 'SYNTHETIC_ONLY.json') == {'synthetic_only': True}, 'Synthetic association requires explicit private tmp fixture')
        else:
            require(self.project == LIVE, 'Production project root is fixed')
        self._science_binding = {}
        self._science_policy = {'families': {}}
        self._scorer_contract = {}
        self._official_ready = None
        self._ancestor_sources = _read(HERE / 'NUMERIC_ANCESTOR_PROPOSAL.json')['files']
        self._effective_sources = dict(self.lock['sources'])
        self._native_scope = None
        self._bootstrap_depth = 0
        self._bootstrap_source_ready = False
        self._t5_value = {}

    def sources(self):

        self._effective_sources = dict(self.lock['sources'])
        self._effective_sources.update({k: dict(identity=v) for k, v in self._ancestor_sources.items() if k in self._ancestor_sources})
        for rel, item in self._effective_sources.items():
            p = LIVE / rel
            with self._validation():
                actual = _identity(p)
            require(actual == dict(path=str(p), **item['identity']), 'Source drift; re-review/retest: ' + rel)
            self._authority_files[str(p)] = actual
            if self.project != LIVE:
                replica = self.project / rel
                self._authority_files[str(replica)] = dict(actual, path=str(replica))
        for rel, expected in self.lock['authorities'].items():
            with self._validation():
                actual = _identity(LIVE / rel)
            require(actual == dict(path=str(LIVE / rel), **expected), 'Frozen timestamp_checks drift: ' + rel)
            self._authority_files[str(LIVE / rel)] = actual
            if self.project != LIVE:
                replica = self.project / rel
                self._authority_files[str(replica)] = dict(actual, path=str(replica))
            with self._validation():
                value = _read(LIVE / rel)
            inventory = {}
            for field in ('files', 'code_sha256'):
                if isinstance(value.get(field), dict):
                    inventory.update(value[field])
            if rel == B_REL + '/CODE_FREEZE.json':
                tests = value['test_receipts_provenance']['tests']
                test_path = _no_symlink_path(tests['path'])
                require(test_path == LIVE / B_REL / 'TEST_RESULTS.json' and self.metadata_root(test_path), 'Wrong canonical frozen scorer code-test receipt')
                with self._validation():
                    _checked(tests)
                    test_id = _identity(test_path)
                    test_value = _read(test_path)
                    common_path = LIVE / ENTRIES['batch_inputs']
                    common_bytes = common_path.read_bytes()
                common_id = self._authority_files[str(common_path)]
                require(len(common_bytes) == common_id['bytes'] and hashlib.sha256(common_bytes).hexdigest() == common_id['sha256'], 'Frozen scorer inventory source drift')
                tree = ast.parse(common_bytes)
                declared = [node.value for node in tree.body if isinstance(node, ast.Assign) and any((isinstance(target, ast.Name) and target.id == 'SCORER_ONLY' for target in node.targets))]
                require(len(declared) == 1, 'Ambiguous frozen scorer-only inventory')
                keys = ast.literal_eval(declared[0])
                hashes = test_value['scorer_code_sha256']
                require(isinstance(keys, set) and isinstance(hashes, dict) and (set(hashes) == keys), 'Frozen scorer code-test inventory drift')
                self._authority_files[str(test_path)] = test_id
                if self.project != LIVE:
                    replica = self.project / test_path.relative_to(LIVE)
                    self._authority_files[str(replica)] = dict(test_id, path=str(replica))
                for name, digest in hashes.items():
                    require(name in keys and Path(name).suffix in ('.py', '.sh'), 'Unexpected scorer-only timestamp_checks file')
                    inventory[name] = digest
            for name, item in inventory.items():
                digest = item if isinstance(item, str) else item.get('sha256') if isinstance(item, dict) else None
                if digest is None:continue
                candidate=Path(os.path.abspath((LIVE/rel).parent/name))
                if not self.metadata_root(candidate):continue
                p = _frozen_metadata_member(LIVE,LIVE/rel,name)
                require(p.is_relative_to(LIVE), 'Code timestamp_checks file escaped study root')
                with self._validation():
                    actual = _identity(p)
                require(actual['sha256'] == digest and (not isinstance(item, dict) or 'bytes' not in item or actual['bytes'] == item['bytes']), 'Frozen metadata timestamp_checks drift: ' + str(p))
                self._authority_files[str(p)] = actual
                if self.project != LIVE:
                    replica = self.project / p.relative_to(LIVE)
                    self._authority_files[str(replica)] = dict(actual, path=str(replica))
        with self._validation():
            self._authority_files[str(HERE / 'SOURCE_LOCK.json')] = _identity(HERE / 'SOURCE_LOCK.json')
        return self.lock

    def verify_science_authority(self, item):
        require(self._validation_depth > 0, 'Private scientific timestamp_checks verification scope required')
        require(Path(item['path']) == self.out / 'SCIENCE_FREEZE.json', 'Wrong scientific timestamp_checks')
        _checked(item)
        return _read(item['path'])

    def release(self):
        return science_contract._release(self, runtime_sources._Core(globals()))

    def verify_host_parents(self, binding):

        for n, root, label in ((1, self.f1, 'T4D'), (2, self.f2, 'T4E')):
            fp = root / ('SET' + str(n) + '_FREEZE.json')
            tp = root / (label + '_BINDING.json')
            require(binding['set' + str(n) + '_freeze'] == _identity(fp) and binding[label.lower() + '_binding'] == _identity(tp), 'Wrong SET host parent association')
            frozen = _read(fp)
            stamp = _read(tp)
            require(frozen['state'] == 'FROZEN_DISKSET' + str(n), 'Unfrozen SET host parent')
            for rel, item in frozen['files'].items():
                p = _contained(root / rel, root)
                require(_identity(p) == dict(path=str(p), **item), 'SET host file drift: ' + rel)
            for name, item in frozen['parents'].items():
                p = Path(name)
                require(p.is_absolute() and _identity(p) == dict(path=str(p), **item), 'SET host parent drift: ' + name)
            required = (self.d / 'DISK_FREEZE.json', self.d / 'T4C_BINDING.json') if n == 1 else (self.f1 / 'SET1_FREEZE.json', self.f1 / 'T4D_BINDING.json')
            require(all((str(p) in frozen['parents'] for p in required)), 'Incomplete SET parent chain')
            source = LIVE / (F1_REL if n == 1 else F2_REL) / ('freeze_set' + str(n) + '.py')
            self.verify_code(source)
            tree = ast.parse(source.read_bytes())
            names = ast.literal_eval(next((node.value for node in tree.body if isinstance(node, ast.Assign) and any((isinstance(t, ast.Name) and t.id == 'FILES' for t in node.targets)))))
            require(set(frozen['files']) == set(names) | {p.name for p in root.glob('REVIEW*_source.md')}, 'SET' + str(n) + ' frozen file inventory drift')
            if n == 2:
                require(frozen['parents'] == _read(root / 'PARENT_PINS.json') and frozen['parent_labels'] == ['T4B', 'T4C', 'T4D'] and (frozen['next_binding'] == 'T4E') and (frozen['failure'] == _read(root / 'FAILURE_BINDING.json')['failure']), 'SET2 frozen parent inventory drift')
            require(stamp['label'] == label and stamp['state'] == label + '_VERIFIED' and (stamp['source_verified'] is True) and (stamp['set' + str(n) + '_freeze'] == _identity(fp)), 'Unverified SET timestamp binding')
            parse = lambda s: dt.datetime.fromisoformat(s.replace('Z', '+00:00'))
            require(parse(stamp['utc']).utcoffset() == dt.timedelta(0) and parse(frozen['utc']).utcoffset() == dt.timedelta(0) and (parse(stamp['utc']) > parse(frozen['utc'])), 'SET timestamp chronology')
            for item in [*stamp['files'], *stamp['tsa_receipts']]:
                _checked(item)
            require(_identity(fp) in stamp['files'] and len(stamp['tsa_receipts']) >= 2 and (len({i['path'] for i in stamp['tsa_receipts']}) == len(stamp['tsa_receipts'])), 'SET timestamp exact coverage')
            if not self.synthetic:
                source = LIVE / F2_REL / 't4e_verify.py'
                self.verify_code(source)
                ns = {'__file__': str(source), '__name__': '_consumer_set_timestamp_verifier'}
                exec(compile(source.read_bytes(), str(source), 'exec'), ns)
                ns['verify_timestamp_bundle'](stamp, _identity(fp), self.q / 'confirmation/TIMESTAMPS', label=label)
            require(_identity(fp) == binding['set' + str(n) + '_freeze'] and _identity(tp) == binding[label.lower() + '_binding'], 'SET host release drift during verification')
            self._authority_files.update({str(root / rel): dict(path=str(root / rel), **item) for rel, item in frozen['files'].items()})
            self._authority_files[str(fp)] = binding['set' + str(n) + '_freeze']
            self._authority_files[str(tp)] = binding[label.lower() + '_binding']
        self.verify_later_host_parents(binding)
        return True

    def verify_later_host_parents(self, binding):

        if self.synthetic and (not any(('set' + str(n) + '_freeze' in binding for n in (3, 4, 5)))):
            return True
        previous_stages = ['DLY8_mode1']
        previous_pin = _read(self.f2 / 'FAILURE_BINDING.json')
        previous = {previous_stages[0]: previous_pin}
        for n, rel, label in HOST_LAYERS[2:]:
            root = self.project / rel
            fp = root / ('SET' + str(n) + '_FREEZE.json')
            tp = root / (label + '_BINDING.json')
            freeze_id = _identity(fp)
            stamp_id = _identity(tp)
            require(binding.get('set' + str(n) + '_freeze') == freeze_id and binding.get(label.lower() + '_binding') == stamp_id, 'Wrong SET' + str(n) + ' host parent association')
            frozen = _read(fp)
            stamp = _read(tp)
            require(frozen.get('state') == 'FROZEN_DISKSET' + str(n), 'Unfrozen SET' + str(n) + ' host parent')
            actual_files = {}
            for name, item in frozen['files'].items():
                path = _contained(root / name, root)
                require(not Path(name).is_absolute() and '..' not in Path(name).parts, 'SET timestamp_checks inventory escaped root')
                actual = _identity(path)
                require(actual == dict(path=str(path), **item), 'SET' + str(n) + ' host file drift: ' + name)
                actual_files[str(path)] = actual
            source = root / ('freeze_set' + str(n) + '.py')
            require(str(source) in actual_files, 'Missing verified SET freeze-writer source')
            tree = ast.parse(source.read_bytes())
            declared = ast.literal_eval(next((node.value for node in tree.body if isinstance(node, ast.Assign) and any((isinstance(t, ast.Name) and t.id == 'FILES' for t in node.targets)))))
            names = set(declared) | {p.name for p in root.glob('REVIEW*_source.md')}
            if (root / 'FIRST_RUN_FAILURE.json').exists():
                names.add('FIRST_RUN_FAILURE.json')
            require(len(declared) == len(set(declared)) and set(frozen['files']) == names, 'SET' + str(n) + ' frozen file inventory drift')
            pins = _read(root / 'PARENT_PINS.json')
            require(frozen['parents'] == pins, 'SET' + str(n) + ' exact parent inventory drift')
            for name, item in pins.items():
                path = _no_symlink_path(name)
                require(Path(name).is_absolute() and path.is_relative_to(self.project) and (_identity(path) == dict(path=str(path), **item)), 'SET' + str(n) + ' host parent drift: ' + name)
            prev_n, prev_rel, prev_label = HOST_LAYERS[n - 2]
            prev_root = self.project / prev_rel
            prev_freeze = prev_root / ('SET' + str(prev_n) + '_FREEZE.json')
            prev_stamp = prev_root / (prev_label + '_BINDING.json')
            require(all((str(p) in pins for p in (prev_freeze, prev_stamp))) and frozen['parent_release'] == dict(set_freeze=_identity(prev_freeze), **{prev_label.lower() + '_binding': _identity(prev_stamp)}) and (frozen['parent_labels'] == ['T4B', 'T4C', *[x[2] for x in HOST_LAYERS[:n - 1]]]) and (frozen['next_binding'] == label), 'SET' + str(n) + ' incomplete parent release chain')
            failures = _read(root / 'FAILURE_BINDINGS.json')
            added = list(REMEDY_PAIRS)[n - 2]
            require(set(failures) == set(previous) | {added} and frozen['failures'] == failures and all((failures[k] == v for k, v in previous.items())), 'SET' + str(n) + ' historical failure whitelist drift')
            previous = failures
            require(stamp.get('label') == label and stamp.get('state') == label + '_VERIFIED' and (stamp.get('source_verified') is True) and (stamp.get('set' + str(n) + '_freeze') == freeze_id), 'Unverified SET' + str(n) + ' timestamp binding')
            parse = lambda x: dt.datetime.fromisoformat(x.replace('Z', '+00:00'))
            frozen_utc = parse(frozen['utc'])
            stamp_utc = parse(stamp['utc'])
            require(frozen_utc.utcoffset() == dt.timedelta(0) and stamp_utc.utcoffset() == dt.timedelta(0) and (stamp_utc > frozen_utc), 'SET' + str(n) + ' timestamp chronology')
            for item in [*stamp['files'], *stamp['tsa_receipts']]:
                _checked(item)
            require(freeze_id in stamp['files'] and len(stamp['tsa_receipts']) >= 2 and (len({x['path'] for x in stamp['tsa_receipts']}) == len(stamp['tsa_receipts'])), 'SET' + str(n) + ' timestamp exact coverage')
            if not self.synthetic:
                evidence = self._host_timestamp(stamp, freeze_id, label)
                if n >= 4:
                    wrapper = root / ('host_wrapper_set' + str(n) + '.py')
                    parser = next((node for node in ast.parse(wrapper.read_bytes()).body if isinstance(node, ast.FunctionDef) and node.name == 'verified_gen_time_utc'))
                    ns = {'dt': dt, 're': re}
                    exec(compile(ast.Module(body=[parser], type_ignores=[]), str(wrapper), 'exec'), ns)
                    require(set(evidence['tsa']) == {'freetsa', 'digicert'}, 'Both verified SET TSA genTimes required')
                    require(all((ns['verified_gen_time_utc'](v['time_stamp']) > frozen_utc for v in evidence['tsa'].values())), 'Verified SET TSA genTime must follow freeze')
            require(_identity(tp) == stamp_id and _identity(fp) == freeze_id, 'SET' + str(n) + ' release drift during verification')
            self._authority_files.update(actual_files)
            self._authority_files[str(fp)] = freeze_id
            self._authority_files[str(tp)] = stamp_id
        return True

    def _host_timestamp(self, stamp, freeze_id, label):
        source = LIVE / F2_REL / 't4e_verify.py'
        self.verify_code(source)
        ns = {'__file__': str(source), '__name__': '_consumer_set_timestamp_verifier'}
        exec(compile(source.read_bytes(), str(source), 'exec'), ns)
        return ns['verify_timestamp_bundle'](stamp, freeze_id, self.q / 'confirmation/TIMESTAMPS', label=label)

    def authority_sources(self, value, root):

        count = 0
        for rel, item in value.get('files', {}).items():
            p = root / rel
            if isinstance(item, str):
                require(_sha(p) == item, 'Future timestamp_checks file drift: ' + str(p))
            elif isinstance(item, dict):
                require(_sha(p) == item['sha256'] and ('bytes' not in item or p.stat().st_size == item['bytes']), 'Future timestamp_checks file drift: ' + str(p))
            else:
                raise Refusal('Unknown future timestamp_checks inventory')
            count += p.suffix == '.py'
        require(count > 0, 'Future timestamp_checks lacks a code inventory')
        for rel, digest in value.get('test_receipts', {}).items():
            require(_sha(root / rel) == digest, 'Future consumer test receipt drift: ' + rel)
        for rel, digest in value.get('external_identities', {}).items():
            require(_sha(LIVE / rel) == digest, 'Future consumer dependency drift: ' + rel)

    def ambiguity(self):
        for p in (self.b / 'state', self.b / 'dly8', self.b / 'cps8', *(self.b / n for n in POST_OUTPUTS)):
            if p.is_dir():
                require(not any((x.is_file() or x.is_symlink() for x in p.rglob('*'))), 'Ambiguous SET4 production output: ' + str(p))
            else:
                require(not p.exists() and (not p.is_symlink()), 'Ambiguous SET4 production output: ' + str(p))
        for name in ('state', 'dly8', 'cps8'):
            p = self.q / 'batch_estimation' / name
            require(not p.exists() or (p.is_dir() and (not any((x.is_file() or x.is_symlink() for x in p.rglob('*'))))), 'Ambiguous legacy production output: ' + str(p))

    def _check_ambiguity(self):
        self._ambiguity_depth += 1
        try:
            self.ambiguity()
        finally:
            self._ambiguity_depth -= 1

    def _need_validation(self):
        require(ACTIVE is self and self._validation_depth > 0 and (self._released or (self._bootstrap_depth > 0 and self._bootstrap_source_ready)), 'Verified scientific release or authenticated private bootstrap required')

    def route(self, value):
        p = Path(os.path.normpath(str(value)))
        for b in (LIVE / B_REL, self.b):
            if p.is_relative_to(b):
                rel = p.relative_to(b)
                if rel.parts and rel.parts[0] in ('state', 'dly8', 'cps8'):
                    return self.d / rel
                if str(rel) in SIDECARS:
                    return self.out / rel
                if str(rel) in POST_OUTPUTS:
                    return self.d / 'state/postscore' / rel
        if p.is_relative_to(self.d):
            rel = p.relative_to(self.d)
            if rel.parts and rel.parts[0] in ('code', 'tests') or str(rel) in ('CODE_FREEZE.json', 'T4B_BINDING.json'):
                return LIVE / B_REL / rel
        legacy = self.q / 'batch_estimation'
        if p.is_relative_to(legacy) and p != legacy:
            rel = p.relative_to(legacy)
            if rel.parts[0] in ('state', 'dly8', 'cps8'):
                return self.d / rel
        if self.synthetic and p.is_relative_to(LIVE):
            rel = p.relative_to(LIVE)
            if p.suffix == '.py' or 'code' in rel.parts or 'tests' in rel.parts:
                return p
            return self.project / rel
        return p

    def output_item(self, item, root=None):
        self._need_validation()
        p = _checked(item)
        self._verified_files[str(p)] = _identity(p)
        self._sealed_roots.add(p.parent)
        if root is not None:
            _contained(p, root)
        if p.is_relative_to(self.d):
            _contained(p, self.d)
            self.sealed.add(p)
        return p

    def chain(self, value, *, released=False, external_json=False):

        self._need_validation()
        if isinstance(value, list):
            for row in value:
                self.chain(row, released=released, external_json=external_json)
        elif isinstance(value, dict):
            if {'path', 'sha256'} <= value.keys():
                p = Path(value['path'])
                require(not p.is_relative_to(self.b / 'state') and (not p.is_relative_to(self.b / 'dly8')) and (not p.is_relative_to(self.b / 'cps8')), 'Seal points to SET4 output')
                if not released:
                    self.output_item(value)
                    if (p.is_relative_to(self.d) or external_json) and p.suffix == '.json' and (p not in self._parsed):
                        self._parsed.add(p)
                        self.chain(_read(p), external_json=external_json)
                return
            for key, path in value.items():
                if key.endswith('_path') and isinstance(path, str) and (key[:-5] + '_sha256' in value):
                    p = Path(path)
                    if p.is_relative_to(self.d) or external_json:
                        self.output_item(dict(path=path, sha256=value[key[:-5] + '_sha256']))
                        if external_json and p.suffix == '.json' and (p not in self._parsed):
                            self._parsed.add(p)
                            self.chain(_read(p), external_json=True)
            for key, row in value.items():
                self.chain(row, released=released or key == 'matrices', external_json=external_json)

    def matrix_chain(self, root, row):
        self._need_validation()
        seal_path = root / 'MATRIX_EVIDENCE_SEAL.json'
        seal = _read(seal_path)
        require(seal['state'] == 'REGENERABLE_MATRICES_SEALED' and seal['binding'] == row['binding'] and (seal['family_receipt'] == _identity(root / 'DELAY_RECEIPT.json')), 'Matrix evidence family drift')
        require(row['models_refitted'] == 0 and row['delays_minutes'] == [5, 15, 60], 'DLY8 design metadata drift')
        arms = row['arms']
        require(arms and len(set(arms)) == len(arms), 'DLY8 arms invalid')
        parity_path = self.output_item(row['parity'], root / 'attempts')
        attempt = parity_path.parent
        require(parity_path.name == 'PARITY_DELTA0.json' and attempt.parent == root / 'attempts', 'Successful attempt path')
        parity = _read(parity_path)
        require(parity['state'] == 'PASS' and parity['binding'] == row['binding'] and ([r['arm'] for r in parity['checks']] == arms) and all((r['features_byte_equal'] and r['predictions_byte_equal'] for r in parity['checks'])), 'DLY8 parity evidence')
        require([(r['delta_minutes'], r['arm']) for r in row['predictions']] == [(d, a) for d in (5, 15, 60) for a in arms], 'DLY8 prediction chain incomplete')
        sizes = {}
        for item in row['predictions']:
            p = self.output_item(item, attempt)
            require(p.parent == attempt and p.name == 'notice__' + item['arm'] + '__delay' + str(item['delta_minutes']) + '.parquet', 'DLY8 prediction placement')
            sizes.setdefault(item['arm'], int(item['rows']))
            require(sizes[item['arm']] == int(item['rows']), 'DLY8 row identity drift')
        expected = [attempt / ('delta' + str(d)) / 'MATRIX_RELEASE.json' for d in (0, 5, 15, 60)]
        require(seal['releases'] == [_identity(p) for p in expected], 'Four exact matrix releases required')
        shapes = {}
        for p in expected:
            self.output_item(_identity(p), attempt)
            release = _read(p)
            require(release['state'] == 'COMPLETED_DELTA_RELEASE' and release['binding'] == row['binding'] and ([i['arm'] for i in release['matrices']] == arms), 'Matrix release chain drift')
            for item in release['matrices']:
                matrix = _contained(Path(item['path']), attempt)
                shape = item['shape']
                require(matrix == p.parent / (item['arm'] + '.npy') and item['dtype'] == 'float32' and (len(shape) == 2) and all((type(n) is int and n > 0 for n in shape)) and (shape[0] == sizes[item['arm']]) and (item['bytes'] >= shape[0] * shape[1] * 4) and re.fullmatch('[0-9a-f]{64}', item['sha256']), 'Matrix release shape/identity invalid')
                shapes.setdefault(item['arm'], shape)
                require(shapes[item['arm']] == shape, 'Matrix delta shape drift')
                require(not matrix.exists(), 'Released matrix still present; finish sealed source_delivery first')
        self.sealed.add(seal_path)

    def source_delivery(self):

        self.sealed.clear()
        self._parsed.clear()
        self._verified_files.clear()
        self._sealed_roots.clear()
        self._live_controls.clear()
        self._official_files.clear()
        try:
            self._check_ambiguity()
            with self._validation():
                batch = self._source_delivery_body()
                for p in self.sealed:
                    p = _no_symlink_path(p)
                    self._verified_files[str(p)] = _identity(p)
                    self._sealed_roots.add(p.parent)
                return batch
        except BaseException:
            self.sealed.clear()
            self._parsed.clear()
            self._verified_files.clear()
            self._sealed_roots.clear()
            self._live_controls.clear()
            self._official_files.clear()
            raise

    def _source_delivery_body(self, *, census=True):

        require((self._bootstrap_depth>0 and self._bootstrap_source_ready and self._validation_depth>0) or (self._released and not self._preparing), 'Released consumer or authenticated private bootstrap required')
        require(self.synthetic or ACTIVE is self, 'Production source_delivery requires this installed association')
        batch_path = _contained(self.d / 'state/SEAL_BATCH.json', self.d)
        require(batch_path.is_file(), 'Missing D batch seal')
        metadata = _read(batch_path)
        _contained(metadata['feature_manifest_path'], self.d / 'state')
        for item in metadata['predictions']:
            require(Path(item['path']).is_relative_to(self.d / 'state/sealed') or Path(item['path']).is_relative_to(self.d / 'cps8/sealed'), 'Batch prediction outside D output roots')
            _contained(item['path'], self.d)
        for item in metadata['fit_receipts_and_models']:
            _contained(item['path'], self.d / 'state')
        export = self._load_verified('batch_export')
        batch = export.verify_seal(self.d / 'state')
        self.sealed.add(batch_path)
        self.chain(batch)
        self.chain(_read(_checked(batch['conf_seal'])), external_json=True)
        self.sealed.add(Path(batch['feature_manifest_path']))
        self.chain(_read(batch['feature_manifest_path']))
        for mode, name in ((1, 'PRIMARY'), (2, 'R8')):
            family_seal = self.d / 'dly8' / ('DLY8_SEAL_' + name + '.json')
            family = _read(family_seal)
            root = self.d / 'dly8' / ('mode' + str(mode))
            receipt = root / 'DELAY_RECEIPT.json'
            require(family['state'] in ('DLY8_SEALED_BEFORE_SCORING', 'NOT_RUN_R8_UNAVAILABLE') and family['receipt'] == _identity(receipt) and (family.get('models_refitted', 0) == 0) and (family['conf_seal_sha256'] == batch['conf_seal_sha256']) and (family['adapter_freeze_sha256'] == batch['adapter_freeze_sha256']), 'D family seal invalid')
            row = _read(receipt)
            require(row['models_refitted'] == 0, 'DLY8 cannot refit models')
            expected_source = batch['conf_seal'] if mode == 1 else _identity(batch_path)
            require(row['binding']['main_conf_seal'] == batch['conf_seal'] and row['binding']['source_seal'] == expected_source and (family['source_seal'] == expected_source), 'D family source seal association drift')
            self.chain(row)
            self.sealed.update((family_seal, receipt))
            if row['state'] == 'ALL_DLY8_PREDICTIONS_SEALED':
                self.matrix_chain(root, row)
                attempt = Path(row['parity']['path']).parent
                for p in attempt.rglob('*'):
                    if p.is_file() or p.is_symlink():
                        require(p in self.sealed or 'revisions' in p.parts, 'Unsealed successful DLY8 output: ' + str(p))
            else:
                require(not row['predictions'] and row.get('state', '').startswith(('NOT_RUN', 'PENDING', 'A8DLY_DEV', 'DEVIATION')), 'Unsealed D family output')
        for root in (self.d / 'cps8', self.d / 'state/sealed'):
            if root.exists():
                for p in root.rglob('*'):
                    if p.is_file() or p.is_symlink():
                        require(p in self.sealed or any((s in p.parts for s in ('failed_attempts', 'revisions', 'retained_budget'))), 'Unsealed D output: ' + str(p))
        inputs = self.d / 'state/score_inputs/A8BATCH_INPUTS.json'
        if inputs.exists():
            value = _read(inputs)
            require(value['seal'] == _identity(batch_path) and value['code_freeze'] == batch['code_freeze'] and (value['state'] == 'A8BATCH_SCORE_INPUTS_SEALED_NOT_SCORED'), 'Derived score input seal drift')
            self.chain(value)
            require(value['DLY8'] == [dict(_identity(self.d / 'dly8' / ('mode' + str(m)) / 'DELAY_RECEIPT.json'), mode=m) for m in (1, 2)], 'Derived DLY8 association drift')
            self.sealed.add(inputs)
        if census:
            self.census()
        return batch

    def _evidence_proposal_chain(self):

        self.sealed.clear()
        self._parsed.clear()
        self._verified_files.clear()
        self._sealed_roots.clear()
        self._live_controls.clear()
        self._official_files.clear()
        require(ACTIVE is self, 'Evidence proposal requires the installed producer context')
        require(self._validation_depth > 0, 'Evidence proposal needs its private verification scope')
        try:
            return self._source_delivery_body(census=False)
        except BaseException:
            self.sealed.clear()
            self._parsed.clear()
            self._verified_files.clear()
            self._sealed_roots.clear()
            self._live_controls.clear()
            self._official_files.clear()
            raise

    def census(self):

        self._need_validation()
        extras = set()
        post = self.out / 'POSTSCORE_PRODUCER_RECEIPT.json'
        if post.exists():
            value = _read(post)
            require(value['state'] == 'ASSOCIATED_FROZEN_SCORER_OUTPUTS_COMPLETE' and value['batch_seal'] == _identity(self.d / 'state/SEAL_BATCH.json') and (value['scorer_freeze'] == _identity(self.out / 'SCORER_CODE_FREEZE.json')) and (value['association_freeze'] == _identity(self.out / 'SCIENCE_FREEZE.json')), 'Postscore producer association drift')
            for item in value['files']:
                self.output_item(item, self.d / 'state/scoring')
                self.chain(item)
        for root in (self.d / 'state', self.d / 'dly8', self.d / 'cps8'):
            if root.exists():
                for p in root.rglob('*'):
                    if p.is_file() or p.is_symlink():
                        _contained(p, root)
                        if p not in self.sealed:
                            extras.add(p)
        log = self.d / 'REMEDY_LOG.md'
        if log.exists() and log not in self.sealed:
            extras.add(_contained(log, self.d))
        journals = {self.d / 'state/postscore' / n for n in ('POSTSCORE_HOST_LOG.jsonl', 'POSTSCORE_TURN_STATE.json')}
        journals |= {p for p in extras if p.parent == self.d / 'state/postscore/revisions' and re.fullmatch('POSTSCORE_TURN_STATE\\.json\\.[0-9a-f]{32}', p.name)}
        if extras & journals:
            gate = _read(self.out / 'T5_BINDING.json')
            require(gate['state'] == 'T5_VERIFIED' and gate['source_verified'] is True, 'Postscore journals require verified T5')
            source = LIVE / B_REL / 'code/check_scoring_context.py'
            require(_identity(source) in gate['files'] and _identity(self.out / 'SCORER_CODE_FREEZE.json') in gate['files'], 'Postscore journal producer not frozen in T5')
            for item in [*gate['files'], *gate['tsa_receipts']]:
                _checked(item)
            require(len(gate['tsa_receipts']) >= 2, 'Postscore journals require two T5 TSA identities')
            self._live_controls.update(extras & journals)
            extras -= journals
        required_four = str(self.f5 / 'SET5_FREEZE.json') in self._authority_files
        if not extras and (not required_four):
            return
        path = self.out / 'OUTPUT_EVIDENCE_BINDINGS.json'
        require(path.is_file(), 'Unsealed D outputs; exact supplemental evidence binding required: ' + (str(sorted(extras)[0]) if extras else 'verified SET5 four-remedy history'))
        value = _read(path)
        require(value['schema'] == 'A8DISK_OUTPUT_EVIDENCE_IDENTITIES_V1' and value['source_reviewed'] is True and (value['batch_seal'] == _identity(self.d / 'state/SEAL_BATCH.json')) and (value['scientific_eligibility_changed'] is False), 'Invalid supplemental evidence binding')
        covered = set()
        for row in value['files']:
            item = row['identity']
            if row['role'] == 'OPERATIONAL_LIVE':
                p = _contained(item['path'], self.d / 'state')
                require(p.parent == self.d / 'state' and p.name in ('OPENED_PATHS.jsonl', 'EXPLICIT_READS.jsonl', 'PROCESS_OVERLAP_AUDIT.jsonl', 'FITTING_WALL_LEDGER.json', 'FITTING_WALL_EVENTS.jsonl', '.fitting.lock'), 'Unknown mutable operational file')
                snapshot = _checked(row['snapshot'])
                _contained(snapshot, self.out / 'evidence_snapshots')
                self.sealed.add(snapshot)
                self._live_controls.add(p)
                covered.add(p)
                continue
            p = self.output_item(item, self.d)
            require(row['role'] in ('OPERATIONAL_EVIDENCE', 'RETAINED_EXCLUDED', 'RECEIPT_BOUND_POSTSCORE', 'PRODUCER_SIDECAR_CACHE'), 'Unknown evidence role')
            if row['role'] == 'PRODUCER_SIDECAR_CACHE':
                pair = self.cache_pair(p)
                require(row['sidecar'] == _identity(pair[1]) and row['producer_sources'] == [_identity(LIVE / 'studies/confirmation/execution/embedding_adapter.py'), _identity(LIVE / B_REL / 'code/delay_cache.py')], 'Cache sidecar/producer association drift')
            if row['role'] == 'RETAINED_EXCLUDED':
                require(any((s in p.parts for s in ('failed_attempts', 'revisions', 'retained_budget'))), 'Retained evidence escaped named namespace')
            if row['role'] == 'RECEIPT_BOUND_POSTSCORE':
                require(p.is_relative_to(self.d / 'state/scoring') or p.is_relative_to(self.d / 'state/postscore'), 'Postscore evidence escaped output root')
                timestamp_checks = _read(_checked(row['producer_receipt']))
                self.chain(timestamp_checks)
                require(any((Path(i['path']) == p and i['sha256'] == item['sha256'] for i in timestamp_checks['files'])), 'Postscore output not receipt-bound')
            if row['role'] == 'OPERATIONAL_EVIDENCE':
                require((p.suffix in ('.json', '.jsonl', '.lock', '.log', '.txt') or p == self.d / 'REMEDY_LOG.md') and (not p.is_relative_to(self.d / 'state/scoring')) and (not p.is_relative_to(self.d / 'state/sealed')) and (not p.is_relative_to(self.d / 'cps8/sealed')) and (not p.name.startswith(('SEAL', 'MATRIX', 'notice__', 'news__'))), 'Unsealed scientific output cannot be operational evidence')
            covered.add(p)
        require(extras <= covered, 'Supplemental evidence chain incomplete: ' + str(sorted(extras - covered)))
        if required_four or not self.synthetic or 'operational_history' in value:
            require(value.get('operational_history') == self.operational_history(value['files']), 'Honest SET2 historical/current operational identities incomplete')
        if required_four or not self.synthetic or 'remedy_history' in value:
            require(value.get('remedy_history') == self.remedy_history(value['files']), 'Four honest remedy historical/current identities incomplete')
        self.sealed.add(path)

    def operational_history(self, rows):

        self._need_validation()
        pin = _read(self.f2 / 'FAILURE_BINDING.json')['failure']
        stopped = self.d / 'dly8/mode1/STOPPED_FOR_REMEDY.json'
        require(pin['path'] == str(stopped), 'SET2 historical failure points outside mode1')
        require(len(rows) == len({r['identity']['path'] for r in rows}), 'Duplicate operational evidence identity')
        files = {r['identity']['path']: r for r in rows}
        required = [self.d / 'state/remedies/DLY8_mode1.json', stopped, self.d / 'REMEDY_LOG.md']
        markers = [self.d / 'state' / n / 'DLY8_mode1.json' for n in ('remedies_used', 'remedied_attempts')]
        require(markers[0].exists() == markers[1].exists(), 'Honest SET2 consumption markers incomplete')
        required += [p for p in markers if p.exists()]
        for p in required:
            require(str(p) in files and files[str(p)]['role'] == 'OPERATIONAL_EVIDENCE' and (files[str(p)]['identity'] == _identity(p)), 'Missing exact honest SET2 operational row: ' + str(p))
        current = _identity(stopped)
        preserved = [r['identity'] for r in rows if r['role'] == 'RETAINED_EXCLUDED' and r['identity']['sha256'] == pin['sha256'] and (r['identity']['bytes'] == pin['bytes']) and Path(r['identity']['path']).is_relative_to(self.d / 'dly8/mode1')]
        if current != pin:
            require(preserved, 'Historical STOPPED bytes not retained after replacement')
            for item in preserved:
                _checked(item)
        return dict(original_failure=pin, current_failure=current, retained_original=preserved, remedy_kind='implementation_defect_set', resource_only=False, scientific_eligibility_changed=False)

    def remedy_history(self, rows):

        self._need_validation()
        legacy = self.operational_history(rows)
        require(len(rows) == len({r['identity']['path'] for r in rows}), 'Duplicate remedy evidence identity')
        files = {r['identity']['path']: r for r in rows}

        def frozen_pins(root, n):
            fp = root / ('SET' + str(n) + '_FREEZE.json')
            f = _read(fp)
            require(f.get('state') == 'FROZEN_DISKSET' + str(n), 'Unfrozen remedy host timestamp_checks')
            name = 'FAILURE_BINDING.json' if n == 2 else 'FAILURE_BINDINGS.json'
            path = root / name
            actual = _identity(path)
            require(f.get('files', {}).get(name) == {k: v for k, v in actual.items() if k != 'path'}, 'Remedy failure pins not bound by own host freeze')
            if not self.synthetic:
                require(self._authority_files.get(str(fp)) == _identity(fp) and self._authority_files.get(str(path)) == actual, 'Remedy host parent not released/verified')
            return _read(path)
        pins = frozen_pins(self.f5, 5)
        require(set(pins) == set(REMEDY_PAIRS), 'Exactly four honest remedy pairs required')
        log = self.d / 'REMEDY_LOG.md'
        log_id = _identity(log)

        def row_id(path):
            row = files.get(str(path))
            require(row is not None and row['role'] == 'OPERATIONAL_EVIDENCE' and (row['identity'] == _identity(path)), 'Missing exact honest remedy operational row: ' + str(path))
            return row['identity']
        row_id(log)
        current_log = log.read_bytes()
        result = {}
        for stage, (n, label, rel) in REMEDY_PAIRS.items():
            root = self.project / HOST_LAYERS[n - 1][1]
            pin = pins[stage]
            own = frozen_pins(root, n)
            expected = own if n == 2 else own.get(stage)
            require(expected == pin and pin.get('stage') == stage, 'Historical per-stage failure pin drift: ' + stage)
            stop = self.d / rel
            original = pin['failure']
            current = row_id(stop)
            require(original.get('path') == str(stop), 'Failure identity escaped exact remedy stage: ' + stage)
            retained = []
            for r in rows:
                item = r['identity']
                path = _no_symlink_path(item['path'])
                stage_revision = path.parent == stop.parent / 'revisions' and path.name.startswith(stop.name + '.')
                stage_failed = path.is_relative_to(stop.parent / 'failed_attempts') and path.name == stop.name
                if r['role'] == 'RETAINED_EXCLUDED' and (stage_revision or stage_failed) and all((item.get(k) == original.get(k) for k in ('bytes', 'sha256'))):
                    _checked(item)
                    retained.append(item)
            require(current == original or retained, 'Historical stop bytes missing in exact stage namespace: ' + stage)
            original_path = stop if current == original else Path(retained[0]['path'])
            failed = _read(original_path)
            required = ('stage', 'state', 'detail', 'failure_utc', 'remedy_count', 'maximum_remedies')
            require(all((failed.get(k) == pin.get(k) for k in required)), 'Historical original failure metadata drift: ' + stage)
            if stage == 'DLY8_mode2':
                require(failed == pin.get('record') and failed.get('reconstructed_post_hoc') is not True, 'DLY8 mode2 must retain its exact native stop, never reconstructed')
            remedy = self.d / 'state/remedies' / (stage + '.json')
            remedy_id = row_id(remedy)
            value = _read(remedy)
            key = label.lower() + '_binding'
            fp = root / ('SET' + str(n) + '_FREEZE.json')
            tp = root / (label + '_BINDING.json')
            freeze_id = _identity(fp)
            stamp_id = _identity(tp)
            stamp = _read(tp)
            require(stamp.get('label') == label and stamp.get('state') == label + '_VERIFIED' and (stamp.get('source_verified') is True) and (stamp.get('set' + str(n) + '_freeze') == freeze_id), 'Remedy own host timestamp binding invalid: ' + stage)
            require(value.get('stage') == stage and value.get('failure') == original and (value.get('resource_only') is False) and (value.get('remedy_kind') == 'implementation_defect_set') and (type(value.get('remedy_count')) is int) and (value['remedy_count'] == 1) and isinstance(value.get('description'), str) and value['description'].strip() and (value.get('set_freeze') == freeze_id) and (value.get(key) == stamp_id) and ({k for k in value if re.fullmatch('t4[a-z]+_binding', k)} == {key}), 'Remedy stage/failure/freeze/timestamp pair mismatch: ' + stage)
            history = value.get('original_failure_record')
            require(isinstance(history, dict) and all((history.get(k) == pin.get(k) for k in required)), 'Remedy historical failure record incomplete: ' + stage)
            if stage == 'DLY8_mode2':
                require(history == pin['record'], 'Remedy native mode2 record changed')
            if stage == 'CS8_primary_seed_robustness_news':
                require(value.get('reconstruction_evidence') == pin.get('reconstruction_evidence') and pin.get('reconstruction_evidence') is not None, 'CS8 reconstructed provenance missing')
            parse = lambda x: dt.datetime.fromisoformat(x.replace('Z', '+00:00'))
            utc = parse(value['utc'])
            old_utc = parse(pin['failure_utc'])
            require(utc.utcoffset() == dt.timedelta(0) and old_utc.utcoffset() == dt.timedelta(0) and (utc > old_utc), 'Honest remedy chronology invalid: ' + stage)
            historical_log = value.get('remedy_log', {})
            require(historical_log.get('path') == str(log) and type(historical_log.get('bytes')) is int and (0 < historical_log['bytes'] <= len(current_log)) and (hashlib.sha256(current_log[:historical_log['bytes']]).hexdigest() == historical_log.get('sha256')), 'Historical consumed remedy log prefix drift: ' + stage)
            marker_paths = {kind: self.d / 'state' / directory / (stage + '.json') for kind, directory in (('used', 'remedies_used'), ('started', 'remedied_attempts'))}
            require(marker_paths['used'].exists() == marker_paths['started'].exists(), 'Honest remedy marker pair incomplete: ' + stage)
            markers = {kind: None for kind in marker_paths}
            for kind, path in marker_paths.items():
                if not path.exists():
                    continue
                markers[kind] = row_id(path)
                marker = _read(path)
                require(marker.get('stage') == stage and marker.get('remedy') == remedy_id and (marker.get('failure') == original) and (marker.get('resource_only') is False) and (marker.get('remedy_kind') == 'implementation_defect_set') and (marker.get('set_freeze') == freeze_id) and (marker.get(key) == stamp_id) and ({k for k in marker if re.fullmatch('t4[a-z]+_binding', k)} == {key}), 'Honest remedy marker stage/failure/freeze/timestamp mismatch: ' + stage)
                if kind == 'used':
                    require(marker.get('record') == value and marker.get('remedy_log') == historical_log and (type(marker.get('remedy_count')) is int) and (marker['remedy_count'] == 1) and isinstance(marker.get('clause'), str) and marker['clause'].strip(), 'Honest consumed remedy marker record incomplete: ' + stage)
            result[stage] = dict(original_failure=original, current_failure=current, retained_original=retained, remedy=remedy_id, markers=markers, set_freeze=freeze_id, timestamp_binding=stamp_id, remedy_log=historical_log, native_original_failure=stage != 'CS8_primary_seed_robustness_news', reconstruction_evidence=pin.get('reconstruction_evidence'))
        require(_identity(log) == log_id, 'Remedy log changed during verification')
        return dict(set2_history=legacy, remedies=result)

    def cache_pair(self, path):

        self._need_validation()
        root = self.d / 'dly8/embedding_cache'
        p = _contained(path, root)
        rel = p.relative_to(root)
        require(p.suffix in ('.json', '.npy') and re.fullmatch('[0-9a-f]{64}', p.stem) and (len(rel.parts) == 2 and rel.parts[0] == 'corpora' or (len(rel.parts) == 3 and rel.parts[0] == 'chunks')), 'Unknown derived cache path')
        vector, sidecar = (p.with_suffix('.npy'), p.with_suffix('.json'))
        require(vector.is_file() and sidecar.is_file(), 'Incomplete derived cache sidecar pair')
        _contained(vector, root)
        _contained(sidecar, root)
        value = _read(sidecar)
        require(value['vector_sha256'] == _sha(vector), 'Derived cache sidecar SHA drift')
        if rel.parts[0] == 'corpora':
            signature = value['signature']
            require(hashlib.sha256(json.dumps(signature, sort_keys=True, separators=(',', ':')).encode()).hexdigest() == p.stem, 'Corpus sidecar signature/key drift')
        else:
            require(value['revision'] == rel.parts[1] and value['token_ids_sha256'] == p.stem, 'Chunk sidecar revision/key drift')
        return (vector, sidecar)

    def verify_t5_coverage(self):
        require(ACTIVE is self, 'T5 coverage requires this installed association')
        with self._validation():
            return self._verify_t5_coverage_body()

    def _verify_t5_coverage_body(self):
        require(self.synthetic or self._released, 'Production release required before T5 coverage')
        self.source_delivery()
        value = _read(self.out / 'T5_BINDING.json')
        require(value['state'] == 'T5_VERIFIED' and value['source_verified'] is True, 'Verified T5 required')
        for item in [*value['files'], *value['tsa_receipts']]:
            _checked(item)
        require(len(value['tsa_receipts']) >= 2, 'Two verified T5 identities required')
        commitment = self.t5_commitments()
        indexed = {i['path']: i for i in commitment['files']}
        required_payloads = self.prescore_paths()
        require(set(indexed) == {str(p) for p in required_payloads} and all((indexed.get(str(p)) == _identity(p) for p in required_payloads)), 'T5 transitive commitment lacks/drifts exact original payload or metadata identity')
        required = [self.out / 'T5_IDENTITY_COMMITMENTS.json', self.out / 'T5_COMMITMENT_SOURCE_RECEIPT.json']
        required += [p for p in required_payloads if self.metadata_root(p)]
        required += [self.out / 'SCIENCE_FREEZE.json', self.out / 'SCORER_CODE_FREEZE.json', self.d / 'DISK_FREEZE.json', self.d / 'T4C_BINDING.json', self.d / 'T4C_ROOTS.json']
        required += self.host_metadata()
        required += self.science_t5_metadata()
        required += [self.out / rel for rel in _read(self.out / 'SCIENCE_FREEZE.json')['files']]
        sf = _read(self.out / 'SCORER_CODE_FREEZE.json')
        required += [_checked(i) for i in [sf['batch_code_freeze'], sf['numerical_inputs'], sf['scorer_bindings'], *sf['files']]]
        for p in (self.out / 'CPS8_METADATA.json', self.out / 'CPS8_METADATA.receipt.json'):
            if p.exists():
                required.append(p)
        if (self.out / 'CPS8_METADATA.receipt.json').exists():
            projection = _read(self.out / 'CPS8_METADATA.receipt.json')
            required += [_checked(projection[k]) for k in ('source', 'adapter')]
        if (self.out / 'OUTPUT_EVIDENCE_BINDINGS.json').exists():
            for row in _read(self.out / 'OUTPUT_EVIDENCE_BINDINGS.json')['files']:
                if row['role'] == 'PRODUCER_SIDECAR_CACHE':
                    required += [_checked(i) for i in row['producer_sources']]
                if row['role'] == 'RECEIPT_BOUND_POSTSCORE':
                    p = Path(row['producer_receipt']['path'])
                    if p in required:
                        required.remove(p)
        require(all((_identity(p) in value['files'] for p in required)), 'T5 lacks exact associated D evidence')
        for p in [*required, self.out / 'T5_BINDING.json']:
            p = _no_symlink_path(p)
            if self.metadata_root(p):
                self._authority_files[str(p)] = _identity(p)

    def science_t5_metadata(self):
        require(self._released, 'Scientific release required')
        paths = []
        for item in self._science_binding['t5_metadata']:
            p = _checked(item)
            require(self.metadata_root(p), 'Scientific T5 member is not metadata')
            paths.append(p)
        return paths

    def prescore_paths(self):
        return {p for p in self.sealed if not p.is_relative_to(self.d / 'state/scoring') and (not p.is_relative_to(self.d / 'state/postscore'))}

    def metadata_root(self, path):

        if Path(path).is_relative_to(self.project / 'tables'):
            return False
        p = Path(path)
        forbidden = {'private', '.aws', '.llm_client', '.git', '__pycache__', 'a1_paper_not_frozen', 'host_state', 'scoring', 'scored', 'scores', 'score', 'predictions', 'prediction', 'models', 'model', 'sealed', 'evaluation', 'run', 'run_null_ext'}
        parts = p.relative_to(self.project).parts if p.is_relative_to(self.project) else p.parts
        if 'TIMESTAMPS' in parts or any((s.lower() in forbidden for s in parts)):
            return False
        if p.name.startswith(('.env', 'OPENED_PATHS')) or p.name in ('auth.json', '.DS_Store'):
            return False
        if re.search('(^|_)(model|models)(_|\\.|$)', p.name, re.I) and p.suffix not in ('.py', '.md'):
            return False
        if p.is_relative_to(self.d):
            rel = str(p.relative_to(self.d))
            fixed = {'DISK_FREEZE.json', 'T4C_BINDING.json', 'T4C_ROOTS.json', 'state/SEAL_BATCH.json', 'state/B0_REPRODUCTION.json', 'state/R8_ADMISSION.json', 'dly8/DELAY_FORECAST_SEAL.json', 'dly8/DLY8_SEAL_R8.json', 'REMEDY_LOG.md', 'cps8/CPS8_SELECTION.json', 'cps8/CPS8_RECEIPT.json', 'cps8/CPS8_NOT_RUN.json'}
            if rel in fixed:
                return True
            return p.is_relative_to(self.d / 'dly8') and p.name in ('MATRIX_EVIDENCE_SEAL.json', 'MATRIX_RELEASE.json', 'DELAY_RECEIPT.json')
        if re.search('(^|_)(SEAL|SCORE_RECEIPT|A8_POSTSCORE|INPUTS_V2)(_|\\.|$)', p.name) or re.search('(^|_)predictions?(_|\\.|$)', p.name, re.I) or (p.suffix in ('.json', '.csv', '.jsonl') and re.search('(^|_)(SCORE|SCORES|SCORE_RECEIPT)(_|\\.|$)', p.name, re.I)):
            return False
        return p.suffix in ('.json', '.jsonl', '.md', '.py', '.sh', '.txt', '.csv', '.sha256', '.tsr', '.tsq', '.pem', '.crt')

    def host_metadata(self):
        paths = []
        for n, rel, label in HOST_LAYERS:
            root = self.project / rel
            if self.synthetic and n >= 3 and (not (root / ('SET' + str(n) + '_FREEZE.json')).exists()):
                continue
            freeze = root / ('SET' + str(n) + '_FREEZE.json')
            binding = root / (label + '_BINDING.json')
            paths += [freeze, binding]
            paths += [root / rel for rel in _read(freeze)['files']]
            t = _read(binding)
            paths += [Path(i['path']) for i in [*t['files'], *t['tsa_receipts']]]
        return sorted({p for p in paths if self.metadata_root(p)})

    def t5_commitments(self):
        require(self.synthetic or self._released, 'Production release required before T5 metadata access')
        with self._metadata_access():
            return self._t5_commitments_body()

    def _t5_commitments_body(self):
        value = _read(self.out / 'T5_IDENTITY_COMMITMENTS.json')
        require(value['schema'] == 'A8DISK_T5_IDENTITY_COMMITMENTS_V1' and value['source_reviewed'] is True and (value['scientific_eligibility_changed'] is False) and (value['batch_seal'] == _identity(self.d / 'state/SEAL_BATCH.json')), 'Reviewed exact T5 identity commitments required')
        require(len(value['files']) == len({i['path'] for i in value['files']}), 'Duplicate T5 identity commitment')
        for item in value['files']:
            p = Path(item['path'])
            require(p.is_absolute() and p.resolve() == p and p.is_relative_to(self.project) and (type(item.get('bytes')) is int) and (item['bytes'] >= 0) and re.fullmatch('[0-9a-f]{64}', item['sha256']), 'Unsafe T5 identity commitment')
            require(any((p.is_relative_to(self.d / r) for r in ('state', 'dly8', 'cps8'))) or p == self.d / 'REMEDY_LOG.md' or p == self.out / 'OUTPUT_EVIDENCE_BINDINGS.json' or p.is_relative_to(self.out / 'evidence_snapshots'), 'Unauthorized extra T5 commitment path')
        receipt_path = self.out / 'T5_COMMITMENT_SOURCE_RECEIPT.json'
        require(value['closure_receipt'] == _identity(receipt_path), 'T5 closure receipt identity drift')
        source = _read(receipt_path)
        require(source['schema'] == 'A8DISK_T5_COMMITMENT_SOURCE_V1' and source['batch_seal'] == value['batch_seal'] and (source['association_source'] == _identity(HERE / 'consumer_roots.py')) and (source['files'] == value['files']), 'T5 commitment differs from verified original closure')
        return value

    def propose_t5_commitments(self):
        with self._validation():
            self.source_delivery()
            source = dict(schema='A8DISK_T5_COMMITMENT_SOURCE_V1', association_source=_identity(HERE / 'consumer_roots.py'), batch_seal=_identity(self.d / 'state/SEAL_BATCH.json'), files=[_identity(p) for p in sorted(self.prescore_paths())])
            receipt = self.out / 'T5_COMMITMENT_SOURCE_RECEIPT.json'
            _write(receipt, source)
            value = dict(schema='A8DISK_T5_IDENTITY_COMMITMENTS_V1', source_reviewed=False, scientific_eligibility_changed=False, batch_seal=source['batch_seal'], files=source['files'], closure_receipt=_identity(receipt), scope='same original pre-score exact identities; metadata timestamp roots, runtime byte verification')
            _write(self.out / 'T5_IDENTITY_COMMITMENTS.afterseal.template.json', value)
            return value

    def publish_score_receipt(self):
        require(self._released and (not self.synthetic), 'Only completed production scorer may publish this receipt')
        require(self._producer_entry == 'score_batch', 'Only the verified frozen scorer invocation publishes outputs')
        with self._validation():
            return self._publish_score_receipt_body()

    def _publish_score_receipt_body(self):
        require(self._producer_official is not None, 'Official score completion timestamp_checks missing')
        self._check_official_score(self._producer_official)
        root = self.d / 'state/scoring'
        require((root / 'A8BATCH_POSTSCORE_INPUTS.json').is_file(), 'Scorer did not complete')
        paths = sorted((p for p in root.rglob('*') if p.is_file()))
        for p in paths:
            _contained(p, root)
        _write(self.out / 'POSTSCORE_PRODUCER_RECEIPT.json', dict(state='ASSOCIATED_FROZEN_SCORER_OUTPUTS_COMPLETE', batch_seal=_identity(self.d / 'state/SEAL_BATCH.json'), scorer_freeze=_identity(self.out / 'SCORER_CODE_FREEZE.json'), association_freeze=_identity(self.out / 'SCIENCE_FREEZE.json'), files=[_identity(p) for p in paths], scope='opaque identities only; scientific outputs written solely by unchanged frozen scorer'))

    def load(self, entry):

        entry = self._canonical_entry(entry)
        self._public_gate(entry)
        with self._source_loading():
            return _ConsumerModule(self, self._load_verified(entry), entry)

    def _load_verified(self, entry):

        require(self._validation_depth or self._source_loading_depth or self._preparing, 'Internal loader requires a verification or source-loading scope')
        entry = self._canonical_entry(entry)
        require(self.synthetic or self._released or self._preparing, 'Verify release before importing production consumers')
        require(self.synthetic or ACTIVE is self, 'Production consumer import requires this installed association')
        rel = ENTRIES.get(entry, entry)
        p = LIVE / rel
        self.verify_code(p)
        name = p.stem
        if name in sys.modules and Path(getattr(sys.modules[name], '__file__', '/')).resolve() == p.resolve():
            return sys.modules[name]
        spec = importlib.util.spec_from_file_location(name, p)
        module = importlib.util.module_from_spec(spec)
        sys.modules[name] = module
        spec.loader.exec_module(module)
        self.patch(module)
        return module

    @contextlib.contextmanager
    def _consumer_execution(self, entry, *, producer=False):

        t5 = self._public_gate(entry, 'score' if producer else None)
        require(not producer or (entry == 'score_batch' and self._producer_entry is None), 'Invalid frozen producer scope')
        previous = self._guard_t5
        self._guard_t5 = previous or t5
        self._guard_depth += 1
        try:
            if producer:
                if self._producer_official is None:
                    require(self._official_ready is not None, 'Both official views required')
                    self._check_official_score(self._official_ready)
                    self._producer_official = self._official_ready
                self._check_official_score(self._producer_official)
                self._official_files.update(self._producer_official['files'])
                self._sealed_roots.update((Path(n).parent for n in self._producer_official['files']))
                self._producer_entry = entry
                self._producer_paths.clear()
                with self._validation():
                    self._producer_seal = dict(state='FROZEN_SCORER_INFLIGHT_IDENTITIES', batch_seal=_identity(self.d / 'state/SEAL_BATCH.json'), scorer_freeze=_identity(self.out / 'SCORER_CODE_FREEZE.json'), producer=_identity(LIVE / ENTRIES[entry]), files={})
            yield
            if producer and (not self.synthetic):
                self.publish_score_receipt()
        finally:
            if producer:
                self._producer_entry = None
                self._producer_paths.clear()
                self._producer_seal = None
                self._producer_official = None
            self._guard_depth -= 1
            self._guard_t5 = previous

    def _canonical_entry(self, entry):
        if entry in ENTRIES:
            return entry
        p = _no_symlink_path(LIVE / str(entry))
        return next((key for key, rel in ENTRIES.items() if (LIVE / rel).resolve() == p), entry)

    @contextlib.contextmanager
    def _source_loading(self):
        self._source_loading_depth += 1
        try:
            yield
        finally:
            self._source_loading_depth -= 1

    @contextlib.contextmanager
    def _validation(self):
        self._validation_depth += 1
        try:
            yield
        finally:
            self._validation_depth -= 1

    @contextlib.contextmanager
    def _metadata_access(self):
        self._metadata_depth += 1
        try:
            yield
        finally:
            self._metadata_depth -= 1

    def _public_gate(self, entry, function=None):
        require(self._released and self._science_binding.get('integration_complete') is True, 'Scientific integration pending; no legacy fallback')
        require(self.synthetic or self._released or self._preparing, 'Verify release before importing production consumers')
        require(ACTIVE is self, 'Production consumer import requires this installed association')
        require(not self._metadata_only, 'Metadata-only context cannot import a consumer')
        if self._preparing:
            require(entry in ('scorer_freeze', 'batch_inputs'), 'Freeze preparation only loads code authorities')
            return False
        if entry == 'runner' and function is not None:
            require(function in RUNNER_SUPPORT, 'Runner API only exposes export and path support functions')
        t5 = entry not in PRESCORE_ENTRIES or (entry == 'batch_export' and function == 'export_scored')
        if t5:
            self.verify_t5_coverage()
            require(self._official_ready is not None, 'Both verified official score views required before public post-score consumption')
            self._check_official_score(self._official_ready)
        else:
            self.source_delivery()
        return t5

    def _call_public(self, entry, fn, args, kwargs):
        if entry == 'score_batch' and fn.__name__ == 'score':
            self._public_gate(entry, fn.__name__)
            item = args[3] if len(args) > 3 else kwargs['main_score_receipt']
            require(self._official_ready is not None, 'Both official views required')
            self._check_official_score(self._official_ready)
            require(item == self._official_ready['view_inputs']['original']['score_receipt'], 'Frozen batch scorer original receipt mismatch')
            self._producer_official = self._official_ready
            try:
                with self._consumer_execution(entry, producer=True):
                    return fn(*args, **kwargs)
            finally:
                self._producer_official = None
        t5 = self._public_gate(entry, fn.__name__)
        previous = self._guard_t5
        self._guard_t5 = previous or t5
        self._guard_depth += 1
        old_copy = self._helper_copy
        try:
            if entry == 'read_comparisons' and fn.__name__ == 'write_output':
                evidence = args[2] if len(args) > 2 else kwargs['evidence']
                self._ready_inputs(evidence.get('inputs', {}))
            name = fn.__name__
            readers = {'sha', 'sha256', 'identity', 'read', 'read_json', 'strict_json', 'checked'}
            if name in readers:
                value = args[0] if args else kwargs.get('item' if name == 'checked' else 'path')
                if name == 'checked' and isinstance(value, dict):
                    value = value.get('path')
                if value is not None:
                    self._authorize_read(self.route(_no_symlink_path(value)))
            if name == 'atomic_copy':
                source = args[0] if args else kwargs['source']
                destination = args[1] if len(args) > 1 else kwargs['destination']
                source = self.route(_no_symlink_path(source))
                destination = self.route(_no_symlink_path(destination))
                self._authorize_read(source)
                old = None
                if destination.exists():
                    self._authorize_read(destination)
                    old = self._verified_files.get(str(destination)) or self._authority_files.get(str(destination))
                self._helper_copy = dict(destination=destination, source=self._read_identity(source), old=old, files={}, producer=_identity(LIVE / ENTRIES[entry]))
            result = fn(*args, **kwargs)
            if t5:
                self._check_official_score(self._official_ready)
            return result
        finally:
            self._helper_copy = old_copy
            self._guard_depth -= 1
            self._guard_t5 = previous

    def _read_identity(self, p):
        derived = self._derived_files.get(str(p))
        return self._verified_files.get(str(p)) or self._authority_files.get(str(p)) or self._official_files.get(str(p)) or (derived['identity'] if derived else None)

    def _official_score(self, items):
        return science_contract._views(self, runtime_sources._Core(globals()), items)

    def _check_official_score(self, certificate):
        try:
            require(self._official_ready is not None and certificate == self._official_ready, 'No current verified official completion certificate')
            return science_contract._recheck(self, runtime_sources._Core(globals()), certificate)
        except BaseException:
            self._official_ready = None
            self._official_files.clear()
            self._ap_runtime.revoke()
            raise

    def _run_journal_producer(self, entry, fn, args, kwargs):

        self._public_gate(entry, fn.__name__)
        require(self._output_scope is None, 'Nested journal producer scope refused')
        log = self.route(_no_symlink_path(args[3] if len(args) > 3 else kwargs['log_path']))
        require(log.name == 'POSTSCORE_HOST_LOG.jsonl', 'Unexpected host journal name')
        paths = {log, log.parent / 'POSTSCORE_TURN_STATE.json'}
        if self.synthetic:
            require(log.is_relative_to(self.project.parent), 'Synthetic journals escaped owned scratch')
        else:
            require(log == self.d / 'state/postscore/POSTSCORE_HOST_LOG.jsonl', 'Unreviewed host journal destination')
        with self._validation():
            parent = _identity(self.d / 'state/SEAL_BATCH.json')
        code = _identity(LIVE / ENTRIES[entry])
        self._output_scope = dict(paths=paths, written=set(), files={}, journal=True, parent=parent, producer=code)
        try:
            result = fn(*args, **kwargs)
            with self._validation():
                require(_identity(self.d / 'state/SEAL_BATCH.json') == parent and _identity(LIVE / ENTRIES[entry]) == code, 'Journal producer parent identity drift')
            return result
        finally:
            self._output_scope = None

    def _run_output_producer(self, entry, fn, args, kwargs):

        self._public_gate(entry, fn.__name__)
        require(self._output_scope is None, 'Nested output producer scope refused')
        with self._validation():
            parent = _identity(self.d / 'state/SEAL_BATCH.json')
        code = _identity(LIVE / ENTRIES[entry])
        if entry == 'cps8_projection':
            source = dict(args[0] if args else kwargs['source'])
            p = _no_symlink_path(source['path'])
            require(p == self.d / 'cps8/CPS8_SELECTION.json', 'Projection source outside specified CPS8 root')
            self._authorize_read(p)
            require(all((self._read_identity(p).get(k) == v for k, v in source.items())), 'Projection source identity drift')
            destination = _no_symlink_path(args[1] if len(args) > 1 else kwargs['destination'])
            receipt = destination.with_suffix('.receipt.json')
            paths = {destination, receipt}
            if not self.synthetic:
                require(destination == self.out / 'CPS8_METADATA.json', 'Unreviewed projection destination')
        else:
            evidence = args[2] if len(args) > 2 else kwargs['evidence']
            official = self._ready_inputs(evidence.get('inputs', {}))
            record = args[1] if len(args) > 1 else kwargs['record']
            claimed = record.get('identities', {}).get('source_receipt_sha256')
            require(claimed is None or claimed == evidence['inputs']['score_receipt']['sha256'], 'Postscore record/official receipt identity drift')
            source = None
            destination = _no_symlink_path(args[0] if args else kwargs['out'])
            paths = {destination / name for name in ('A8_POSTSCORE.json', 'A8_POSTSCORE_EVIDENCE.json', 'A8_POSTSCORE_RECEIPT.json')}
            receipt = destination / 'A8_POSTSCORE_RECEIPT.json'
            if not self.synthetic:
                require(destination.is_relative_to(self.q / 'inference') or destination.is_relative_to(self.d / 'state/postscore'), 'Unreviewed postscore output root')
        if self.synthetic:
            require(all((p.is_relative_to(self.project.parent) for p in paths)), 'Synthetic producer escaped owned scratch')
        self._output_scope = dict(paths=paths, written=set(), files={}, parent=parent, producer=code, official=official if entry == 'read_comparisons' else None)
        try:
            result = fn(*args, **kwargs)
            scope = self._output_scope
            require(scope['written'] == paths, 'Original producer did not write the exact receipt closure')
            with self._validation():
                if scope['official']:
                    self._check_official_score(scope['official'])
                rows = {str(p): _identity(p) for p in paths}
                binding = _read(receipt)
                require(_identity(self.d / 'state/SEAL_BATCH.json') == parent and _identity(LIVE / ENTRIES[entry]) == code, 'Output producer parent identity drift')
                if entry == 'cps8_projection':
                    require(binding['schema'] == 'A8POST_CPS8_METADATA_PROJECTION_V1' and binding['outcome_access'] is False and (binding['source'] == source) and (binding['output'] == {k: v for k, v in rows[str(destination)].items() if k != 'bytes'}) and (binding['adapter'] == {k: v for k, v in code.items() if k != 'bytes'}), 'Original projection receipt closure drift')
                    require(all((_identity(p).get(k) == v for k, v in source.items())), 'Projection sealed source changed')
                else:
                    expected = [{k: v for k, v in rows[str(destination / name)].items() if k != 'bytes'} for name in ('A8_POSTSCORE.json', 'A8_POSTSCORE_EVIDENCE.json')]
                    require(binding['state'] == 'A8_POSTSCORE_COMPLETE' and binding['outputs'] == expected, 'Original postscore receipt closure drift')
            for p in paths:
                self._derived_files[str(p)] = dict(identity=rows[str(p)], receipt=rows[str(receipt)], parent=parent, producer=code, source=source, official=scope['official'])
            return result
        finally:
            self._output_scope = None

    def _authorize_read(self, path):
        if not self._validation_depth:
            if self._ap_runtime.family(path) is not None and (self._native_scope is None or str(path) in self._authority_files):
                self._ap_runtime.member(path)
                return
            self._ap_runtime.revalidate()
        p = _no_symlink_path(path)
        require(ACTIVE is self, 'Consumer payload read requires this installed association')
        if self._bootstrap_depth:
            require(self._bootstrap_source_ready and self._validation_depth > 0, 'Bootstrap is private metadata-only verification')
            return
        if self._preparing:
            require(not any((p.is_relative_to(self.d / r) for r in ('state', 'dly8', 'cps8'))) and 'host_state' not in p.parts, 'Freeze preparation cannot access production outputs: ' + str(p))
            if self._validation_depth:
                return
            if p in self._runtime_loading_paths:
                return
            item = self._authority_files.get(str(p))
            require(item is not None, 'Freeze preparation requires exact checked timestamp_checks identity: ' + str(p))
            with self._validation():
                require(_identity(p) == item, 'Preparation timestamp_checks identity drift: ' + str(p))
            return
        require(not any((p.is_relative_to(b / r) for b in (LIVE / B_REL, self.b, self.q / 'batch_estimation') for r in ('state', 'dly8', 'cps8'))), 'No silent SET4 fallback: ' + str(p))
        if self._validation_depth:
            return
        if self._native_scope is not None:
            output_lifecycle._read(self, p)
            return
        if p in self._runtime_loading_paths:
            return
        if self._metadata_depth or self._metadata_only:
            require(self.metadata_root(p), 'Metadata-only access refused payload: ' + str(p))
            if self._metadata_depth:
                return
            item = self._read_identity(p)
            require(item is not None, 'Metadata-only helper lacks a verified identity: ' + str(p))
            with self._validation():
                require(_identity(p) == item, 'Metadata-only identity drift: ' + str(p))
            return
        if self._output_scope and p in self._output_scope['written']:
            with self._validation():
                actual = _identity(p)
                require(_identity(self.d / 'state/SEAL_BATCH.json') == self._output_scope['parent'] and _identity(self._output_scope['producer']['path']) == self._output_scope['producer'], 'Original producer self-check parent drift')
            previous = self._output_scope['files'].setdefault(str(p), actual)
            require(actual == previous, 'Original producer self-check identity drift: ' + str(p))
            return
        if self._helper_copy and str(p) in self._helper_copy['files']:
            item = self._helper_copy['files'][str(p)]
            with self._validation():
                actual = _identity(p)
            require(actual['bytes'] == item['bytes'] and actual['sha256'] == item['sha256'], 'Frozen copy output differs from sealed input identity: ' + str(p))
            return
        if self._producer_entry == 'score_batch' and p in self._producer_paths:
            _contained(p, self.d / 'state/scoring')
            with self._validation():
                rows = self._producer_seal['files']
                if str(p) not in rows:
                    rows[str(p)] = _identity(p)
                require(_identity(p) == rows[str(p)], 'In-flight frozen producer output drift: ' + str(p))
            return
        if self._source_loading_depth:
            item = self._authority_files.get(str(p))
            require(item is not None, 'Unpinned source/timestamp_checks read: ' + str(p))
            with self._validation():
                require(_identity(p) == item, 'Source/timestamp_checks read drift: ' + str(p))
            return
        if str(p) not in self._authority_files:
            require(self._official_ready is not None, 'No consumer payload read before verified original/capture/R2 completion')
        if not self._guard_depth:
            self.verify_t5_coverage()
        if str(p) not in self._authority_files:


            self._check_official_score(self._official_ready)
            self._official_files.update(self._official_ready['files'])
            self._sealed_roots.update(Path(self._official_ready['view_inputs'][view]['score_receipt']['path']).parent for view in ('original','r2'))
        if self._read_identity(p) is None:
            if self._guard_t5:
                self.verify_t5_coverage()
            else:
                self.source_delivery()
        derived = self._derived_files.get(str(p))
        if derived:
            with self._validation():
                if derived.get('official'):
                    self._check_official_score(derived['official'])
                require(_identity(self.d / 'state/SEAL_BATCH.json') == derived['parent'] and _identity(derived['producer']['path']) == derived['producer'] and (_identity(derived['receipt']['path']) == derived['receipt']), 'Completed producer receipt/parent drift')
                if derived['source']:
                    require(all((_identity(derived['source']['path']).get(k) == v for k, v in derived['source'].items())), 'Completed projection source drift')
        roots = self._sealed_roots | {Path(i['path']).parent for i in self._authority_files.values()} | {Path(i['identity']['path']).parent for i in self._derived_files.values()}
        require(any((p.is_relative_to(root) for root in roots)), 'Read outside allowed sealed roots: ' + str(p))
        item = self._read_identity(p)
        require(item is not None, 'Payload absent from verified seal chain: ' + str(p))
        with self._validation():
            require(_identity(p) == item, 'Verified seal-chain payload drift: ' + str(p))

    def _install_readers(self):


        def guard_source(source):
            name = source if isinstance(source, (str, bytes, os.PathLike)) else getattr(source, 'name', None)
            require(name is not None, 'Anonymous native payload stream refused')
            require(not isinstance(name, int), 'Untracked payload file descriptor')
            p = _no_symlink_path(name)
            self._authorize_read(p)
            if not isinstance(source, (str, bytes, os.PathLike)):
                require(not getattr(source, 'closed', True) and hasattr(source, 'fileno') and source.readable(), 'Native payload stream is not an open readable file')
                try:
                    fd = source.fileno()
                    actual = os.fstat(fd)
                except (OSError, ValueError, TypeError, AttributeError) as exc:
                    raise Refusal('Untracked native payload stream') from exc
                expected = p.stat()
                require(stat.S_ISREG(actual.st_mode) and (actual.st_dev, actual.st_ino, actual.st_size) == (expected.st_dev, expected.st_ino, expected.st_size), 'Native payload descriptor differs from sealed path')
                import io
                require(type(source) in (io.FileIO, io.BufferedReader, io.BufferedRandom, io.TextIOWrapper), 'Native payload stream must be a real file object')

        def wrap(owner, attr, model=False):
            if not hasattr(owner, attr) or any((o is owner and n == attr for o, n, f in self._reader_originals)):
                return
            original = getattr(owner, attr)
            if model:

                @functools.wraps(original)
                def guarded(instance, *args, **kwargs):
                    name = kwargs.get('model_file', args[2] if len(args) > 2 else None)
                    if name is not None:
                        guard_source(name)
                    return original(instance, *args, **kwargs)
            else:

                @functools.wraps(original)
                def guarded(*args, **kwargs):
                    source = args[0] if args else next((kwargs[k] for k in ('path', 'path_or_buf', 'filepath_or_buffer', 'file', 'filename', 'source') if k in kwargs), None)
                    if source is not None:
                        guard_source(source)
                    return original(*args, **kwargs)
            self._reader_originals.append((owner, attr, original))
            setattr(owner, attr, guarded)
        for name, attrs in (('pandas', ('read_parquet', 'read_csv', 'read_pickle')), ('numpy', ('load',)), ('joblib', ('load',))):
            module = sys.modules.get(name)
            if module is not None:
                for attr in attrs:
                    wrap(module, attr)
        module = sys.modules.get('lightgbm')
        if module is not None and hasattr(module, 'Booster'):
            wrap(module.Booster, '__init__', model=True)

    def authorize_ap_route(self, route):

        return self._ap_runtime.grant(route)

    def revoke_ap_route(self):
        self._ap_runtime.revoke()

    def verify_code(self, path):
        if self._ap_runtime.family(path) is not None:
            self._ap_runtime.member(path)
            self.imported.add(str(_no_symlink_path(path).relative_to(self.project)))
            return
        p = _no_symlink_path(path)
        require(p.is_relative_to(LIVE), 'Foreign project import')
        rel = str(p.relative_to(LIVE))
        item = self._effective_sources.get(rel)
        require(item is not None and _identity(p) == dict(path=str(p), **item['identity']), 'Unpinned/drifted imported code: ' + rel)
        self.imported.add(rel)

    def patch(self, module):
        if module.__name__ == 'scorer_freeze':
            scorer_metadata._install(self, module)
        module.Path = _RoutedPath
        for name, value in list(vars(module).items()):
            if isinstance(value, Path):
                setattr(module, name, _RoutedPath(value))
        for value in vars(module).values():
            if isinstance(value, types.FunctionType) and value.__module__ == module.__name__:
                if value.__defaults__:
                    value.__defaults__ = tuple((_RoutedPath(v) if isinstance(v, Path) else v for v in value.__defaults__))
                if value.__kwdefaults__:
                    value.__kwdefaults__ = {k: _RoutedPath(v) if isinstance(v, Path) else v for k, v in value.__kwdefaults__.items()}
        if module.__name__ == 'batch_adapter':
            module.OUT = _RoutedPath(self.d)
        if module.__name__ == 'source_binding_plan':
            original_plan = module.expected_plan

            def expected_plan():
                previous = module.OUT
                module.OUT = Path(self.b)
                try:
                    return original_plan()
                finally:
                    module.OUT = previous
            module.expected_plan = expected_plan
        if module.__name__ in ('check_scoring_bindings', 'dispatch_scoring'):
            attr = 'read_json' if module.__name__ == 'check_scoring_bindings' else None
            original = getattr(module, attr) if attr else module.B.read

            def metadata(path):
                value = original(path)
                if Path(path).resolve() == (LIVE / B_REL / 'CODE_FREEZE.json').resolve():
                    with self._source_loading():
                        sf = self._load_verified('scorer_freeze').verify()
                    value = dict(value, code_sha256={**value['code_sha256'], **sf['code_sha256']})
                return value
            if attr:
                setattr(module, attr, metadata)
            else:
                module.B = types.SimpleNamespace(**vars(module.B))
                module.B.read = metadata
                module.B.Q = _RepinQ(self.q)
        entry = next((key for key, rel in ENTRIES.items() if str(LIVE / rel) == str(Path(module.__file__))), None)
        attr = 'write_output' if entry == 'read_comparisons' else 'project' if entry == 'cps8_projection' else 'run_order' if entry == 'check_scoring_context' else None
        if attr and getattr(getattr(module, attr), '_association_output_writer', None) is not self:
            original = getattr(module, attr)

            @functools.wraps(original)
            def output_producer(*args, **kwargs):
                if entry == 'check_scoring_context':
                    return self._run_journal_producer(entry, original, args, kwargs)
                return self._run_output_producer(entry, original, args, kwargs)
            output_producer._association_output_writer = self
            setattr(module, attr, output_producer)

    @contextlib.contextmanager
    def installed(self, *, preparation=False, metadata_only=False):
        global ACTIVE
        require(ACTIVE is None, 'Nested association is unsupported')
        self._preparing = preparation
        self._metadata_only = metadata_only
        if not preparation:
            self._authority_files.clear()
        if not preparation:
            self.release()
        self.sources()
        if not preparation:
            self.ambiguity()
        ACTIVE = self
        old_path = sys.path[:]
        old_get = importlib.machinery.SourceFileLoader.get_code
        old_exec = importlib.machinery.SourceFileLoader.exec_module
        old_import = builtins.__import__
        old_import_module = importlib.import_module
        old_execve = os.execve
        old_run = __import__('subprocess').run
        reference_snapshot = dict(sys.modules)

        def get_code(loader, fullname):
            if self._ap_runtime.family(loader.path) is not None:
                payload = self._ap_runtime.source_bytes(loader.path)
                return compile(payload, str(_no_symlink_path(loader.path)), 'exec', dont_inherit=True)
            p = _no_symlink_path(loader.path)
            if p.is_relative_to(LIVE) and p.parent != HERE:
                self.verify_code(p)
                with self._source_loading():
                    return compile(p.read_bytes(), str(p), 'exec', dont_inherit=True)
            if p.parent == HERE:
                item = self._authority_files.get(str(p))
                require(item is not None, 'Unpinned association source import: ' + str(p))
                with self._validation():
                    require(_identity(p) == item, 'Association source import drift: ' + str(p))
                with self._source_loading():
                    return compile(p.read_bytes(), str(p), 'exec', dont_inherit=True)
            old = self._runtime_loading_paths.copy()
            require(p.suffix in ('.py', '.pyc') and any((p.is_relative_to(r) for r in self._runtime_roots)), 'Foreign runtime source loader refused: ' + str(p))
            self._runtime_loading_paths.add(p)
            if p.suffix == '.py':
                self._runtime_loading_paths.add(Path(importlib.util.cache_from_source(str(p))))
            try:
                return old_get(loader, fullname)
            finally:
                self._runtime_loading_paths = old

        def exec_module(loader, module):
            family = self._ap_runtime.family(loader.path)
            if family is not None:
                self._ap_runtime.member(loader.path)
            try:
                result = old_exec(loader, module)
            except BaseException:
                if family is not None:
                    self._ap_runtime.revoke()
                raise
            if family is not None:
                self._ap_runtime.member(loader.path)
                self.patch(module)
                self._ap_runtime.guard_module(module)
            elif _no_symlink_path(loader.path).is_relative_to(LIVE) and _no_symlink_path(loader.path).parent != HERE:
                self.patch(module)
            self._install_readers()
            return result

        def argv(command):
            if not isinstance(command, (list, tuple)):
                return command
            result = list(command)
            for i, arg in enumerate(result):
                if isinstance(arg, str) and Path(arg).is_absolute():
                    mapped = self.route(arg)
                    if str(mapped) in (str(LIVE / r) for r in ENTRIES.values()):
                        require(i > 0 and Path(result[0]).name.startswith('python'), 'Consumer child must use Python')
                        entry = next((k for k, r in ENTRIES.items() if str(LIVE / r) == str(mapped)))
                        if entry in FIT_SHIMS:
                            return [*result[:i], str(HERE / FIT_SHIMS[entry]), *result[i + 1:]]
                        context=['postscore','--project',str(self.project),'--request',os.environ.get('SCORING_REQUEST',''),'--request-bytes',os.environ.get('SCORING_REQUEST_BYTES',''),'--request-sha256',os.environ.get('SCORING_REQUEST_SHA256',''),'--request-provenance',os.environ.get('SCORING_REQUEST_PROVENANCE',''),'--request-provenance-bytes',os.environ.get('SCORING_REQUEST_PROVENANCE_BYTES',''),'--request-provenance-sha256',os.environ.get('SCORING_REQUEST_PROVENANCE_SHA256','')]
                        require(all(context),'Exact inherited reviewed child context missing')
                        if self.synthetic:context.append('--synthetic')
                        return [*result[:i],str(HERE/'dispatch.py'),*context,'--consumer',entry,'--',*result[i+1:]]
                    result[i] = str(mapped)
            return result

        def execve(path, command, env):
            require(not self.synthetic, 'Synthetic test cannot exec a host child')
            return old_execve(path, argv(command), env)

        def run(command, *a, **kw):
            return old_run(argv(command), *a, **kw)

        def checked_import(*args, **kwargs):
            if not self._validation_depth:
                self._ap_runtime.revalidate()
            result = old_import(*args, **kwargs)
            self._ap_runtime.cached_module(result)
            if not self._validation_depth:
                self._ap_runtime.revalidate()
            return result

        def checked_import_module(*args, **kwargs):
            if not self._validation_depth:
                self._ap_runtime.revalidate()
            result = old_import_module(*args, **kwargs)
            self._ap_runtime.cached_module(result)
            if not self._validation_depth:
                self._ap_runtime.revalidate()
            return result
        builtins.__import__ = checked_import
        importlib.import_module = checked_import_module
        importlib.machinery.SourceFileLoader.get_code = get_code
        importlib.machinery.SourceFileLoader.exec_module = exec_module
        os.execve = execve
        __import__('subprocess').run = run
        try:
            self._ap_runtime.revoke()
            for name, module in list(sys.modules.items()):
                path = getattr(module, '__file__', None)
                if path and Path(path).resolve().is_relative_to(LIVE) and (Path(path).resolve().parent != HERE):
                    del sys.modules[name]
            sys.path[:0] = [str(LIVE / B_REL / 'code'), str(LIVE / 'studies/inference/code'), str(LIVE / 'studies/source_bindings')]
            self._install_readers()
            yield self
        finally:

            ACTIVE = None
            self._preparing = False
            self._metadata_only = False
            self._ap_runtime.revoke()
            builtins.__import__ = old_import
            importlib.import_module = old_import_module
            importlib.machinery.SourceFileLoader.get_code = old_get
            importlib.machinery.SourceFileLoader.exec_module = old_exec
            os.execve = old_execve
            __import__('subprocess').run = old_run
            for owner, name, original in reversed(self._reader_originals):
                setattr(owner, name, original)
            self._reader_originals.clear()
            sys.path[:] = old_path
            for name in list(sys.modules):
                path = getattr(sys.modules[name], '__file__', None)
                if path and Path(path).resolve().is_relative_to(LIVE) and (Path(path).resolve().parent != HERE):
                    del sys.modules[name]
            for name, module in reference_snapshot.items():
                family_path = getattr(module, '__file__', None)
                if family_path and self._ap_runtime.family(family_path) is not None:
                    continue
                if name not in sys.modules:
                    sys.modules[name] = module
            ACTIVE = None
            self._preparing = False
            self._metadata_only = False

    def t5_roots(self):
        with self._metadata_access():
            return self._t5_roots_body()

    def _t5_roots_body(self):
        self.release()
        self._check_ambiguity()
        commitment = self.t5_commitments()
        fixed = ['consumer_roots.py', 'SOURCE_LOCK.json', 'SCIENCE_FREEZE.json', 'SCORER_CODE_FREEZE.json', 'SCORER_BINDINGS.json', 'SCIENTIFIC_ASSOCIATION.json', 'SCIENTIFIC_ACCEPTANCE_RECEIPT.json', 'SOURCE_CLOSURE_RECEIPT.json', 'INDEPENDENT_REVIEW.json']
        paths = {self.out / p for p in fixed} | {self.out / 'T5_IDENTITY_COMMITMENTS.json', self.out / 'T5_COMMITMENT_SOURCE_RECEIPT.json'}
        paths |= {Path(i['path']) for i in commitment['files'] if self.metadata_root(i['path'])}
        paths.update(self.host_metadata())
        paths.update(self.science_t5_metadata())
        for rel in _read(self.out / 'SCIENCE_FREEZE.json')['files']:
            paths.add(self.out / rel)
        scorer = _read(self.out / 'SCORER_CODE_FREEZE.json')
        for item in [scorer['batch_code_freeze'], scorer['numerical_inputs'], scorer['scorer_bindings'], *scorer['files']]:
            paths.add(_checked(item))
        for p in (self.out / 'CPS8_METADATA.json', self.out / 'CPS8_METADATA.receipt.json'):
            if p.exists():
                paths.add(p)
        if (self.out / 'CPS8_METADATA.receipt.json').exists():
            projection = _read(self.out / 'CPS8_METADATA.receipt.json')
            for name in ('source', 'adapter'):
                paths.add(_checked(projection[name]))
        if (self.out / 'OUTPUT_EVIDENCE_BINDINGS.json').exists():
            for row in _read(self.out / 'OUTPUT_EVIDENCE_BINDINGS.json')['files']:
                if row['role'] == 'PRODUCER_SIDECAR_CACHE':
                    paths.update((_checked(i) for i in row['producer_sources']))
        paths.update((self.d / 'DISK_FREEZE.json', self.d / 'T4C_BINDING.json', self.d / 'T4C_ROOTS.json', self.b / 'CODE_FREEZE.json'))
        paths.add(self.d / 'state/B0_REPRODUCTION.json')
        require(all((self.metadata_root(p) for p in paths)), 'T5 root is a payload or unreviewed production path')
        for p in paths:
            require(p.is_file() and (not p.is_symlink()), 'T5 root is not an exact regular file: ' + str(p))
        require(all((p.resolve().is_relative_to(self.project) for p in paths)), 'T5 file escapes study project')
        return sorted((os.path.relpath(p, self.q) for p in paths))

    def _disk_release(self, binding):
        for name in ('disk_freeze', 't4c_binding'):
            _checked(binding[name])
        require(Path(binding['disk_freeze']['path']) == self.d / 'DISK_FREEZE.json' and Path(binding['t4c_binding']['path']) == self.d / 'T4C_BINDING.json', 'Wrong disk release association')
        frozen = _read(binding['disk_freeze']['path'])
        require(frozen['state'] == 'FROZEN_RESOURCE_ONLY_DISK_SPECIFICATION', 'Invalid D freeze')
        roots = dict(batch=str(self.b), state=str(self.d / 'state'), dly8=str(self.d / 'dly8'), cps8=str(self.d / 'cps8'))
        require(frozen['roots'] == roots and _read(self.d / 'T4C_ROOTS.json') == roots, 'D layout changed; reverify binding')
        for rel, item in frozen['files'].items():
            p = _contained(self.d / rel, self.d)
            require(_identity(p) == dict(path=str(p), **item), 'Frozen D supplement drift: ' + rel)
        for rel, item in frozen['parents'].items():
            require(_identity(LIVE / rel) == dict(path=str(LIVE / rel), **item), 'D parent drift: ' + rel)
        t = _read(binding['t4c_binding']['path'])
        require(t['label'] == 'T4C' and t['state'] == 'T4C_VERIFIED' and (t['source_verified'] is True) and (t['roots'] == roots) and (t['supplement_freeze'] == _identity(self.d / 'DISK_FREEZE.json')), 'Unverified T4C')
        parse = lambda s: dt.datetime.fromisoformat(s.replace('Z', '+00:00'))
        require(parse(t['utc']).utcoffset() == dt.timedelta(0) and parse(t['utc']) >= parse(frozen['utc']), 'T4C chronology')
        for item in [*t['files'], *t['tsa_receipts']]:
            _checked(item)
        require(len(t['tsa_receipts']) >= 2, 'Two verified T4C TSA identities required')
        require(all((_identity(p) in t['files'] for p in (self.d / 'DISK_FREEZE.json', self.d / 'T4C_ROOTS.json', self.b / 'CODE_FREEZE.json'))), 'T4C root coverage')
        self.verify_host_parents(binding)

    def official_views(self, original_inputs, r2_inputs, execution_identity):
        self._official_ready = None
        try:
            certificate = self._official_score(dict(original=original_inputs, r2=r2_inputs, execution=execution_identity))
            self._official_ready = __import__('copy').deepcopy(certificate)
            return __import__('copy').deepcopy(certificate)
        except BaseException:
            self._official_ready = None
            self._official_files.clear()
            self._ap_runtime.revoke()
            raise

    def _verify_numeric_ancestors(self, item):
        return science_contract._numeric_ancestors(self, runtime_sources._Core(globals()), item)

    def _producer_identity(self,path):
        require(ACTIVE is self and self._native_scope is not None,'Private active producer hash scope required')
        p=_no_symlink_path(path);scope=self._native_scope
        _contained(p,scope['root'])
        require(str(p) in scope['written'] and (not scope['outputs'] or str(p) in scope['outputs']),'Only exact newly written producer output may self-check')
        with self._validation():
            self.verify_code(scope['code']['path'])
            return _identity(p)

    def _ready_inputs(self, inputs):
        require(self._official_ready is not None, 'Original/capture/R2 completion required')
        self._check_official_score(self._official_ready)
        require(inputs.get('score_receipt') == self._official_ready['view_inputs']['original']['score_receipt'], 'Original receipt cannot be substituted or relabelled')
        require(inputs.get('seal') == self._official_ready['view_inputs']['original']['seal'], 'Original seal identity drift')
        require(inputs.get('score_report') == self._official_ready['view_inputs']['original']['score_report'], 'Original report identity drift')
        require(inputs.get('scientific_views') == self._official_ready['view_inputs'], 'Both score views and execution must be committed in published evidence')
        return self._official_ready

class _ConsumerModule(types.ModuleType):


    def __init__(self, association, module, entry):
        types.ModuleType.__init__(self, module.__name__)
        types.ModuleType.__setattr__(self, '_association', association)
        types.ModuleType.__setattr__(self, '_module', module)
        types.ModuleType.__setattr__(self, '_entry', entry)

    def __getattribute__(self, name):
        if name in ('_association', '_module', '_entry', '__class__'):
            return types.ModuleType.__getattribute__(self, name)
        module = types.ModuleType.__getattribute__(self, '_module')
        value = getattr(module, name)
        if isinstance(value, types.FunctionType):
            association = types.ModuleType.__getattribute__(self, '_association')
            entry = types.ModuleType.__getattribute__(self, '_entry')

            @functools.wraps(value)
            def guarded(*args, **kwargs):
                return association._call_public(entry, value, args, kwargs)
            return guarded
        if types.ModuleType.__getattribute__(self, '_entry') == 'runner' and callable(value):
            require(value is _RoutedPath, 'Runner API only exposes export and path support functions')
        return value

    def __setattr__(self, name, value):
        if name in ('_association', '_module', '_entry'):
            return types.ModuleType.__setattr__(self, name, value)
        setattr(types.ModuleType.__getattribute__(self, '_module'), name, value)

def _routed_input(*args):
    p = Path(*args)
    if ACTIVE and ACTIVE._ap_runtime.family(p) is not None:
        for arg in args:
            raw = os.fsdecode(os.fspath(arg))
            operand = Path(raw)
            require(bool(raw) and raw == str(operand) and ('..' not in operand.parts) and ('.' not in raw.split(os.sep)), 'G39 noncanonical path/alias: ' + raw)
        ACTIVE._ap_runtime._token(p)
    return p

class _RoutedPath(type(Path())):

    def __new__(cls, *args):
        p = _routed_input(*args)
        routed = ACTIVE.route(p) if ACTIVE else p
        if ACTIVE and routed != p:
            _no_symlink_path(p)
        return super().__new__(cls, routed)

    def __init__(self, *args):
        p = _routed_input(*args)
        routed = ACTIVE.route(p) if ACTIVE else p
        if ACTIVE and routed != p:
            _no_symlink_path(p)
        super().__init__(routed)

    def resolve(self, strict=False):
        if not ACTIVE:
            return super().resolve(strict=strict)
        p = _no_symlink_path(self)
        if strict:
            p.lstat()
        return _RoutedPath(p)

    def __truediv__(self, key):
        return _RoutedPath(str(self), key)

    def joinpath(self, *args):
        return _RoutedPath(str(self), *args)

class _RepinQ(_RoutedPath):

    def __truediv__(self, key):
        rel = Path(key)
        if ACTIVE and (not rel.is_absolute()) and rel.parts and (rel.parts[0] == 'batch_estimation'):
            return _RoutedPath(ACTIVE.b.joinpath(*rel.parts[1:]))
        return _RoutedPath(str(self), key)

def _audit(event, args):
    if ACTIVE is None:
        return
    if event in ('open', 'os.listdir', 'os.scandir') and args and isinstance(args[0], (str, bytes, os.PathLike)):
        if event == 'open' and not ACTIVE._validation_depth and ACTIVE._ap_runtime.family(args[0]) is not None and (ACTIVE._native_scope is None or str(args[0]) in ACTIVE._authority_files):
            ACTIVE._ap_runtime.member(args[0])
        p = _no_symlink_path(args[0])
        observation=getattr(ACTIVE,'_resource_metadata_root',None)
        if event in ('os.listdir','os.scandir') and observation is not None and observation.is_relative_to(Path('/private/tmp')) and ACTIVE.project.is_relative_to(observation) and p.is_relative_to(observation):
            return
        if (ACTIVE._preparing and (any((p.is_relative_to(ACTIVE.d / root) for root in ('state', 'dly8', 'cps8'))) or 'host_state' in p.parts)) and (not ACTIVE._bootstrap_depth):
            raise Refusal('Freeze preparation cannot access production outputs: ' + str(p))
        for b in (LIVE / B_REL, ACTIVE.b, ACTIVE.q / 'batch_estimation'):
            if any((p.is_relative_to(b / root) for root in ('state', 'dly8', 'cps8'))):
                if not (ACTIVE._ambiguity_depth and event in ('os.listdir', 'os.scandir')):
                    raise Refusal('No silent SET4 fallback: ' + str(p))
        if event == 'open':
            mode = args[1] if len(args) > 1 else None
            flags = args[2] if len(args) > 2 else 0
            writing = isinstance(mode, str) and any((c in mode for c in 'wax+')) or (isinstance(flags, int) and bool(flags & (os.O_WRONLY | os.O_RDWR | os.O_CREAT | os.O_TRUNC | os.O_APPEND)))
            reading = isinstance(mode, str) and ('r' in mode or '+' in mode) or (isinstance(flags, int) and flags & os.O_ACCMODE != os.O_WRONLY)
            if writing and ACTIVE._native_scope is not None:
                output_lifecycle._write(ACTIVE, p)
                if not reading:
                    return
            associated = any((p.is_relative_to(ACTIVE.d / root) for root in ('state', 'dly8', 'cps8'))) or p == ACTIVE.d / 'REMEDY_LOG.md'
            new_exclusive = writing and (not p.exists()) and isinstance(flags, int) and bool(flags & os.O_EXCL) and (ACTIVE._guard_depth > 0)
            if reading and (not new_exclusive):
                ACTIVE._authorize_read(p)
            else:
                if writing and ACTIVE._helper_copy:
                    copy = ACTIVE._helper_copy
                    destination = copy['destination']
                    if p == destination or (p.parent == destination.parent and p.name.startswith(destination.name + '.atomic.')):
                        copy['files'][str(p)] = copy['source']
                if writing and ACTIVE._output_scope and (p in ACTIVE._output_scope['paths']):
                    official = ACTIVE._output_scope.get('official')
                    if official:
                        ACTIVE._check_official_score(official)
                    ACTIVE._output_scope['written'].add(p)
                    ACTIVE._output_scope['files'].pop(str(p), None)
                if ACTIVE._producer_entry == 'score_batch' and p.is_relative_to(ACTIVE.d / 'state/scoring'):
                    ACTIVE._producer_paths.add(p)
                    ACTIVE._producer_seal['files'].pop(str(p), None)
                if associated and (not ACTIVE._validation_depth) and (not ACTIVE._guard_depth):
                    require(not ACTIVE._metadata_only and (not ACTIVE._metadata_depth), 'Metadata-only access cannot write D outputs')
                    ACTIVE.verify_t5_coverage()
    elif event in ('os.rename', 'os.link') and len(args) > 1:
        source = _no_symlink_path(args[0])
        destination = _no_symlink_path(args[1])
        if ACTIVE._output_scope and destination in ACTIVE._output_scope['paths']:
            scope = ACTIVE._output_scope
            require(source.parent == destination.parent and source.name.startswith(destination.name + '.atomic.'), 'Original producer publication outside fixed atomic path')
            if scope.get('official'):
                ACTIVE._check_official_score(scope['official'])
            scope['written'].add(destination)
            scope['files'].pop(str(destination), None)
        if ACTIVE._helper_copy:
            copy = ACTIVE._helper_copy
            item = copy['files'].get(str(source)) or (copy['old'] if source == copy['destination'] else None)
            if item is not None:
                copy['files'][str(destination)] = item
        if ACTIVE._producer_entry == 'score_batch' and destination.is_relative_to(ACTIVE.d / 'state/scoring'):
            ACTIVE._producer_paths.add(destination)
            ACTIVE._producer_seal['files'].pop(str(destination), None)
    if ACTIVE._native_scope is not None and event in ('os.rename', 'os.link', 'os.mkdir', 'os.remove', 'os.rmdir'):
        for raw in args[:2 if event in ('os.rename', 'os.link') else 1]:
            if isinstance(raw, (str, bytes, os.PathLike)):
                output_lifecycle._write(ACTIVE, _no_symlink_path(raw), directory=(event=='os.mkdir'))
sys.addaudithook(_audit)
