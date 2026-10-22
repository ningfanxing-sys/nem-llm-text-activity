'Check scoring callback records, observation times and input hashes.'
from __future__ import annotations

from contextlib import contextmanager
from copy import deepcopy
from datetime import datetime, timezone
import importlib.util
import math
from pathlib import Path
import re
import sys


_AP = Path(__file__).resolve().parents[2]
_PROJECT = _AP.parents[2]
_PACKAGE = _PROJECT / 'studies/batch_estimation/scoring_callback'
_FIXED = datetime(2026, 10, 6, 1, tzinfo=timezone.utc)
_PRODUCERS = {'primary_tests', 'sensitivity_tests', 'robustness_tests', 'batch_estimation', 'label_scoring', 'KCX', 'PC',
              'PCX_extension', 'inference', 'FILL3f'}
_ARGV = ['/usr/bin/caffeinate', '-i',
         '.venv/bin/python',
         str(_PROJECT / 'studies/confirmation/execution/cli.py'), 'score']
_EMBARGO = {'sole_source': True, 'no_postscore_launch_since_t5': True,
            'all_alternative_outputs_declared': True}
_FORBIDDEN = {'host_state', 'private', 'scored', 'scores', 'scoring',
              'predictions', 'prediction', 'sealed', 'run', 'run_null_ext',
              'evaluation', 'models', '.git', '.llm_client', '.aws'}
_IDENTITY = {'path', 'bytes', 'sha256'}


def _identity_shape(item, P, *, full=False):
    P.require(isinstance(item, dict) and {'path', 'sha256'} <= set(item)
              and set(item) <= _IDENTITY, 'scoring_callback metadata identity required')
    P.require(not full or set(item) == _IDENTITY, 'scoring_callback full identity required')
    value = item['path']
    P.require(isinstance(value, str) and Path(value).is_absolute()
              and str(Path(value)) == value and '..' not in Path(value).parts,
              'scoring_callback canonical absolute identity path required')
    P.require(isinstance(item['sha256'], str)
              and re.fullmatch(r'[0-9a-f]{64}', item['sha256']) is not None,
              'scoring_callback SHA-256 required')
    if 'bytes' in item:
        P.require(type(item['bytes']) is int and item['bytes'] >= 0,
                  'scoring_callback identity byte count required')
    return item


def _same_identity(declared, actual, P):
    _identity_shape(declared, P)
    _identity_shape(actual, P, full=True)
    return all(declared[k] == actual[k] for k in declared)


def _metadata_file(value, P):
    p = Path(value)
    P.require(p.is_absolute() and str(p) == str(p.resolve())
              and not any(a.is_symlink() for a in [p, *p.parents]),
              'scoring_callback metadata symlink/noncanonical path refused')
    if p.is_relative_to(_PROJECT):
        relative = p.relative_to(_PROJECT)
    elif p.is_relative_to(Path('/private/tmp')):


        relative = p.relative_to(Path('/private/tmp'))
    else:
        P.require(False, 'scoring_callback project/synthetic metadata input_checks')
    P.require(not set(relative.parts) & _FORBIDDEN
              and p.suffix in {'.py', '.md', '.json', '.txt', '.sha256', '.tsr', '.sh'}
              and not p.name.startswith(('.env', 'OPENED_PATHS'))
              and p.name not in {'auth.json', 'POSTSCORE_HOST_LOG.jsonl',
                                 'POSTSCORE_TURN_STATE.json'},
              'scoring_callback metadata-only read input_checks')
    P.require(p.is_file() and p.stat().st_size < 16_000_000,
              'scoring_callback missing/oversized metadata')
    return p


def _actual_identity(value, P):
    p = _metadata_file(value, P)
    reference_snapshot = p.stat()
    digest = P.sha256(p)
    after = p.stat()
    P.require((reference_snapshot.st_dev, reference_snapshot.st_ino, reference_snapshot.st_size, reference_snapshot.st_mtime_ns) ==
              (after.st_dev, after.st_ino, after.st_size, after.st_mtime_ns),
              'scoring_callback metadata changed during identity check')
    return dict(path=str(p), bytes=after.st_size, sha256=digest)


def _read_identity(item, P):
    _identity_shape(item, P)
    actual = _actual_identity(item['path'], P)
    P.require(_same_identity(item, actual, P), 'scoring_callback metadata identity drift')
    P.require(Path(actual['path']).suffix == '.json', 'scoring_callback JSON metadata required')
    payload = P.strict_json(actual['path'])
    P.require(isinstance(payload, dict), 'scoring_callback metadata object required')
    P.require(_actual_identity(actual['path'], P) == actual,
              'scoring_callback metadata changed while reading')
    return payload, actual


