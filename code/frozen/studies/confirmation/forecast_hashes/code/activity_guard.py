'Detect concurrent forecast calculations from open lock descriptors.'
import os
from pathlib import Path
import subprocess

from common import require


def activity_paths(roots):

    main=Path(roots['main_root']); disk=Path(roots['disk_root'])
    conf=main.parent; code=Path(roots['code_root'])/'code'
    output=Path(roots.get('output_root', conf/'forecast_hashes'))
    return dict(schema='FORECAST_BINDING_READ_ONLY_ACTIVITY_V1',
                lock_mechanism='BSD_flock_open_descriptor_conservative_refusal',
                protected_roots=[str(main/'host_state'),str(disk/'state'),
                                 str(disk/'dly8'),str(disk/'cps8'),str(output)],
                lock_files=[str(disk/'state/.fitting.lock'),
                            str(main/'host_state/.host.lock'),
                            str(main/'host_state/.fitting.lock'),
                            str(main/'host_state/HOST.lock'),
                            str(main/'host_state/.freeze.lock'),
                            str(conf/'lear_horizon/.seal_wrapper.lock')],
                existence_locks=[],
                entry_files=list(roots['wrapper_entries'])+[str(code/'runner.py'),
                    str(code/'rebuild_delayed_features.py'),str(code/'run_comparison_sets.py'),
                    str(main/'cli.py'),str(main/'execution_adapter.py'),
                    str(main/'features_adapter.py'),str(main/'global_input_freeze.py'),
                    str(conf/'lear_horizon/seal_lear_horizon.py'),
                    str(conf/'news_memory/host_chain_SPEC_8.sh'),
                    str(conf/'fit_memory/host_chain_SPEC_7.sh'),
                    str(conf/'storage_limits/host_chain_SPEC_6.sh'),
                    str(conf/'input_definitions/host_chain_SPEC_5.sh'),
                    str(main/'host_chain_20261002.sh'),
                    str(output/'code/run_bound_forecasts.py')])


def _cannot(message):
    raise RuntimeError('Cannot certify host fit/rebuild non-overlap: '+message)


def _visible_file(f):
    if f.get('fd')=='err' or not f.get('type') or not f.get('name'):
        _cannot('incomplete descriptor visibility')
    name=f['name']; kind=f['type']
    known={'REG','DIR','FIFO','CHR','BLK','LINK','IPv4','IPv6','unix','PIPE','KQUEUE',
           'PSXSEM','PSXSHM','systm','FPOLICY','NPOLICY','NEXUS','CHAN','FSEVENTS',
           'VREG','VDIR','VCHR','VBLK','VFIFO','VSOCK','SOCK','SMT','SHM','SEM','DEL'}
    if kind not in known:
        _cannot('unsupported descriptor type')
    if kind.lower() in {'unknown','?'} or any(s in name.lower() for s in
        ('permission denied','no more information','cannot read','can\'t read','(readlink:','(stat:')):
        _cannot('inaccessible descriptor metadata')
    filesystem=kind in {'REG','DIR','FIFO','CHR','BLK','LINK'} or f['fd'] in {'cwd','txt','mem'}
    if filesystem and not name.startswith('/'):
        _cannot('unavailable filesystem name')

    return name.startswith('/')


def parse_lsof_fields(data):

    if not isinstance(data,bytes) or not data or not data.endswith(b'\x00\n'):
        _cannot('missing/truncated lsof field output')
    processes=[]; process=None; record=None
    for raw in data.split(b'\x00'):
        raw=raw.lstrip(b'\n')
        if not raw:
            continue
        key=chr(raw[0])
        try:
            value=raw[1:].decode('utf-8',errors='strict')
        except UnicodeError:
            _cannot('undecodable lsof metadata')
        if key=='p':
            if not value.isdecimal() or int(value)<=0:
                _cannot('invalid lsof PID')
            process=dict(pid=int(value),uid=None,files=[]); processes.append(process); record=None
        elif process is None:
            _cannot('lsof field outside process')
        elif key=='f':
            if not value or value=='err':
                _cannot('inaccessible lsof descriptor')
            record=dict(fd=value,name=None,type=None,access=None,lock=None)
            process['files'].append(record)
        elif record is None:
            if key=='u':
                if not value.isdecimal() or process['uid'] is not None:
                    _cannot('missing/duplicate lsof UID')
                process['uid']=int(value)
            elif key!='c':
                _cannot('unexpected lsof process field')
        elif key in {'n','t','a','l'}:
            target=dict(n='name',t='type',a='access',l='lock')[key]
            if record[target] is not None:
                _cannot('duplicate lsof file field')
            record[target]=value
        else:
            _cannot('unexpected lsof file field')
    if len({p['pid'] for p in processes})!=len(processes):
        _cannot('duplicate lsof process')
    for p in processes:
        if p['uid'] is None or not p['files']:
            _cannot('incomplete lsof process')
        for f in p['files']:
            _visible_file(f)
    return processes


