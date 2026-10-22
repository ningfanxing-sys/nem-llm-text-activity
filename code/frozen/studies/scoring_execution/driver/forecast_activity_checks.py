'Check forecast activity and save computation receipts.'
import contextlib
from collections import Counter
import hashlib
import uuid
import time
from pathlib import Path
from forecast_check_helpers import exclusive, now, row
from forecast_processes import SameUID, same_uid_snapshot, exception_detail
from forecast_receipts import RUNTIME_ACTIONS, new_activity_root

ACTIONS = ('af-source-freeze', 'af-execute', 'verify-seal', 'guard-dry-run')
HERE = Path(__file__).absolute().parent


KERNEL_KINDS = frozenset(('NPOLICY', 'NEXUS', 'PIPE', 'KQUEUE', 'unix', 'IPv4', 'IPv6',
    'systm', 'ndrv', 'FSEVENTS', 'CHAN', 'SOCK', 'VSOCK', 'PSXSEM', 'PSXSHM',
    'SMT', 'SHM', 'SEM', 'FPOLICY'))
CENSUS_INSTABILITY = 'Cannot certify host fit/rebuild non-overlap: process census changed'


def snapshot_counts(data):

    counts = Counter(); nameless = Counter(); current = None
    if isinstance(data, bytes):
        records = []
        for raw in data.split(b'\0'):
            token = raw.lstrip(b'\n')
            if token.startswith(b'f'):
                current = {}; records.append(current)
            elif token.startswith(b'p'):
                current = None
            elif current is not None and token[:1] in (b't', b'n'):
                current[token[:1]] = token[1:]
        for rec in records:
            kind = rec.get(b't', b'').decode('utf-8', errors='replace') or 'MISSING_TYPE'
            counts[kind] += 1
            if not rec.get(b'n'): nameless[kind] += 1
    return dict(counts_by_kind=dict(sorted(counts.items())),
                nameless_counts_by_kind=dict(sorted(nameless.items())))


def filter_snapshot(data, cannot, *, evidence=None):
    evidence = evidence if evidence is not None else {}
    removed = evidence.setdefault('removed_records', [])
    empty = evidence.setdefault('empty_process_rows', [])
    evidence.update(snapshot_counts(data))

    if not isinstance(data, bytes) or not data or not data.endswith(b'\0\n'):
        cannot('missing/truncated lsof field output')
    groups = []
    for raw in data.split(b'\0')[:-1]:
        token = raw.lstrip(b'\n')
        if token.startswith(b'p'):
            groups.append(dict(header=[raw], files=[]))
        elif not groups:
            if token: cannot('lsof field outside process')
        elif token.startswith(b'f'):
            groups[-1]['files'].append([raw])
        elif groups[-1]['files']:
            groups[-1]['files'][-1].append(raw)
        else:
            groups[-1]['header'].append(raw)
    kept = []; pids = []
    evidence['process_order'] = []
    for group in groups:
        header = [r.lstrip(b'\n') for r in group['header'] if r.lstrip(b'\n')]
        try:
            fields = [(chr(r[0]), r[1:].decode('utf-8', errors='strict')) for r in header]
        except UnicodeError:
            cannot('undecodable lsof metadata')
        pid = fields[0][1]
        if not pid.isdecimal() or int(pid) <= 0: cannot('invalid lsof PID')
        pids.append(int(pid)); evidence['process_order'].append(int(pid))
        uids = [v for k, v in fields[1:] if k == 'u']
        if len(uids) != 1 or not uids[0].isdecimal(): cannot('missing/duplicate lsof UID')
        if any(k not in ('u', 'c') for k, v in fields[1:]): cannot('unexpected lsof process field')
        command = next((v for k, v in reversed(fields) if k == 'c'), '')
        files = []
        for record in group['files']:
            tokens = [r.lstrip(b'\n') for r in record if r.lstrip(b'\n')]
            try:
                fields_ = [(chr(t[0]), t[1:].decode('utf-8', errors='strict')) for t in tokens]
            except UnicodeError:
                cannot('undecodable lsof metadata')
            keys = [k for k, v in fields_]; f = dict(fields_)
            if not f.get('f') or f['f'] == 'err': cannot('inaccessible lsof descriptor')
            if len(keys) != len(set(keys)): cannot('duplicate lsof file field')
            if keys[0] != 'f' or set(keys) - set('ftnal'): cannot('unexpected lsof file field')
            if not f.get('t'): cannot('incomplete descriptor visibility: missing type')
            if not f.get('n') and f['t'] in KERNEL_KINDS:

                if f['f'] in ('cwd', 'txt', 'mem'): cannot('unavailable filesystem name')
                removed.append(dict(pid=int(pid), command=command, fd=f['f'], type=f['t'], name=''))
            else:
                files.extend(record)
        if files:
            kept.extend(group['header']); kept.extend(files)
        elif not group['files']:
            cannot('incomplete lsof process')
        else:

            empty.append(dict(pid=int(pid), uid=int(uids[0]), files=[]))
    if len(pids) != len(set(pids)): cannot('duplicate lsof process')
    evidence['dropped_counts_by_kind'] = dict(sorted(Counter(r['type'] for r in removed).items()))
    return (b'\0'.join(kept) + b'\0\n' if kept else b''), removed