@contextmanager
def _callback_modules(P):

    names = ('score_callback', 'freeze_scoring_callback')
    previous = {n: sys.modules[n] for n in names if n in sys.modules}
    before_path, before_bytecode = list(sys.path), sys.dont_write_bytecode
    try:
        sys.dont_write_bytecode = True
        for name in names:
            sys.modules.pop(name, None)
        for name in names:
            path = _metadata_file(str(_PACKAGE / (name + '.py')), P)
            spec = importlib.util.spec_from_file_location(name, path)
            P.require(spec is not None and spec.loader is not None,
                      'scoring_callback source import required')
            module = importlib.util.module_from_spec(spec)
            sys.modules[name] = module
            spec.loader.exec_module(module)
        yield sys.modules['score_callback'], sys.modules['freeze_scoring_callback']
    finally:
        for name in names:
            sys.modules.pop(name, None)
        sys.modules.update(previous)
        sys.path[:] = before_path
        sys.dont_write_bytecode = before_bytecode


def verified_callback_package(clock, P):

    with _callback_modules(P) as (C, F):
        freeze = C.verify_package()
        P.require(freeze.get('schema') == 'SCORECB_CODE_FREEZE_V1'
                  and freeze.get('production_payload_reads') == 0
                  and freeze.get('production_commands_run') == []
                  and freeze.get('scoring_argv_unchanged') is True,
                  'scoring_callback accepted metadata freeze required')
        plan = C.validate_plan(C.PACKAGE / 'SOURCE_PLAN.json')
        plan_id = C.identity(C.PACKAGE / 'SOURCE_PLAN.json')
        freeze_id = C.identity(C.PACKAGE / 'CODE_FREEZE.json')
        P.require(freeze['plan'] == plan_id and clock['plan'] == plan_id,
                  'scoring_callback frozen plan association drift')
        receipt_path = C.checked(freeze['test_receipt'])
        inside_validation = (receipt_path.parent.parent == C.PACKAGE / 'validation'
                             and receipt_path.name == 'TEST_RESULTS.json')
        P.require((receipt_path.parent == C.PACKAGE
                   and receipt_path.name.startswith('TEST_RESULTS')
                   and receipt_path.suffix == '.json') or inside_validation,
                  'scoring_callback passing test receipt must belong to the package')
        tests = C.read(receipt_path)
        P.require(tests.get('schema') == 'SCORECB_SYNTHETIC_TEST_RECEIPT_V1'
                  and tests.get('state') == 'PASS'
                  and type(tests.get('suite_runs')) is int and tests['suite_runs'] == 1
                  and type(tests.get('tests_run')) is int and tests['tests_run'] > 0
                  and all(type(tests.get(k)) is int and tests[k] == 0
                          for k in ('failures', 'errors', 'skipped')),
                  'scoring_callback complete passing synthetic receipt required')
        source = F.tested_hashes(C.PACKAGE)
        P.require(tests.get('source_sha256') == source,
                  'scoring_callback passing test source identity drift')
        resource = tests['resources']
        P.require(all(type(resource.get(k)) is int and resource[k] == v
                      for k, v in [('nice', 20), ('test_processes', 1),
                                   ('production_payload_reads', 0)]),
                  'scoring_callback synthetic process/read gates required')
        free, scratch = (resource.get('minimum_memory_free_percent'),
                         resource.get('maximum_scratch_bytes'))
        P.require(type(free) in (int, float) and math.isfinite(free) and free >= 25
                  and type(scratch) in (int, float) and math.isfinite(scratch)
                  and 0 <= scratch < 1_000_000_000,
                  'scoring_callback synthetic resource gates required')
        acceptance = C.read(C.checked(freeze['review_acceptance']))


        review_path = _metadata_file(str(C.checked(freeze['review'])), P)
        P.require(review_path.parent == C.PACKAGE
                  and review_path.name.startswith('REVIEW_') and review_path.suffix == '.md'
                  and freeze['review'] == C.identity(review_path)
                  and freeze['review_acceptance'] == C.identity(C.PACKAGE / 'REVIEW_ACCEPTANCE.json')
                  and acceptance.get('state') == 'SCORECB_REVIEW_ACCEPTED'
                  and acceptance.get('source_verified') is True
                  and isinstance(acceptance.get('recorded_by'), str)
                  and bool(acceptance['recorded_by'].strip())
                  and acceptance.get('review') == freeze['review']
                  and acceptance.get('test_receipt') == freeze['test_receipt']
                  and acceptance.get('plan') == plan_id
                  and acceptance.get('source_sha256') == source,
                  'scoring_callback actual reviewed acceptance required')
        P.require(C.utc(acceptance['recorded_utc']) <= C.utc(freeze['frozen_utc']) <= C.now(),
                  'scoring_callback review/freeze chronology required')
        t5_id, t5_utc = C.verify_t5(plan, freeze)
        return deepcopy(dict(plan=plan, freeze=freeze, plan_identity=plan_id,
                             freeze_identity=freeze_id, t5_identity=t5_id,
                             t5_utc=t5_utc, score_argv=C.expected_score_argv()))


