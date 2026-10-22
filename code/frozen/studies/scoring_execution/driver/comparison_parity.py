'Compare daily-loss CSVs with the saved numerical arrays.'
from contextlib import contextmanager
import struct
from types import FunctionType, SimpleNamespace
from pathlib import Path
from source_bytes import checked, identity, require

FIELDS = ('arm', 'reference', 'decision', 'holm_p', 'mean_difference',
          'effect_percent_reference_mae', 'interval95_one_day', 'interval95_seven_day',
          'interval_family_one_day', 'interval_family_seven_day')
POINTS = ('mean_difference', 'p_two_sided', 'holm_p', 'decision',
          'hln_decision', 'hln_holm_p', 'hac7_decision', 'hac7_holm_p')


@contextmanager
def nested_writer_capture(L):

    branch = L.core_task.__globals__.get('core_task')
    require(callable(branch), 'AP nested capture requires the R2 core entry')
    S = branch.__globals__.get('S')
    require(S is not None and callable(S.native_namespace), 'AP R2 namespace seam missing')
    original = S.native_namespace
    def namespace(native):
        ns = original(native)
        for name in ('_a1_task', '_a1_reclip'):
            fn = ns[name]
            require(isinstance(fn, FunctionType), 'AP frozen A1 helper missing: '+name)
            clone = FunctionType(fn.__code__, ns, fn.__name__, fn.__defaults__, fn.__closure__)
            clone.__kwdefaults__ = fn.__kwdefaults__
            ns[name] = clone
        return ns
    S.native_namespace = namespace
    try:
        yield
    finally:
        S.native_namespace = original


def exact(a, b):

    if isinstance(a, float) and isinstance(b, float):
        return struct.pack('>d', a) == struct.pack('>d', b)
    if isinstance(a, (list, tuple)) and isinstance(b, (list, tuple)):
        return len(a) == len(b) and all(exact(x, y) for x, y in zip(a, b))
    return a == b


def official_csv_proof(L, records, bundles, evidence):

    own = evidence['daily_csv_proof']
    official = {}
    for task, primary in (('news', ('N', 'M', 'L_count', 'L_chen')),
                          ('notice', ('N', 'M_notice', 'L14', 'L_Laz', 'L_chen_notice'))):
        columns = list(primary)
        for row in records['seal']['predictions']:
            if row['source'] in (task, 'lear' if task == 'news' else task) and \
                    row['seed'] == 20260919 and row['variant'] == 'main' and row['arm'] not in columns:
                columns.append(row['arm'])
        rows = [r for r in records['score_receipt']['files']
                if Path(r['path']).name == task+'__DAILY_LOSSES.csv']
        require(len(rows) == 1, 'AP official R2 CSV identity census: '+task)
        item = rows[0]; payload = checked(item)
        bundle = bundles[task+'/primary']
        require(own[task]['state'] == 'PASS', 'AP full CS8 CSV proof failed: '+task)
        require(all(arm in bundle['losses'] for arm in columns), 'AP R2 replay column missing: '+task)
        raw = {arm:bundle['losses'][arm] for arm in columns}
        require(L.canonical_daily(bundle['days'], raw) == payload,
                'AP exact replay/original R2 CSV column-view drift: '+task)
        official[task] = dict(own[task], file=identity(item['path']), columns=columns,
                             state='PASS', scope='IMMUTABLE_R2_MAIN_COLUMN_VIEW',
                             own_cs8_csv=own[task]['file'])
    evidence['cs8_daily_csv_proof'] = own
    evidence['daily_csv_proof'] = official


def persisted_primary_parity(original, actual, saved, where, point_only=False):

    if where not in ('news/persisted_primary', 'notice/persisted_primary'):
        return original(actual, saved, where, point_only=point_only)
    require(len(actual) == len(saved), 'A17 immutable reader primary row census')
    require(all(all(k in a and k in b and exact(a[k], b[k])
                    for k in set(FIELDS + POINTS)) for a,b in zip(actual,saved)),
            'A17 exact immutable reader primary anchor mismatch: '+where)
    numeric_actual = [{k:v for k,v in row.items() if k != 'robustness'} for row in actual]
    numeric_saved = [{k:v for k,v in row.items() if k != 'robustness'} for row in saved]
    return original(numeric_actual, numeric_saved, where, point_only=point_only)


