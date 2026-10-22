'List forecasting processes belonging to the current user.'
import os


def exception_detail(exc, scope=None):

    chain = []
    current = exc
    while current is not None and all(current is not e for e in chain):
        chain.append(current)
        current = current.__cause__ or (None if current.__suppress_context__ else current.__context__)
    underlying = chain[-1]
    detail = dict(type=type(underlying).__name__, message=str(underlying),
                  outer_type=type(exc).__name__, outer_message=str(exc),
                  pid=getattr(underlying, 'pid', None), process_name=getattr(underlying, 'name', None),
                  check=None)
    if scope and scope.get('failure'):
        detail.update(scope['failure'])
    else:

        for error in chain:
            tb = error.__traceback__
            while tb:
                frame = tb.tb_frame
                if frame.f_code.co_name in ('no_overlap', 'refuse_metadata', '_visible_file', '_cannot'):
                    detail['check'] = frame.f_code.co_name + ':' + str(tb.tb_lineno)
                    process = frame.f_locals.get('process')
                    if isinstance(process, dict):
                        detail['pid'] = process.get('pid', detail['pid'])
                    elif process is not None:
                        detail['pid'] = getattr(process, 'pid', detail['pid'])
                tb = tb.tb_next
        if scope and detail['pid'] in scope.get('names', {}):
            detail['process_name'] = scope['names'][detail['pid']]
    if 'process census changed' in detail['message']:
        detail.update(check='no_overlap.census_stability', pid=None, process_name=None)
    elif 'incomplete all-UID lsof coverage' in detail['message']:
        detail.update(check='no_overlap.same_uid_lsof_coverage', pid=None, process_name=None)
    return detail


class ProcessView:
    def __init__(self, process, api):
        self.process, self.api = process, api
        self.pid = process.pid

    def __getattr__(self, name):
        value = getattr(self.process, name)
        if not callable(value):
            return value
        def call(*args, **kwargs):
            try:
                result = value(*args, **kwargs)
                if name == 'name': self.api.scope['names'][self.pid] = result
                return result
            except BaseException as exc:
                if not isinstance(exc, self.api.original.NoSuchProcess):
                    self.api.failure(exc, self.process, self.api.phase + '.' + name)
                raise
        return call

    def parents(self):
        try: parents = self.process.parents()
        except BaseException as exc:
            self.api.failure(exc, self.process, 'ancestors.parents')
            raise
        return self.api.select(parents, 'ancestors')


class SameUID:

    def __init__(self, original, scope, uid=None):
        self.original, self.scope = original, scope
        self.uid = os.getuid() if uid is None else uid
        self.phase = 'process'
        scope.update(uid=self.uid, census_calls=[], ancestor_calls=[], names={},
                     limitation='Root and other-UID/system processes are not inspected.')

    def __getattr__(self, name):
        return getattr(self.original, name)

    def failure(self, exc, process, check):

        name = getattr(exc, 'name', None) or self.scope['names'].get(process.pid)
        name_error = None
        if name is None and not check.endswith('.uids'):
            try: name = process.name()
            except BaseException as error: name_error = type(error).__name__ + ': ' + str(error)
        self.scope['failure'] = dict(check=check, pid=getattr(exc, 'pid', None) or process.pid,
            process_name=name, name_unavailable=name_error)

    def select(self, processes, phase):
        record = dict(phase=phase, excluded_other_uid=0, included_same_uid=0, vanished=0)
        self.scope['ancestor_calls' if phase == 'ancestors' else 'census_calls'].append(record)
        selected = []
        for process in processes:
            try:

                owner = process.uids().real
            except self.original.NoSuchProcess:
                record['vanished'] += 1
                continue
            except BaseException as exc:
                self.failure(exc, process, phase + '.uids')
                raise
            if owner != self.uid:
                record['excluded_other_uid'] += 1
                continue
            record['included_same_uid'] += 1
            selected.append(ProcessView(process, self))
        return selected

    def process_iter(self, *args, **kwargs):
        self.phase = 'census' if len(self.scope['census_calls']) % 2 == 0 else 'after_census'
        return iter(self.select(self.original.process_iter(*args, **kwargs), self.phase))

    def Process(self, *args, **kwargs):
        return ProcessView(self.original.Process(*args, **kwargs), self)


def same_uid_snapshot(data, uid, cannot, evidence, scope=None):

    if not isinstance(data, bytes) or not data or not data.endswith(b'\0\n'):
        cannot('missing/truncated lsof field output')
    groups = []
    for raw in data.split(b'\0')[:-1]:
        token = raw.lstrip(b'\n')
        if token.startswith(b'p'): groups.append([])
        if not groups:
            if token: cannot('lsof field outside process')
            continue
        groups[-1].append(raw)
    kept = []; seen = set(); excluded = 0
    for group in groups:
        header = []
        for raw in group:
            token = raw.lstrip(b'\n')
            if token.startswith(b'f'): break
            if token: header.append(token)
        pid = header[0][1:]
        owners = [t[1:] for t in header[1:] if t.startswith(b'u')]
        if not pid.isdigit() or int(pid) <= 0 or int(pid) in seen: cannot('invalid/duplicate lsof PID')
        seen.add(int(pid))
        if len(owners) != 1 or not owners[0].isdigit(): cannot('missing/duplicate lsof UID')
        if any(t[:1] not in (b'p', b'u', b'c') for t in header): cannot('unexpected lsof process field')
        if int(owners[0]) == uid:
            kept.extend(group)
            if scope is not None:
                commands = [t[1:] for t in header[1:] if t.startswith(b'c')]
                if commands:
                    try: scope['names'][int(pid)] = commands[-1].decode('utf-8', errors='strict')
                    except UnicodeError: cannot('undecodable lsof metadata')
        else: excluded += 1
    evidence['excluded_other_uid_lsof_processes'] = excluded
    if scope is not None: scope['excluded_other_uid_lsof_processes'] = excluded
    if not kept: cannot('no same-UID lsof process visibility')
    return b'\0'.join(kept) + b'\0\n'
