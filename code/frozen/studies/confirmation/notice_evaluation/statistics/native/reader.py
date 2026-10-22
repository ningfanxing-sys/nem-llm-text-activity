'Read notice data with the frozen numerical functions.'
from __future__ import annotations
from contextlib import contextmanager
from copy import deepcopy
import ast, hashlib, importlib.util, json, sys
from pathlib import Path
OUT=Path(__file__).resolve().parents[1]
PROJ=OUT.parents[4]
Q=PROJ/'studies'
confirmation=Q/'confirmation'; AP=Q/'inference'; B=Q/'batch_estimation/fitting'; AF=confirmation/'forecast_hashes'


ARMS = ('N', 'M_notice', 'L14', 'L_Laz', 'L_chen_notice')

AFFECTED = ('L14', 'L_Laz')

PAIRS = [('L14', 'M_notice'), ('L_Laz', 'M_notice'), ('L_chen_notice', 'M_notice')]

KEYS = ['origin', 'target_time', 'region', 'horizon']

VALUES = ('prediction', 'raw_prediction', 'lower_bound', 'upper_bound')

SCOPE = dict(source='notice', seed=20260919, variant='main', secondary_corrected=False)


def verify_sources():

    from source_validator import verify_source_contract, checked_public_source
    contract = read_json(OUT/'PUBLIC_SOURCE_CONTRACT.json')
    verify_source_contract(contract)
    ancestors = read_json(OUT/'NUMERICAL_ANCESTOR_PINS.json')
    permitted = {r['path'] for r in ancestors['files']}
    for item in ancestors['files']:
        checked_public_source(item, permitted_paths=permitted)
    return ancestors

class Refusal(ValueError):
    pass

def require(ok, message):
    if not ok:
        raise Refusal(message)

def sha(path):
    h = hashlib.sha256()
    with Path(path).open('rb') as stream:
        for block in iter(lambda: stream.read(1 << 20), b''):
            h.update(block)
    return h.hexdigest()

def identity(path):
    return dict(path=str(Path(path).resolve()), sha256=sha(path))

def checked(item):
    require(isinstance(item, dict) and {'path', 'sha256'} <= item.keys(), 'Identity required')
    p = Path(item['path'])
    require(p.is_absolute() and p.is_file() and not p.is_symlink(), 'Missing/unsafe identity: '+str(p))
    require(len(item['sha256']) == 64 and sha(p) == item['sha256'], 'Identity drift: '+str(p))
    return p

def read_json(path):
    def pairs(rows):
        result = {}
        for key, value in rows:
            require(key not in result, 'Duplicate JSON key')
            result[key] = value
        return result
    def invalid(value):
        raise Refusal('Nonfinite JSON')
    return json.loads(Path(path).read_text(), object_pairs_hook=pairs, parse_constant=invalid)

def json_bytes(value):
    return (json.dumps(value, sort_keys=True, ensure_ascii=False, indent=2, allow_nan=False)+'\n').encode()

def write_json(path, value):
    path = Path(path)
    with path.open('xb') as stream:
        stream.write(json_bytes(value))

def canonical_hash(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(',', ':')).encode()).hexdigest()