def adapted_parse(data, original, cannot, evidence):
    filtered, removed = filter_snapshot(data, cannot, evidence=evidence)
    evidence['filtered_snapshot_bytes'] = len(filtered)
    evidence['filtered_snapshot_sha256'] = hashlib.sha256(filtered).hexdigest()
    parsed = original(filtered) if filtered else []
    by_pid = {r['pid']: r for r in [*parsed, *evidence['empty_process_rows']]}
    return [by_pid[pid] for pid in evidence['process_order']]


@contextlib.contextmanager
def installed(native, action, control, *, receipt_root=None):

    if action not in ACTIONS:
        yield
        return
    root = (Path(receipt_root) if receipt_root is not None else
            new_activity_root(native.project, action) if action in RUNTIME_ACTIONS else
            HERE/'a6/activity_receipts'/action)
    root.mkdir(parents=True, exist_ok=True)
    attempt = uuid.uuid4().hex
    counters = dict(loader_calls=0, snapshot_calls=0)
    scope = {}
    attempts = []
    common = dict(schema='MINRUN_TIME_ALIGNMENT_A7B_ACTIVITY_ADAPTER_RECEIPT_V1', action=action,
        control=control, attempt=attempt, activity_certified=False,
        certification_attempts=attempts, retry_limit=10, retry_interval_seconds=2,
        removal_rule='nameless classified non-filesystem kernel objects only; err/missing type/nameless filesystem or unclassified kinds refuse',
        snapshot_identities_are_digests_only=True, same_uid_scope=scope)
    def receipt(phase, outcome, **fields):
        return exclusive(root/(uuid.uuid4().hex+'.json'), dict(common, utc=now(), phase=phase, outcome=outcome, **fields))
    def certification(function, roots, proxy, process_api, kwargs):


        call = uuid.uuid4().hex
        for number in range(1, 11):
            scope.pop('failure', None)
            census_start = len(scope.get('census_calls', []))
            snapshots = counters['snapshot_calls']
            started = now()
            try:
                result = function(roots, process_api=proxy if process_api is None else process_api, **kwargs)
            except BaseException as exc:
                detail = exception_detail(exc, scope)
                instability = (type(exc) is RuntimeError and str(exc) == CENSUS_INSTABILITY
                    and exc.__cause__ is None and not scope.get('failure')
                    and detail['check'] == 'no_overlap.census_stability')
                retry = instability and number < 10
                record = dict(certification_call=call, attempt_number=number, started_utc=started,
                    completed_utc=now(), outcome='REFUSE', exception=detail,
                    retry=retry, census_calls=scope.get('census_calls', [])[census_start:],
                    snapshot_calls=counters['snapshot_calls']-snapshots)
                attempts.append(record)
                receipt('certification_attempt', 'REFUSE', **{k:v for k,v in record.items() if k!='outcome'})
                if not retry: raise
            else:
                record = dict(certification_call=call, attempt_number=number, started_utc=started,
                    completed_utc=now(), outcome='PASS', exception=None, retry=False,
                    census_calls=scope.get('census_calls', [])[census_start:],
                    snapshot_calls=counters['snapshot_calls']-snapshots)
                attempts.append(record)
                receipt('certification_attempt', 'PASS', activity_certified=True,
                        **{k:v for k,v in record.items() if k!='outcome'})
                return result
            time.sleep(2)

    def certified(function, proxy):
        def overlap(roots=None, *, process_api=None, **kwargs):
            return certification(function, roots, proxy, process_api, kwargs)
        return overlap
    receipt('adapter_entry', 'INSTALLED', **counters)
    patched = []; hosts = []; bridge = None; original_loader = None; original_entry = None; entry_aliases = []; loader_aliases = []
    try:
        bridge = native.af('runtime_bridge')
        original_loader = bridge.frozen_modules
        def loader(*args, **kwargs):
            counters['loader_calls'] += 1
            modules = original_loader(*args, **kwargs)
            host = modules.get('run_bound_forecasts')
            if host is not None and not any(host is m for m, fn, old in hosts):
                function = host.no_overlap
                old = function.__kwdefaults__
                defaults = dict(old)
                api = defaults.get('process_api')
                if api is None:
                    import psutil as api
                defaults['process_api'] = SameUID(api, scope)

                function.__kwdefaults__ = defaults
                hosts.append((host, function, old))
                host.no_overlap = certified(function, defaults['process_api'])
            guard = modules['activity_guard']
            if not any(guard is m for m, old in patched):
                original = guard.parse_lsof_fields
                source = row(guard.__file__, native.sources.bytes(guard.__file__))
                def parse(data):
                    counters['snapshot_calls'] += 1
                    evidence = dict(native_guard=source, snapshot_observed=True, **snapshot_counts(data))
                    if isinstance(data, bytes):
                        evidence.update(snapshot_bytes=len(data), snapshot_sha256=hashlib.sha256(data).hexdigest())
                    outcome = 'REFUSE'; error = None
                    try:
                        if hosts:
                            data = same_uid_snapshot(data, scope['uid'], guard._cannot, evidence, scope)
                        result = adapted_parse(data, original, guard._cannot, evidence)
                        outcome = 'PASS'
                        return result
                    except BaseException as exc:
                        error = str(exc)
                        raise
                    finally:
                        evidence['removed_record_count'] = len(evidence.get('removed_records', []))
                        evidence['dropped_counts_by_kind'] = dict(sorted(Counter(
                            r['type'] for r in evidence.get('removed_records', [])).items()))
                        receipt('lsof_parse', outcome, error=error, **evidence)
                guard.parse_lsof_fields = parse
                patched.append((guard, original))
            return modules
        bridge.frozen_modules = loader
        original_entry = getattr(bridge, 'actual_entry_metadata', None)
        if original_entry is not None:
            @contextlib.contextmanager
            def entry(host):
                direct = host.no_overlap
                function = next(fn for m, fn, old in hosts if m is host)


                host.no_overlap = function
                try:
                    with original_entry(host):
                        clone = host.no_overlap
                        host.no_overlap = certified(clone, clone.__kwdefaults__['process_api'])
                        try: yield
                        finally: host.no_overlap = clone
                finally: host.no_overlap = direct
            bridge.actual_entry_metadata = entry


            wrapper = native.af('forecast_wrapper')
            if wrapper is not bridge and hasattr(wrapper, 'actual_entry_metadata'):
                entry_aliases.append((wrapper, wrapper.actual_entry_metadata))
                wrapper.actual_entry_metadata = entry
                if hasattr(wrapper, 'frozen_modules'):
                    loader_aliases.append((wrapper, wrapper.frozen_modules))
                    wrapper.frozen_modules = loader


        if getattr(bridge, '_MODULES', None) is not None:
            loader()
        yield
    except BaseException as exc:
        receipt('adapter_exit', 'REFUSE', error=str(exc), exception=exception_detail(exc, scope),
                snapshot_observed=bool(counters['snapshot_calls']), **counters)
        raise
    else:
        receipt('adapter_exit', 'PASS', activity_certified=bool(attempts) and attempts[-1]['outcome']=='PASS',
                snapshot_observed=bool(counters['snapshot_calls']), **counters)
    finally:
        if bridge is not None and original_loader is not None: bridge.frozen_modules = original_loader
        if bridge is not None and original_entry is not None: bridge.actual_entry_metadata = original_entry
        for wrapper, old in reversed(entry_aliases): wrapper.actual_entry_metadata = old
        for wrapper, old in reversed(loader_aliases): wrapper.frozen_modules = old
        for host, function, old in reversed(hosts):
            host.no_overlap = function
            function.__kwdefaults__ = old
        for guard, original in reversed(patched): guard.parse_lsof_fields = original