def reader_computation(P, L, primary_tests, frozen, inputs, bundles, computed):

    result = dict(computed); tasks = {}; reasons = []
    for task in P.PAIRS:
        key = task+'/primary'; raw = computed[key]; bundle = bundles[key]
        if raw['state'] != 'COMPUTED':
            continue
        frame = inputs.daily_losses(task)
        require(frame.target_day.tolist() == bundle['days'], 'A17 reader/raw day view drift')
        native = inputs.score_json(task+'__PRIMARY.json')
        hln = inputs.score_json(task+'__A1_HLN.json')
        seeds = inputs.score_json(task+'__A1_SEED_FRAGILE.json')

        L.native_parity(P.ChunkedScoring(frozen, 2000, 512), bundle, native)
        dense = P.compute_bundle(primary_tests, frozen, dict(bundle, mean_prediction_losses=None))
        require(len(raw['reports']) == len(native['reports']) == len(dense['reports']),
                'A17 native primary row census')
        for row, saved, oracle in zip(raw['reports'], native['reports'], dense['reports']):
            require(all(exact(row[k], oracle[k]) for k in FIELDS), 'A17 raw dense/prefix mismatch')
            require((row['arm'], row['reference']) == (saved['arm'], saved['reference']) and
                exact(row['mean_difference'], saved['dm_p1']['mean_difference']) and
                exact(row['p_two_sided'], saved['dm_p1']['p_two_sided']) and
                exact(row['holm_p'], saved.get('primary_two_sided_holm_p')) and
                row['decision'] == saved.get('primary_decision'), 'A17 raw native point mismatch')
            for block in ('1', '7'):
                anchor = saved['bootstrap'][block]
                for field in ('effect_percent_reference_mae', 'reference_mae', 'interval95_percent',
                              'finite_draws', 'undefined_draws', 'bootstrap_nonpositive_effect_count',
                              'monte_carlo_resolution'):
                    if field in anchor:
                        require(exact(row['bootstrap'][block].get(field), anchor[field]),
                                'A17 raw native bootstrap bit mismatch')
        csv_bundle = dict(bundle, losses={arm:frame[arm].to_numpy() for arm in bundle['losses']},
                          mean_prediction_losses=None)
        csv = P.compute_bundle(primary_tests, frozen, csv_bundle)
        seed_by_pair = {(s['arm'], s['reference']):s for s in seeds['rows']}
        hln_by_pair = {(s['arm'], s['reference']):s for s in hln['rows']}
        for row, raw_row in zip(csv['reports'], raw['reports']):
            pair = (row['arm'], row['reference']); h = hln_by_pair.get(pair, {})
            require(exact(raw_row['hln_holm_p'], h.get('hln_t_holm_p')) and
                    raw_row['hln_decision'] == h.get('hln_decision'), 'A17 raw native HLN mismatch')

            row.update({k:raw_row[k] for k in POINTS})
            seed = seed_by_pair.get(pair, {})
            reasons.append((row, seed.get('reason')))


        csv['three_seed'] = dict(reports=[dict(decision=seed_by_pair.get(
            (r['arm'], r['reference']), {}).get('three_seed_mean_decision')) for r in csv['reports']])
        mean = raw.get('three_seed')
        if mean and mean.get('state') == 'COMPUTED':
            require(len(mean['reports']) == len(csv['reports']) and all(
                r['decision'] == s['decision'] for r,s in zip(mean['reports'],csv['three_seed']['reports'])),
                'A17 raw native mean decision mismatch')
        result[key] = csv
        tasks[task] = dict(days=len(bundle['days']), parser='primary_tests.Inputs.daily_losses (default pd.read_csv)',
            csv_identity=inputs.score_files[task+'__DAILY_LOSSES.csv'],
            native_identity=inputs.score_files[task+'__PRIMARY.json'])
    return result, tasks, reasons


