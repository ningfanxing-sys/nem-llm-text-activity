'Check the input records required for forecast execution.'
from __future__ import annotations
import contextlib
import datetime as dt
import hashlib
import importlib
import json
import os
from pathlib import Path
import sys
import tempfile


sys.dont_write_bytecode = True

ROOT = Path(__file__).resolve().parent
confirmation = ROOT.parent
PROJ = confirmation.parents[2]
STATE = ROOT / 'host_state'
_AUDIT_FDS = {}

def install_audit(reader='host'):

    if reader in _AUDIT_FDS:
        return
    log = ROOT / ('OPENED_PATHS_' + reader + '.jsonl')
    fd = os.open(log, os.O_CREAT | os.O_APPEND | os.O_WRONLY, 0o600)
    _AUDIT_FDS[reader] = fd
    def event(kind, args):
        if kind != 'open' or not isinstance(args[0], (str, bytes, os.PathLike)):
            return
        path = os.path.abspath(os.fsdecode(args[0]))
        if path == str(log):
            return
        credential = (Path(path).name in {'.env', '.netrc'} or
                      '/.llm_client/auth.json' in path or '/.aws/credentials' in path or
                      '/huggingface/token' in path or '/huggingface/stored_tokens' in path or
                      '/Keychains/' in path)
        if '/semantic_validation/private/' in path or credential:
            raise PermissionError('Protected path prohibited: ' + path)
        item = {'time_utc': utc_now(), 'path': path, 'reader': reader,
                'mode': str(args[1]), 'purpose': 'execution audited host or synthetic execution'}
        os.write(fd, (json.dumps(item, ensure_ascii=False) + '\n').encode())
    sys.addaudithook(event)

def utc_now():
    return dt.datetime.now(dt.timezone.utc).isoformat()

def sha256(path):
    h = hashlib.sha256()
    with Path(path).open('rb') as f:
        for block in iter(lambda: f.read(1024 * 1024), b''):
            h.update(block)
    return h.hexdigest()

def file_identity(path, **extras):
    p = Path(path).resolve()
    return {'path': str(p), 'sha256': sha256(p), 'bytes': p.stat().st_size, **extras}

def read_json(path):
    return json.loads(Path(path).read_text(encoding='utf-8'))

def canonical_bytes(value):
    return (json.dumps(value, sort_keys=True, ensure_ascii=False, indent=2, allow_nan=False) + '\n').encode()

def atomic_json(path, value, *, immutable=False):
    p = Path(path); p.parent.mkdir(parents=True, exist_ok=True)
    b = canonical_bytes(value)
    if immutable and p.exists():
        if p.read_bytes() != b:
            raise RuntimeError('Refusing to overwrite immutable receipt: ' + str(p))
        return p
    fd, name = tempfile.mkstemp(prefix=p.name + '.', suffix='.tmp', dir=p.parent)
    try:
        with os.fdopen(fd, 'wb') as f:
            f.write(b); f.flush(); os.fsync(f.fileno())
        if immutable:

            os.link(name, p); os.unlink(name)
        else:
            os.replace(name, p)
    finally:
        if os.path.exists(name):
            os.unlink(name)
    return p

def conf_module(name):
    code = str(confirmation / 'code')
    if code not in sys.path:
        sys.path.insert(0, code)
    return importlib.import_module(name)

def verify_design(conf_root=None):
    conf = Path(conf_root or confirmation)
    freeze = read_json(conf / 'FREEZE.json')
    for rel, identity in freeze['frozen_files'].items():
        p = conf / rel
        if sha256(p) != identity['sha256'] or p.stat().st_size != identity['bytes']:
            raise PermissionError('Frozen design drift: ' + rel)
    return freeze

def verify_identities(identities):
    for item in identities:
        p = Path(item['path'])
        if not p.is_file() or sha256(p) != item['sha256'] or p.stat().st_size != item['bytes']:
            raise PermissionError('Input bytes drift: ' + str(p))

def verify_adapters(root=None):
    root = Path(root or ROOT)
    manifest = read_json(root / 'ADAPTER_FREEZE.json')
    if manifest.get('state') != 'SPEC_2_FROZEN_SYNTHETICALLY_VERIFIED':
        raise PermissionError('Adapters not frozen')
    for rel, item in manifest['files'].items():
        p = root / rel
        if sha256(p) != item['sha256'] or p.stat().st_size != item['bytes']:
            raise PermissionError('Execution adapter drift: ' + rel)
    return manifest