def read_lsof_snapshot(*, command=None, runner=None):

    command=command or ['/usr/sbin/lsof','-nP','+w','-F0pcufaltn']
    try:
        result=(runner or subprocess.run)(command,stdout=subprocess.PIPE,
                    stderr=subprocess.PIPE,check=False,timeout=20)
    except (OSError,subprocess.SubprocessError) as exc:
        raise RuntimeError('Cannot certify host fit/rebuild non-overlap: lsof unavailable') from exc
    if result.returncode!=0 or result.stderr:
        _cannot('lsof incomplete/permission/tool failure')
    return parse_lsof_fields(result.stdout)


def _canonical(path):

    if not isinstance(path,str) or not path.startswith('/') or '\x00' in path:
        _cannot('unverified absolute metadata path')
    return os.path.realpath(path)


def refuse_metadata(contract,records,*,own_pid=None):

    own_pid=os.getpid() if own_pid is None else own_pid
    protected=[_canonical(p) for p in contract['protected_roots']]
    locks={_canonical(p) for p in contract['lock_files']}
    entries={_canonical(p) for p in contract['entry_files']}
    for process in records:
        if process['pid']==own_pid:
            continue
        for f in process['files']:
            if not _visible_file(f):
                continue
            raw=f['name']

            if raw.endswith(' (deleted)'):
                raw=raw[:-10]
            path=_canonical(raw)
            busy=(path in locks or path in entries or
                  any(path==root or path.startswith(root+os.sep) for root in protected))
            require(not busy,'inference_design host-order refusal: another fit/rebuild is active')


def process_entry(argv,cwd,contract,launch_tail):

    cwd=_canonical(cwd)
    if not all(isinstance(t,str) and '\x00' not in t for t in argv):
        _cannot('invalid process argv')
    entries={_canonical(p) for p in contract['entry_files']}
    normalised={t:os.path.realpath(t if os.path.isabs(t) else os.path.join(cwd,t)) for t in argv}
    command=launch_tail(argv)
    if not command:
        return False
    if normalised[command[0]] in entries:
        return True
    executable=Path(normalised[command[0]]).name.lower(); tail=list(command[1:])
    if executable in {'sh','bash','zsh'}:
        while tail:
            token=tail.pop(0)
            if token=='--':
                return bool(tail and normalised[tail[0]] in entries)
            if not token.startswith(('-','+')):
                return normalised[token] in entries
            if token.startswith('--'):
                _cannot('unresolved shell long option')
            if 'c' in token[1:]:
                return False
            if token in {'-o','+o','-O','+O'}:
                if not tail:_cannot('missing shell option operand')
                tail.pop(0);continue
            if not token[1:] or not set(token[1:])<=set('abefhilmnprstuvxBCEHPT'):
                _cannot('unresolved shell entry')
        return False
    if not executable.startswith('python'):
        return False
    no_value=set('bBdEiIOPqRsStuvx')
    while tail:
        token=tail.pop(0)
        if token=='--':
            return bool(tail and normalised[tail[0]] in entries)
        if token=='-' or token in {'--help','--help-env','--help-xoptions','--help-all','--version'}:
            return False
        if not token.startswith('-'):
            return normalised[token] in entries
        if token=='--check-hash-based-pycs':
            if not tail or tail.pop(0) not in {'default','always','never'}:
                _cannot('unresolved Python option')
            continue
        if token.startswith('--'):
            _cannot('unresolved Python entry')
        for j,flag in enumerate(token[1:]):
            if flag in no_value:
                continue
            if flag in 'h?V':
                return False
            if flag in 'cm':
                operand=token[j+2:] or (tail.pop(0) if tail else None)
                if operand is None:
                    _cannot('missing Python interface operand')
                if flag=='c':
                    return False
                if not all(part.isidentifier() for part in operand.split('.')):
                    _cannot('unresolved module name')
                module=os.path.join(cwd,*operand.split('.'))
                if os.path.realpath(module+'.py') in entries or os.path.realpath(module+'/__main__.py') in entries:
                    return True
                if operand.rsplit('.',1)[-1] in {Path(p).stem for p in entries}:
                    _cannot('reviewed wrapper module provenance')
                return False
            if flag in 'WX':
                if not token[j+2:]:
                    if not tail:
                        _cannot('missing Python option operand')
                    tail.pop(0)
                break
            _cannot('unresolved Python entry')
    return False
