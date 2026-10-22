
'Run the seven scoring steps in their specified order.'
import argparse
from datetime import datetime, timezone
import hashlib
import importlib.util
import importlib.machinery
import json
from pathlib import Path
import subprocess
import sys

HERE = Path(__file__).resolve().parent
STAGES = ('original-and-capture', 'r2-score', 'readers', 'ap-numbers',
          'rd-joint', 'sensitivity_export', 'export')
READER_ORDER = ('primary_tests', 'sensitivity_tests', 'robustness_tests', 'batch-parity', 'authorized-optional', 'sensitivity_tests', 'robustness_tests')


class DriverStop(RuntimeError):
    pass


def pending(value, trail='$'):

    from forecast_check_helpers import unresolved_values
    return [path for path, _ in unresolved_values(value, trail)]


def read_control(path):
    value = json.loads(Path(path).read_bytes())
    unresolved = pending(value)
    if unresolved:
        raise DriverStop('PENDING_CONTROL: ' + ', '.join(unresolved))
    template = json.loads((HERE/'CONTROL.template.json').read_bytes())
    def shape(expected, actual, trail='$'):
        if isinstance(expected, dict):
            if not isinstance(actual, dict) or set(expected)-set(actual):
                raise DriverStop('MISSING_CONTROL_FIELD: '+trail)
            for key in expected:
                shape(expected[key], actual[key], trail+'.'+key)
    shape(template, value)
    if value['schema'] != 'MINRUN_CONTROL_V1':
        raise DriverStop('WRONG_CONTROL_SCHEMA')
    return value


def support():

    manifest = json.loads((HERE/'BUILD_IDENTITY.json').read_bytes())
    for filename,row in manifest['files'].items():
        data=(HERE/filename).read_bytes()
        if len(data)!=row['bytes'] or hashlib.sha256(data).hexdigest()!=row['sha256']:
            raise DriverStop('K1 driver byte drift: '+filename)
    for name in ('source_bytes', 'adapters'):
        path = HERE/(name+'.py')
        data = path.read_bytes()
        row = manifest['files'][path.name]
        if len(data) != row['bytes'] or hashlib.sha256(data).hexdigest() != row['sha256']:
            raise DriverStop('K1 driver support byte drift: '+path.name)
        module = importlib.util.module_from_spec(importlib.util.spec_from_file_location(name, path))
        sys.modules[name] = module
        exec(compile(data, str(path), 'exec', dont_inherit=True), vars(module))
    snapshots={str(HERE/name):(HERE/name).read_bytes() for name in manifest['files'] if name.endswith('.py')}
    previous=importlib.machinery.SourceFileLoader.get_code
    def driver_code(loader,name):
        path=str(Path(loader.path))
        if path in snapshots:return compile(snapshots[path],path,'exec',dont_inherit=True)
        return previous(loader,name)
    importlib.machinery.SourceFileLoader.get_code=driver_code
    return sys.modules['source_bytes'], sys.modules['adapters']


def utc(value):
    stamp = datetime.fromisoformat(value.replace('Z', '+00:00'))
    if stamp.utcoffset().total_seconds() != 0:
        raise DriverStop('K3 UTC required')
    return stamp


def execution_gate(control, B):
    release = B.document(control['release'])
    B.require(release['schema'] == 'MINRUN_SCORE_RELEASE_V1'
        and release['control_sha256_without_release'] == hashlib.sha256(json.dumps(
            {k: v for k, v in control.items() if k not in ('release', '_control_path')},
            sort_keys=True, separators=(',', ':')).encode()).hexdigest()
        and release['driver_build'] == control['driver_build']
        and release['permit'] == control['original']['permit']
        and release['capture_clock_writer'] == B.identity(HERE/'backend.py')
        and release['capture_clock_authorized'] is True, 'K2 actual release identity/permit/clock writer')
    t5 = B.document(control['t5'])


    B.require(t5['state'] == 'T5_VERIFIED_AND_BOUND' and len(t5['tsa_verifications']) == 2
        and all(x['offline_signature_verified'] and x['manifest_imprint_verified']
                for x in t5['tsa_verifications']), 'K3 actual dual-TSA/T5 binding required')
    for item in t5['metadata_files']:
        B.checked(item)


    for row in t5['tsa_verifications']:
        B.checked(row['verification_receipt'])
    B.require(utc(control['corrected_eligibility']['verified_seal_utc']) < utc(t5['utc']),
              'K6 verified corrected seal must precede T5')


    for item in control['corrected_eligibility']['authority_files']:
        B.checked(item)
    quiet = B.document(control['quiet_host'])
    B.require(quiet['kind'] == 'PROCEDURAL_QUIET_HOST' and quiet['unknown_activity'] is False
        and quiet['concurrent_activity'] is False and quiet['single_direct_terminal'] is True
        and quiet['dispositions'] and all(x['terminal'] is True for x in quiet['dispositions']),
        'K3 unresolved actual host activity; never claim HOST_PASS')
    B.require(utc(t5['utc']) < datetime.now(timezone.utc), 'K3 future T5')
    B.require(control['interpreter']['path'] == sys.executable
        and B.identity(sys.executable) == control['interpreter'], 'K1 interpreter identity')
    B.require(B.identity(HERE/'BUILD_IDENTITY.json') == control['driver_build'], 'K1 driver build identity')
    return dict(release=control['release'], t5=control['t5'], quiet_host=control['quiet_host'])