SPECIFICATION_CHAIN=('shared_storage','quantity_parsing','input_definitions','storage_limits','fit_memory','news_memory')
SPEC_4_FEATURE_CONTENT_CHANGE='NRX_MW_LITERAL_PARSING_CORRECTION_ONLY'
SPEC_5_FEATURE_CONTENT_CHANGE='A1_SECONDARY_ARMS_W2_D_AND_NPM_ADDED_EXISTING_ARMS_UNCHANGED'
SPEC_5_ADDED_SECONDARY_ARMS={'news':['W2_D'],'notice':['NPM']}
SPEC_5_UNCHANGED='primary_families_contrasts_holm_windows_learners_seeds_budget_drop_order_unchanged'
SPEC_6_RESOURCE_RULE='FEATURE_AUXILIARY_ALLOWANCE_DERIVED_RESERVATION_NOT_A_STOP'
SPEC_7_RESOURCE_RULE='FIT_MEMORY_ANONYMOUS_LIMITS_WIDE_ARM_ADMISSION_QUERY_AFTER_FIT'
SPEC_7_RESUME_IDENTITY_RULE='RESUME_PANEL_COPY_BYTES_EQUAL_CANONICAL_SERIALIZATION'
SPEC_7_THROUGHPUT_RULE='NEWS_POOL_UP_TO_7_RESERVED_ANONYMOUS_ADMISSION_LEAR_3_WINDOW_SUBJOBS'
SPEC_8_RESOURCE_RULE='NEWS_PER_FIT_ANONYMOUS_3_5_GIB_MEASURED_PROJECTION_FLOORS'


def _specification_declared(task,specification):
    if task=='shared_storage':
        return specification.get('no_statistical_design_or_feature_content_change') is True
    if task=='quantity_parsing':
        return (specification.get('no_statistical_design_or_inference_rule_change') is True and
                specification.get('feature_content_change')==SPEC_4_FEATURE_CONTENT_CHANGE)
    if task=='input_definitions':
        return (specification.get('pre_score_addendum')=='confirmation-A1' and
                specification.get(SPEC_5_UNCHANGED) is True and
                specification.get('primary_decision_rule_change') is False and
                specification.get('feature_content_change')==SPEC_5_FEATURE_CONTENT_CHANGE and
                specification.get('added_secondary_arms')==SPEC_5_ADDED_SECONDARY_ARMS)
    if task=='storage_limits':
        return (specification.get('no_statistical_design_or_feature_content_change') is True and
                specification.get('execution_resource_rule')==SPEC_6_RESOURCE_RULE)
    if task=='fit_memory':
        return (specification.get('no_statistical_design_or_feature_content_change') is True and
                specification.get('execution_resource_rule')==SPEC_7_RESOURCE_RULE and
                specification.get('resume_identity_rule')==SPEC_7_RESUME_IDENTITY_RULE and
                specification.get('throughput_rule')==SPEC_7_THROUGHPUT_RULE)
    if task=='news_memory':
        return (specification.get('no_statistical_design_or_feature_content_change') is True and
                specification.get('execution_resource_rule')==SPEC_8_RESOURCE_RULE)
    return False