@contextmanager
def installed(P, L, cs8):

    replay, parity, complete = L.replay, P.check_parity, L.complete_bundles
    reader_parity = L.a2_parity
    captured = {}
    def replay_with_inputs(state, scratch, primary_tests, sensitivity_tests, robustness_tests, frozen, records, synthetic=False):
        old = cs8.effective_inputs; seen = []; daily_views = {}
        def inputs(*args, **kwargs):
            value = old(*args, **kwargs); seen.append(value); return value
        cs8.effective_inputs = inputs
        try:
            with nested_writer_capture(L):
                core = L.core_task
                def capture_daily(*args, **kwargs):
                    value = core(*args, **kwargs)
                    task = args[2]
                    require(task not in daily_views, 'AP duplicate raw daily capture: '+task)
                    daily_views[task+'/primary'] = dict(days=value[0][task+'__PRIMARY.json']['days'],
                                            losses=value[1])
                    return value
                L.core_task = capture_daily
                try:
                    bundles, evidence = replay(state, scratch, primary_tests, sensitivity_tests, robustness_tests, frozen, records, synthetic)
                finally:
                    L.core_task = core
        finally:
            cs8.effective_inputs = old
        require(len(seen) == 1, 'A17 exact replay input seam')
        official_csv_proof(L, records, daily_views, evidence)
        captured.update(inputs=seen[0], bundles=bundles, evidence=evidence, frozen=frozen)
        return bundles, evidence
    def check(primary_tests, sensitivity_tests, robustness_tests, computed, a2, a3, a4):
        require(bool(captured), 'A17 missing actual replay input timestamp_checks')
        csv, tasks, reasons = reader_computation(P, L, primary_tests, captured['frozen'],
            captured['inputs'], captured['bundles'], computed)
        for task in tasks:
            for row, anchor, anchor4 in zip(csv[task+'/primary']['reports'],
                    a2['tasks'][task]['primary'], a4['tasks'][task]['primary_rows']):
                require(all(exact(row[k], anchor[k]) and exact(row[k], anchor4[k]) for k in FIELDS),
                        'A17 exact CSV reader-anchor mismatch: '+task)

        pending = iter(reasons); calls = []
        def robust(*args, **kwargs):
            row, reason = next(pending)
            require(args[:3] == (row['decision'], row['interval95_one_day'], row['interval95_seven_day']),
                    'A17 native robustness call order')
            calls.append(row); return sensitivity_tests.robustness_a3(*args, **kwargs, seed_reason=reason)
        proxy = SimpleNamespace(**dict(vars(sensitivity_tests), robustness_a3=robust))
        value = parity(primary_tests, proxy, robustness_tests, csv, a2, a3, a4)
        require(len(calls) == len(reasons), 'A17 full reader-anchor census')
        captured['evidence']['representation_parity'] = dict(schema='MINRUN_A17_EXACT_PARITY_V1',
            reader_anchor='CSV_DEFAULT_PARSER_EXACT', native='RAW_FLOAT64_EXACT',
            official_statistics='RAW_FLOAT64_UNCHANGED', tasks=tasks)
        return value
    def complete_with_dispositions(primary_tests, sensitivity_tests, robustness_tests, frozen, bundles, records, evidence):
        result = complete(primary_tests, sensitivity_tests, robustness_tests, frozen, bundles, records, evidence)
        from comparison_inventory import complete as census
        return census(P, captured['inputs'], result, records, evidence)
    L.replay, P.check_parity, L.complete_bundles = replay_with_inputs, check, complete_with_dispositions
    L.a2_parity = lambda actual,saved,where,point_only=False:persisted_primary_parity(
        reader_parity,actual,saved,where,point_only)
    try:
        yield
    finally:
        L.replay, P.check_parity, L.complete_bundles = replay, parity, complete
        L.a2_parity = reader_parity