def pipeline(control, backend, B, A):

    backend.preflight()
    out = Path(control['attempt_directory'])
    B.require(not out.exists(), 'K3 attempt exists; never retry successful original score')
    out.mkdir(parents=True, exist_ok=False)
    evidence = []
    arm = backend.arm(out)
    A.exclusive_json(out/'ARMED.json', arm)


    status = backend.score(out)
    finish = datetime.now(timezone.utc).isoformat()
    B.require(status == 0, 'K3 original score failed; no capture/R2/readers')
    capture = backend.capture_after_exit(out, arm, finish)
    B.require(capture['source_values_decoded'] is False
        and capture['pending_is_negative'] is False, 'K3 invalid outcome-blind capture')
    evidence.append(A.exclusive_json(out/'01_CAPTURE_COMPLETE.json', capture))
    r2 = backend.r2_after_capture(capture)
    evidence.append(A.exclusive_json(out/'02_R2_COMPLETE.json', r2))
    backend.certificate(capture, r2)
    readers = backend.readers(READER_ORDER)
    evidence.append(A.exclusive_json(out/'03_READERS_COMPLETE.json', readers))
    numeric = backend.ap_numbers(readers)
    attachment = A.original_attachment(numeric['original_news_214'], backend.original_receipt)
    evidence.append(A.exclusive_json(out/'04_AP_COMPLETE.json', numeric))
    rd, eligibility = backend.rd_and_independent_eligibility(numeric)
    A.full_census(numeric, rd)
    evidence.append(A.exclusive_json(out/'05_RD_COMPLETE.json', dict(rd=rd, eligibility=eligibility)))
    sens = backend.sens35_from_detached_ap(numeric)
    evidence.append(A.exclusive_json(out/'06_SENS_COMPLETE.json', sens))
    exported = backend.export(numeric, rd, eligibility, sens, attachment)
    evidence.append(A.exclusive_json(out/'07_EXPORT_COMPLETE.json', exported))
    final = dict(schema='MINRUN_ATTEMPT_RECEIPT_V1', stages=list(STAGES), evidence=evidence,
                 synthetic_only=backend.synthetic_only, state='COMPLETE')
    A.exclusive_json(out/'ATTEMPT_RECEIPT.json', final)
    return final


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('action', choices=('check-control', 'run', 'resume-check', 'resume'))
    parser.add_argument('--control', required=True, type=Path)
    args = parser.parse_args(argv)
    try:
        control = read_control(args.control)
        control['_control_path'] = str(args.control)
        B, A = support()
        if args.action not in ('resume-check','resume'):execution_gate(control, B)
        sources = B.Sources(control['sources'])
        selected = json.loads((HERE/'RUNTIME_SOURCES.json').read_bytes())
        required = {(str(Path(control['project'])/r['logical_path']), r['sha256'], r['bytes']) for r in selected['files']}
        B.require(required <= {(r['logical_path'],r['sha256'], r['bytes']) for r in control['sources']},
                  'K1 selected exact kernel closure omitted')

        adapter = A.NativeAdapters(control, sources)
        from contextlib import nullcontext
        from forecast_resource_limits import installed_score
        with sources.imports(), (installed_score(sources, control['project']) if args.action in ('run','resume') else nullcontext()):
            if args.action in ('resume-check','resume'):
                from resume_driver import execute
                result=execute(control,sources,adapter,run=args.action=='resume')
                print(json.dumps(result))
                return 0
            adapter.preflight()
            if args.action == 'run':
                try: pipeline(control, adapter, B, A)
                finally: adapter.close()
        return 0
    except (DriverStop, RuntimeError, KeyError, ValueError) as exc:
        print('BLOCKED: '+str(exc), file=sys.stderr)
        return 2


if __name__ == '__main__':
    raise SystemExit(main())