def adapter_specification_chain(root,expected_hash):

    root=Path(root).resolve();manifest=verify_adapters(root)
    freeze_path=root/'ADAPTER_FREEZE.json'
    if expected_hash==sha256(freeze_path):return manifest,[]
    freeze_key=str(freeze_path.relative_to(root.parent))
    steps=[];child=manifest
    while True:
        specification=child.get('execution_specification')
        if not isinstance(specification,dict):
            if steps:raise PermissionError('Adapter specification does not descend from input-bound freeze')
            raise PermissionError('Adapter freeze changed without execution-only specification')
        if len(steps)==len(SPECIFICATION_CHAIN):
            raise PermissionError('Adapter specification does not descend from input-bound freeze')
        task=specification.get('task')
        if not _specification_declared(task,specification):
            raise PermissionError('Adapter freeze changed without execution-only specification')
        identities=[specification.get(k) for k in ('parent_adapter_freeze','execution_note','before_identities')]
        if not all(isinstance(x,dict) and {'path','sha256','bytes'}<=set(x) for x in identities):
            raise PermissionError('Execution specification identities missing')
        verify_identities(identities)
        parent=identities[0];reference_snapshot=read_json(identities[2]['path'])
        archived=reference_snapshot.get(freeze_key,{})
        if (archived.get('sha256')!=parent['sha256'] or archived.get('bytes')!=parent['bytes'] or
                Path(archived.get('archive_path','')).resolve()!=Path(parent['path']).resolve()):
            raise PermissionError('Archived parent adapter freeze identity mismatch')
        ancestor=read_json(parent['path'])
        if ancestor.get('design_freeze')!=child.get('design_freeze') or ancestor.get('execution_rule')!=child.get('execution_rule'):
            raise PermissionError('Execution specification changed design or input rule')
        steps.insert(0,{'task':task,'parent_adapter_freeze':parent,'reference_snapshot':reference_snapshot,'ancestor':ancestor})
        if parent['sha256']==expected_hash:break
        child=ancestor
    if tuple(step['task'] for step in steps)!=SPECIFICATION_CHAIN:
        raise PermissionError('Adapter specification chain is not exactly input-bound -> '+' -> '.join(SPECIFICATION_CHAIN))
    for index,step in enumerate(steps):
        for rel,item in step['ancestor']['files'].items():
            original=(root/rel).resolve()
            key=str(original.relative_to(root.parent))
            archived=[later['reference_snapshot'][key] for later in steps[index:] if key in later['reference_snapshot']]
            candidate=Path(archived[0]['archive_path']) if archived else original
            if not candidate.is_file() or sha256(candidate)!=item['sha256'] or candidate.stat().st_size!=item['bytes']:
                raise PermissionError('Archived adapter ancestor drift: '+rel)
    return manifest,steps


def verify_adapter_ancestor(root,expected_hash):

    return adapter_specification_chain(root,expected_hash)[0]


def validate_permit(conf_root=None, receipt_path=None):

    conf = Path(conf_root or confirmation)
    receipt_path = Path(receipt_path or conf / 'execution/host_state/EXECUTION_AUTHORIZATION.json')
    receipt = read_json(receipt_path)
    inputs = read_json(receipt['completed_input_manifest_path'])
    if inputs.get('state') != 'COMPLETE_GLOBAL_INPUT_FREEZE' or inputs.get('pending_dependencies'):
        raise PermissionError('The frozen GLOBAL input gate is incomplete')
    if inputs.get('nrx_terminal_census', {}).get('state') not in {'COMPLETE', 'PARTIAL-final'}:
        raise PermissionError('notice_extraction has not finalized the full census')
    adapter_root=conf/'execution'
    manifest,steps=adapter_specification_chain(adapter_root,inputs.get('adapter_freeze_sha256'))
    guard=conf_module('guard')
    if inputs['adapter_freeze_sha256']==sha256(adapter_root/'ADAPTER_FREEZE.json'):
        return guard.load_permit(receipt_path,conf)


    from types import FunctionType
    parent=steps[0]['parent_adapter_freeze']
    adapter_path=(adapter_root/'ADAPTER_FREEZE.json').resolve()
    linked=[item for item in inputs['inputs'] if Path(item['path']).resolve()==adapter_path]
    if len(linked)!=1 or linked[0]['sha256']!=parent['sha256'] or linked[0]['bytes']!=parent['bytes']:
        raise PermissionError('Input-bound adapter ancestor identity mismatch')
    def archived_adapter_digest(path):
        if Path(path).resolve()==adapter_path:return guard.digest(parent['path'])
        return guard.digest(path)
    loader=FunctionType(guard.load_permit.__code__,
        {**guard.load_permit.__globals__,'digest':archived_adapter_digest},
        guard.load_permit.__name__,guard.load_permit.__defaults__,guard.load_permit.__closure__)
    return loader(receipt_path,conf)

@contextlib.contextmanager
def exclusive_lock(path):
    import fcntl
    p = Path(path); p.parent.mkdir(parents=True, exist_ok=True)
    with p.open('a+') as f:
        try:
            fcntl.flock(f, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError as exc:
            raise RuntimeError('Another confirmation host command is active') from exc
        try:
            yield
        finally:
            fcntl.flock(f, fcntl.LOCK_UN)

def audit(path, mode='read', purpose='execution explicit read'):

    log = ROOT / 'OPENED_PATHS_execution_host.jsonl'
    with log.open('a') as f:
        f.write(json.dumps({'time_utc':utc_now(), 'path':str(Path(path).resolve()),
                            'reader':'execution_host', 'mode':mode, 'purpose':purpose}) + '\n')