def module(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    value = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(value)
    return value

@contextmanager
def import_path(path):
    sys.path.insert(0, str(path))
    try:
        yield
    finally:
        sys.path.remove(str(path))

@contextmanager
def forecast_binding_verifier():

    names = ('common', 'prediction_set', 'forecast_inputs', 'run_bound_forecasts',
             'activity_guard', 'check_prescoring_state', 'structural_projection', 'source_anchor_check')
    prior = {n: sys.modules.pop(n) for n in names if n in sys.modules}
    try:
        with import_path(AF/'code'):
            import prediction_set
            yield prediction_set
    finally:
        for name in names:
            sys.modules.pop(name, None)
        sys.modules.update(prior)

def validate_frame(native, frame):
    import numpy as np
    require(set(KEYS+['target_day']+list(VALUES)) <= set(frame), 'Prediction fields missing')
    f = native.normalize(frame)
    require(not f.duplicated(KEYS).any() and not f[KEYS].isna().any().any(), 'Prediction row coverage duplicates/missing')
    local = f.target_time.dt.tz_convert('Australia/Brisbane').dt.strftime('%Y-%m-%d')
    require(f.target_day.equals(local), 'Target-day identity mismatch')
    require(all(np.isfinite(f[col]).all() for col in VALUES), 'Nonfinite prediction')
    require((f.lower_bound <= f.upper_bound).all(), 'Clipping bounds inverted')
    return f

def substitute_rows(native, specified, aligned, arm, coverage):

    import numpy as np
    import pandas as pd
    require(arm in AFFECTED, 'Only L14 or L_Laz may be substituted')
    original, replacement = validate_frame(native, specified), validate_frame(native, aligned)
    cover = native.normalize(coverage)
    require(not cover.duplicated(KEYS).any() and len(cover) > 0, 'Coverage is empty/duplicated')
    require(replacement[KEYS+['target_day']].equals(cover[KEYS+['target_day']]), 'Row coverage mismatch')
    require(cover.target_day.between('2026-08-01', '2026-09-30').all(), 'Substitution outside window D')
    require(original.columns.tolist() == replacement.columns.tolist(), 'Prediction schema mismatch')
    index = pd.MultiIndex.from_frame(original[KEYS])
    positions = index.get_indexer(pd.MultiIndex.from_frame(cover[KEYS]))
    require((positions >= 0).all(), 'Coverage keys not specified')
    require(original.iloc[positions][KEYS+['target_day']].reset_index(drop=True).equals(cover[KEYS+['target_day']]), 'Coverage target-day mismatch')
    for col in VALUES:
        require(original[col].dtype == replacement[col].dtype, 'Prediction dtype mismatch')
    for col in ('lower_bound', 'upper_bound'):
        a, b = original.iloc[positions][col].to_numpy(), replacement[col].to_numpy()
        require(a.dtype == b.dtype and a.tobytes() == b.tobytes(), 'Original clipping-bound identity drift')
    mask = np.ones(len(original), dtype=bool)
    mask[positions] = False
    result = original.copy()
    for col in VALUES:
        values = original[col].to_numpy(copy=True)
        values[positions] = replacement[col].to_numpy()
        result[col] = values
        require(result[col].dtype == original[col].dtype, 'Prediction dtype changed during substitution')
        require(result.loc[mask, col].to_numpy().tobytes() == original.loc[mask, col].to_numpy().tobytes(), 'Uncovered prediction changed')
    return result

def primary_view(main, correction):
    require(set(correction['predictions']) == set(ARMS), 'Corrected arm census mismatch')
    selected, substitutions = [], []
    for arm in ARMS:
        matches = [i for i in main['predictions'] if (i['source'], i['arm'], i['seed'], i['variant']) == ('notice', arm, 20260919, 'main')]
        require(len(matches) == 1, 'Specified primary identity census mismatch')
        original = matches[0]
        row = correction['predictions'][arm]
        if arm in AFFECTED:
            require(row['mode'] == 'CORRECTED_D_SUBSTITUTION', 'Corrected mode mismatch')
            bound = row['specified_identity']
            require(bound['path'] == original['path'] and bound['sha256'] == original['sha256'], 'Specified prediction identity mismatch')
            require(row['identity'].get('arm') == arm and row['identity'].get('rows') == 527040,
                    'Corrected row coverage/arm mismatch')
            item = {**original, **row['identity'], 'source': 'notice', 'arm': arm, 'seed': 20260919, 'variant': 'main'}
            substitutions.append(dict(arm=arm, specified=original, aligned=item))
        else:
            require(row['mode'] == 'REUSE_BY_IDENTITY' and row['identity']['path'] == original['path'] and row['identity']['sha256'] == original['sha256'], 'Unpermitted arm substitution')
            item = original
        checked(item)
        selected.append(item)
    specified = dict(main, predictions=[s['specified'] if s else i for i in selected for s in [next((r for r in substitutions if r['arm'] == i['arm']), None)]])
    return specified, dict(main, predictions=selected), substitutions

def daily_bundle(M, view):
    panel, days, counts, predictions, ids, clips, raw = M.native._read_task_data('notice', view, diagnostic_root=None)
    require(list(predictions) == [(a, 20260919, 'main') for a in ARMS], 'Frozen loader primary census mismatch')
    losses = {}
    for arm in ARMS:
        actual_days, daily = M.native._daily(panel, predictions[(arm, 20260919, 'main')])
        require(actual_days == days, 'Daily row coverage mismatch')
        losses[arm] = daily
    return dict(id='notice/primary', task='notice', state='COMPUTED', days=days,
                losses=losses, pairs=PAIRS, family_m=3, subset=False), counts

def specified_daily_parity(M, specified_seal, score_files):

    pins = verify_sources()
    source = confirmation/'execution/seal_score.py'
    identities = [i for i in pins['files'] if Path(i['path']).resolve() == source.resolve()]
    require(len(identities) == 1, 'Frozen daily assembly identity missing')
    tree = ast.parse(checked(identities[0]).read_text())
    fn = next(n for n in tree.body if isinstance(n, ast.FunctionDef) and n.name == 'score')
    loop = next(n for n in fn.body if isinstance(n, ast.For) and
                isinstance(n.target, ast.Name) and n.target.id == 'source')
    stop = next(i for i, n in enumerate(loop.body) if isinstance(n, ast.Assign) and
                any(isinstance(t, ast.Name) and t.id == 'panel_identity' for t in n.targets))
    namespace = dict(source='notice', seal_receipt=specified_seal, scoring_root=None,
                     SEED=20260919, _read_task_data=M.native._read_task_data,
                     _daily=M.native._daily)
    exec(compile(ast.Module(body=loop.body[:stop], type_ignores=[]), str(source), 'exec'), namespace)
    daily_refs = [i for i in score_files if Path(i['path']).name == 'notice__DAILY_LOSSES.csv']
    require(len(daily_refs) == 1 and checked(daily_refs[0]).read_bytes() ==
            M.L.canonical_daily(namespace['days'], namespace['daily']),
            'Specified canonical daily parity failed')
    return dict(state='PASS', daily_reference=daily_refs[0], daily_columns=list(namespace['daily']),
                daily_assembly=dict(**identities[0], function='score',
                                    block='source loop prefix before panel_identity',
                                    format='unchanged pandas to_csv(index=False)'))

def scientific_reading(M, family, alert=False):
    'Read the saved scalar results with the frozen functions.'
    rows = []
    for row in family['reports']:
        fields = M.BS.fill_fields(M.primary_tests, row, None)
        checks, label, rob = M.P.six_checks(M.primary_tests, M.sensitivity_tests, row, None)
        cls = M.P.CLASS[row['decision']]
        env = M.robustness_tests.envelope(row)
        evaluated = cls != 'NE'
        boot = row['bootstrap']
        fields.update({'class': cls, 'checks': checks, 'label': label,
            'effect_percent': M.P.decimal(row.get('effect_percent_reference_mae')) if evaluated else None,
            'effect_aud': M.P.decimal(row.get('mean_difference')) if evaluated else None,
            'family_one_day': M.P.interval_strings(row.get('interval_family_one_day')) if evaluated else None,
            'family_seven_day': M.P.interval_strings(row.get('interval_family_seven_day')) if evaluated else None,
            'per_contrast_one_day': M.P.interval_strings(row.get('interval95_one_day')) if evaluated else None,
            'per_contrast_seven_day': M.P.interval_strings(row.get('interval95_seven_day')) if evaluated else None,
            'envelope': M.P.decimal(env['U'], 3, 'hi') if env and evaluated else None,
            'holm_p': M.P.decimal(row.get('holm_p')) if evaluated else None,
            'hln_p': M.P.decimal(row.get('hln_holm_p'), 12) if evaluated else None,
            'hac7_p': M.P.decimal(row.get('hac7_holm_p'), 12) if evaluated else None,
            'tail_counts': {name: boot[b]['bootstrap_nonpositive_effect_count'] for name, b in (('one_day', '1'), ('seven_day', '7'))} if evaluated else None,
            'draw_counts': {name: {'finite': boot[b]['finite_draws'], 'undefined': boot[b]['undefined_draws']} for name, b in (('one_day', '1'), ('seven_day', '7'))} if evaluated else None,
            'three_seed_class': 'NE', 'three_seed_effect': None,
            'seven_day_state': boot['7'].get('state', 'COMPUTED'), 'robustness': rob})
        rows.append(fields)
    bounds = [float(r['envelope']) for r in rows if r['class'] in ('NULL', 'DET') and r['envelope'] is not None]
    return dict(complete=family['state'] == 'COMPUTED', alert=bool(alert), contrasts=rows,
                bound=M.P.decimal(max(bounds), 3, 'hi') if bounds else None)

def corrected_parity(M, view, view_sha, permit, gate):
    import numpy as np
    gate()
    bundle, counts = daily_bundle(M, view)
    other, other_counts = daily_bundle(M, view)
    require(counts == other_counts and M.L.canonical_daily(bundle['days'], bundle['losses']) == M.L.canonical_daily(other['days'], other['losses']), 'Corrected native daily byte parity failed')
    attestation = dict(daily_common_key_counts=counts, common_keys_sha256=view['common_keys']['notice']['common_keys_sha256'], sealed_prediction_manifest_sha256=view_sha)
    native = M.sc.specified_daily_inference(other['losses'], other['days'], 'notice', permit, attestation)
    reference, arrays = M.BS.clean_record(M.native, native)
    duplicate = M.sc.specified_daily_inference(bundle['losses'], bundle['days'], 'notice', permit, attestation)
    M.BS.score_parity(M.native, duplicate, reference, arrays)
    prefix_sc = M.P.ChunkedScoring(M.sc, draws=2000, chunk=512, gate=gate)
    picks = {}
    for block in (1, 7):
        a = np.asarray(prefix_sc.block_picks(len(bundle['days']), block))
        b = M.sc.block_picks(len(bundle['days']), block)
        require(a.dtype == b.dtype and a.tobytes() == b.tobytes(), 'Exact first-2000 draw picks drift')

        plan = M.P.PickPlan(len(bundle['days']), block, 100000, chunk=512, gate=gate)
        parts = []
        for start, chunk in plan.chunks():
            parts.append(chunk[:min(len(chunk), 2000-start)])
            if start+len(chunk) >= 2000:
                break
        require(np.concatenate(parts).tobytes() == b.tobytes(), 'B100000 prefix picks drift')
        picks[str(block)] = dict(state='PASS', sha256=hashlib.sha256(b.tobytes()).hexdigest(), draws=2000)
    M.L.native_parity(prefix_sc, bundle, reference)
    frozen_family = M.primary_tests.family_inference(M.sc, other['losses'], PAIRS, other['days'], m=3)
    prefix_family = M.P.compute_bundle(M.primary_tests, prefix_sc, bundle)
    M.L.a2_parity(prefix_family, frozen_family, 'aligned/primary')
    for row, r in zip(prefix_family['reports'], reference['reports']):
        require(row['mean_difference'] == r['dm_p1']['mean_difference'] and row['holm_p'] == r['primary_two_sided_holm_p'], 'Native corrected point/Holm parity mismatch')
        for block in ('1', '7'):
            boot, frozen_boot = row['bootstrap'][block], r['bootstrap'][block]
            for key in ('effect_percent_reference_mae', 'interval95_percent', 'reference_mae', 'finite_draws', 'undefined_draws', 'bootstrap_nonpositive_effect_count', 'monte_carlo_resolution'):
                require(boot[key] == frozen_boot[key], 'Corrected prefix endpoint/tail mismatch')
    bundle['frozen_parity'] = 'PASS'
    return bundle, dict(state='PASS', daily_bytes_sha256=hashlib.sha256(M.L.canonical_daily(bundle['days'], bundle['losses'])).hexdigest(), exact_pick_prefix=picks, native_record_parity=True, a2_prefix_parity=True), reference, arrays

def require_official_score(manifest):
    require(manifest.get('schema') == 'A8POST_INPUTS_V2', 'Specified manifest must remain V2')
    item = manifest.get('inputs', {}).get('score_receipt')
    require(item is not None and Path(item['path']).is_file(), 'Official confirmation score does not exist')
    receipt = read_json(checked(item))
    require(receipt.get('state') == 'FROZEN_SCORE_COMPLETE', 'Official confirmation score incomplete')
    return receipt

def t5_contains(t5, item):
    return any(Path(p).resolve() == Path(item['path']).resolve() and digest == item['sha256'] for p, digest in t5['files'].items())

def verify_prediction_rows(M, main_view, corrected_view, correction, gate):
    import pandas as pd
    parity = read_json(checked(correction['parity']))
    for arm in AFFECTED:
        gate()
        old = next(i for i in main_view['predictions'] if i['arm'] == arm)
        new = next(i for i in corrected_view['predictions'] if i['arm'] == arm)
        a = pd.read_parquet(checked(old))
        b = pd.read_parquet(checked(new))
        coverage = M.native.normalize(a)[KEYS+['target_day']]
        require(len(coverage) == 527040, 'Full D row coverage mismatch')
        substitute_rows(M.native, a, b, arm, coverage)
        with forecast_binding_verifier() as V:
            changed = pd.read_parquet(checked(parity['arms'][arm]['changed_keys']))
            mask = V.touched_mask(M.native.normalize(a), changed)
            V.parity(M.native.normalize(b), M.native.normalize(a), ~mask)

def bind_native_authorities(task, native_identity, corrected_receipt_sha):

    checked(native_identity)
    for i, row in enumerate(task['contrasts']):
        row['native_authority'] = dict(**native_identity, pointer=f'/task/contrasts/{i}',
                                      source_receipt_sha256=corrected_receipt_sha)