def callback_observation(raw, official_score, P):

    callback = raw.get('callback_capture')
    P.require(isinstance(callback, dict)
              and set(callback) == {'clock_association', 'capture_receipt'},
              'scoring_callback callback clock and capture identities required')
    clock, clock_id = _read_identity(callback['clock_association'], P)
    capture, capture_id = _read_identity(callback['capture_receipt'], P)
    P.require(set(clock) == {'schema', 'state', 'source_verified', 'conf_score_receipt',
                            'score_complete_utc', 'host_log', 'turn_state', 'producer_outputs',
                            'initial_inputs', 't5_binding', 'armed', 'plan', 'completion_evidence',
                            'callback_ready_utc', 'retrospective_reconstruction_authorised'}
              and clock.get('schema') == 'SCORECB_POSTSCORE_CLOCK_ASSOCIATION_V1'
              and clock.get('state') == 'POSTSCORE_CLOCK_ASSOCIATION_VERIFIED'
              and clock.get('source_verified') is True
              and clock.get('retrospective_reconstruction_authorised') is False,
              'scoring_callback actual nonretrospective clock required')
    external = verified_callback_package(clock, P)
    plan = external['plan']
    P.require(plan.get('schema') == 'SCORECB_SOURCE_PLAN_V1'
              and plan.get('source_reviewed') is True
              and plan.get('launch_embargo') == _EMBARGO
              and plan.get('initial_inputs_reviewed') is True
              and plan.get('fixed_cutoff_utc') == '2026-10-06T01:00:00Z'
              and external['score_argv'] == plan['score_argv'] == _ARGV,
              'scoring_callback specified reviewed plan required')
    output = Path(plan['output_dir'])
    P.require(clock_id['path'] == str(output / 'POSTSCORE_CLOCK_ASSOCIATION.json')
              and capture_id['path'] == str(output / 'CUTOFF_SNAPSHOT.json')
              and clock['armed']['path'] == str(output / 'ARMED.json'),
              'scoring_callback exact callback output association required')
    armed, _ = _read_identity(clock['armed'], P)
    freeze, freeze_id = _read_identity(armed['callback_freeze'], P)
    P.require(freeze == external['freeze'] and freeze_id == external['freeze_identity']
              and freeze.get('schema') == 'SCORECB_CODE_FREEZE_V1'
              and freeze.get('state') == 'SCORECB_FROZEN_FOR_SOURCE'
              and freeze['plan'] == external['plan_identity'],
              'scoring_callback real callback freeze association drift')
    P.require(set(armed) == {'schema', 'state', 'armed_utc', 't5_binding', 'plan',
                            'callback_freeze', 'score_argv', 'score_receipt_absent',
                            'no_postscore_launches_confirmed'}
              and armed.get('schema') == 'SCORECB_ARMED_V1'
              and armed.get('state') == 'ARMED_AFTER_T5_BEFORE_SCORE'
              and armed.get('score_receipt_absent') is True
              and armed.get('no_postscore_launches_confirmed') is True
              and armed['score_argv'] == _ARGV
              and clock['plan'] == armed['plan'] == external['plan_identity']
              and clock['t5_binding'] == armed['t5_binding'] == external['t5_identity'],
              'scoring_callback real pre-score arming chain required')
    evidence = clock['completion_evidence']
    P.require(isinstance(evidence, dict)
              and set(evidence) == {'kind', 'argv', 'exit_status', 'exit_observed_utc',
                                   'no_postscore_launches_confirmed', 'receipt_contents_decoded'}
              and evidence.get('kind') == 'SOURCE_OBSERVED_SPECIFIED_COMMAND_EXIT'
              and evidence.get('argv') == _ARGV
              and type(evidence.get('exit_status')) is int and evidence['exit_status'] == 0
              and evidence.get('no_postscore_launches_confirmed') is True
              and evidence.get('receipt_contents_decoded') is False,
              'scoring_callback actual successful specified command exit required')
    receipt = _identity_shape(clock['conf_score_receipt'], P, full=True)
    P.require(receipt['bytes'] > 0 and receipt['path'] == plan['score_receipt_path']
              and _same_identity(official_score['score_receipt'], receipt, P),
              'scoring_callback independently verified official score receipt association')
    P.require(receipt['bytes'] == Path(official_score['score_receipt']['path']).stat().st_size,
              'scoring_callback official score receipt byte count mismatch')
    P.require(set(capture) == {'schema', 'state', 'cutoff_utc', 'observed_utc',
                              'capture_lateness_seconds', 'late_score_cutoff', 'clock_association',
                              'producer_states', 'files', 'pending_is_negative', 'source_values_decoded',
                              'native_V2_RS8_constructor_owner'}
              and capture.get('schema') == 'A8_CUTOFF_IDENTITIES_V1'
              and capture.get('state') == 'OUTCOME_BLIND_CUTOFF_SNAPSHOT'
              and capture.get('clock_association') == clock_id
              and capture.get('late_score_cutoff') is True
              and capture.get('pending_is_negative') is False
              and capture.get('source_values_decoded') is False
              and capture.get('native_V2_RS8_constructor_owner') ==
                  'inference/source; use these exact identities and a fresh output',
              'scoring_callback original frozen capture required')
    finish, ready, observed = (P.utc(clock['score_complete_utc']),
                               P.utc(clock['callback_ready_utc']), P.utc(capture['observed_utc']))
    P.require(P.utc(freeze['frozen_utc']) <= external['t5_utc']
              <= P.utc(armed['armed_utc']) <= finish <= ready <= observed
              and finish > _FIXED and P.utc(evidence['exit_observed_utc']) == finish
              and P.utc(raw['fill_clock']['score_utc']) == finish,
              'scoring_callback real freeze/T5/arming/completion/capture chronology required')
    fill_clock = deepcopy(raw['fill_clock'])
    fill_clock['filled_utc'] = capture['observed_utc']
    cutoff = P.fill_cutoff(fill_clock)
    P.require(P.utc(capture['cutoff_utc']) == cutoff == max(finish, _FIXED),
              'scoring_callback original frozen AP cutoff association required')
    lateness = (observed - cutoff).total_seconds()
    P.require(type(capture['capture_lateness_seconds']) in (int, float)
              and capture['capture_lateness_seconds'] == lateness and lateness >= 0,
              'scoring_callback exact disclosed capture lateness required')
    P.require(clock['host_log'] == plan['host_log'] and clock['turn_state'] == plan['turn_state']
              and clock['producer_outputs'] == plan['producer_outputs']
              and set(plan['producer_outputs']) == _PRODUCERS
              and clock['initial_inputs'] == plan['initial_inputs']
              and isinstance(plan['initial_inputs'], list) and bool(plan['initial_inputs']),
              'scoring_callback frozen metadata/producer inventory drift')
    P.require(capture['producer_states'] ==
              {name: dict(state='PENDING_AT_CUTOFF', files=[]) for name in _PRODUCERS},
              'scoring_callback late capture must precede every producer')
    initial = plan['initial_inputs']
    P.require(len({i['path'] for i in initial}) == len(initial)
              and capture['files'] == initial, 'scoring_callback exact initial metadata capture required')
    for item in initial:
        _identity_shape(item, P, full=True)
        P.require(_actual_identity(item['path'], P) == item, 'scoring_callback initial metadata drift')
    P.require(isinstance(raw.get('files'), list)
              and len(raw['files']) == len(initial)
              and len({i['path'] for i in raw['files']}) == len(initial)
              and {i['path'] for i in raw['files']} == {i['path'] for i in initial},
              'scoring_callback AP observation must use only captured initial identities')
    initial_by_path = {i['path']: i for i in initial}
    for item in raw['files']:
        P.require(_same_identity(item, initial_by_path[item['path']], P),
                  'scoring_callback AP observation/capture identity drift')
    return dict(observed_utc=capture['observed_utc'], capture_receipt=capture_id,
                clock_association=clock_id)
