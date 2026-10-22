"""CONFX7 addendum 3: 24-hour feasibility with up to 7 news workers and LEAR window subjobs on 3 workers.

    python feasibility_24h_a3.py --memory MEMORY_MEASUREMENTS.json --speed SPEED_MEASUREMENTS_A3.json --code-root DIR \
        --out FEASIBILITY_24H_A3.json

This is a planning model built only from synthetic measurements and the registered plan; no study value is read.
It evaluates two configurations with the same model, so that they can be compared:
- `confx7_addendum3`: news pool up to 7 with the reserved admission; LEAR window subjobs on 3 workers;
- `four_workers_serial_lear`: news pool up to 4; serial LEAR daily jobs.

Model:
- News fit runtime alone: the measured full-shape single-fit runtimes (`MEMORY_MEASUREMENTS.json`, new worker),
  interpolated linearly in extra columns between N and L_chen and scaled by training rows (as `feasibility_24h.py`).
- Contention: a fit that launches while k fits run (itself included) takes alone × f(k). f(1) = 1. f is linear
  between the measured points of `SPEED_MEASUREMENTS_A3.json`: the mean runtime ratio (to alone) of the fits
  launched at concurrency <= 4 and of those launched at > 4.
- Admission per origin wave: the CONFX7 reserved rule. A fit launches if the parent and tracker baseline, plus the
  projections of the running fits, plus its own projection, stays below 6.6 GiB. The order is fixed and the
  per-origin barrier applies. The throttle (6.0 GiB of measured peaks) drops the wave to one worker.
- Whole-stage admission: the unchanged frozen formula, 1.25 × the largest per-fit runtime recorded so far
  (including contention) × the frozen four-worker round count, and for LEAR max(1.25 × pilot, 288 × 0.5 s) per
  daily job. The 24-hour walk is the same as `feasibility_24h.py`.
- LEAR daily wall: the measured synthetic daily-job wave walls, serial or with 3 subjob workers.
"""
from __future__ import annotations
import argparse, datetime as dt, json, sys
from datetime import date
from pathlib import Path

GIB = 1024 ** 3
TREE, THROTTLE, BUDGET = 6.6 * GIB, 6.0 * GIB, 86400.
NEWS_EXTRAS = {'N': 0, 'M': 2, 'L_count': 36, 'L_chen': 386, 'E_raw': 386, 'M_shift': 2, 'P_shift': 386,
               'P_content': 386, 'W2_D': 386, 'W_Bai': None}          # W2_D counted at the wide width (true width unknown)
NOTICE_SHARED = 61
NOTICE_EXTRAS = {'N': 0, 'M_notice': 3, 'L14': 17, 'L_Laz': 11, 'L_chen_notice': 387, 'R': 17, 'T': 8, 'M_shift_notice': 3,
                 'P_shift': 387, 'P_content': 387, 'NP': 8, 'NPL': 25, 'NPP': 25, 'NPM': 11}
NOTICE_TRAIN = 894901
LEAR_FLOOR = 288 * .5


def case(memory, name):
    entry = next(c for c in memory['cases'] if c['case']['name'] == name)
    run = entry['runs']['new']; res = run['result'] or {}
    return {'anonymous': res.get('peak_anonymous_bytes') or run.get('sampled_max_anonymous_bytes'),
            'runtime': res.get('runtime_seconds'), 'train_rows': res.get('train_rows')}


def news_rows(origin):
    return 72 * ((date.fromisoformat(origin) - date(2021, 10, 1)).days - 1)


def contention(speed):
    """f(k) points: (mean concurrency, mean runtime ratio to the alone runtime of the class)."""
    low, high = [], []
    for wave in speed['news']['waves'].values():
        for run in wave['runs'].values():
            for tid, t in run['tasks'].items():
                arm = tid.split('__')[2]
                alone = speed['_alone']['wide' if NEWS_EXTRAS.get(arm, 0) and NEWS_EXTRAS[arm] >= 384 else 'narrow']
                ratio = t['runtime_seconds'] / alone
                (low if t['concurrent_fits_at_launch'] <= 4 else high).append((t['concurrent_fits_at_launch'], ratio))
    point = lambda xs: (sum(k for k, _ in xs) / len(xs), sum(r for _, r in xs) / len(xs)) if xs else None
    return point(low), point(high)


def make_f(low, high):
    """Piecewise linear through (1, 1) and the measured points; flat beyond the last point."""
    pts = sorted([(1., 1.)] + [p for p in (low, high) if p])
    def f(k):
        if k <= pts[0][0]: return pts[0][1]
        for (k0, r0), (k1, r1) in zip(pts, pts[1:]):
            if k <= k1: return r0 + (r1 - r0) * (k - k0) / max(k1 - k0, 1e-9)
        return pts[-1][1]
    return f


def simulate(config, plan, scheduler, memory, speed, unavailable):
    news_max = 7 if config == 'confx7_addendum3' else 4
    base = memory['parent_baseline']['anonymous'] + 20 * 1024 ** 2
    wide, narrow = case(memory, 'news_L_chen_last_origin_full_shape'), case(memory, 'news_N_last_origin_full_shape')
    n450, n225 = case(memory, 'notice_L_chen_notice_R450000'), case(memory, 'notice_L_chen_notice_R225000')
    l450 = case(memory, 'notice_L14_R450000')
    try:
        full = case(memory, 'notice_L_chen_notice_full_rows')
    except StopIteration:
        full = None
    f = make_f(*contention(speed))
    def anon(arm):
        return narrow['anonymous'] + NEWS_EXTRAS[arm] / 386 * (wide['anonymous'] - narrow['anonymous'])
    def alone(arm, origin, variant):
        rows = 85032 if variant == '2025_fixed_validation' else news_rows(origin)
        return (narrow['runtime'] + NEWS_EXTRAS[arm] / 386 * (wide['runtime'] - narrow['runtime'])) * rows / wide['train_rows']
    slope_t = (n450['runtime'] - n225['runtime']) / (450000 - 225000)
    def notice_runtime(arm):
        if NOTICE_SHARED + NOTICE_EXTRAS[arm] == 448:
            return full['runtime'] if full else n450['runtime'] + slope_t * (NOTICE_TRAIN - 450000)
        return l450['runtime'] * NOTICE_TRAIN / 450000
    lear_walls = [e['parallel']['3']['wave_wall_seconds'] if config == 'confx7_addendum3' else e['serial']['wall_seconds_with_spawn']
                  for e in speed['lear']['issues'].values()]
    lear_job = max(lear_walls)
    pilot = sum(notice_runtime(a) for a in scheduler.NOTICE_PRIMARY) + max(alone(a, '2026-03-01', 'main') for a in scheduler.NEWS_PRIMARY) + lear_job
    elapsed = pilot; largest = max(alone(a, '2026-03-01', 'main') for a in scheduler.NEWS_PRIMARY)
    stages = []
    for name, tasks, mandatory in plan:
        tasks = [t for t in tasks if not (t.task == 'news' and t.arm in unavailable)]
        source = tasks[0].task; concurrency = {}
        if source == 'lear':
            estimate = len(tasks) * max(1.25 * lear_job, LEAR_FLOOR); wall = len(tasks) * lear_job
            concurrency = {'subjob_workers': 3 if config == 'confx7_addendum3' else 1}
        elif source == 'notice':
            largest_notice = max(notice_runtime(a) for a in scheduler.NOTICE_PRIMARY)
            estimate = len(tasks) * 1.25 * max(largest_notice, max(notice_runtime(t.arm) for t in tasks))
            wall = sum(notice_runtime(t.arm) for t in tasks); concurrency = {'max': 1}
        else:
            grouped = {}
            for t in tasks: grouped.setdefault(t.origin, []).append(t)
            wall = 0.; widths = []; stage_max_runtime = 0.
            for origin, group in grouped.items():
                waiting = list(group); running = []; now = 0.; throttled = False; maxc = 0
                while waiting or running:
                    measured = base + sum(anon(t.arm) for t, _ in running)
                    if measured >= THROTTLE: throttled = True
                    effective = 1 if throttled else news_max
                    reserved = base + sum(1.08 * anon(t.arm) for t, _ in running)
                    while waiting and len(running) < effective:
                        incoming = 1.08 * anon(waiting[0].arm)
                        if reserved + incoming >= TREE:
                            if running: break
                            raise MemoryError('projected fit exceeds the admission alone')
                        t = waiting.pop(0); k = len(running) + 1
                        runtime = alone(t.arm, t.origin, t.variant) * f(k)
                        stage_max_runtime = max(stage_max_runtime, runtime)
                        running.append((t, now + runtime + 2.)); reserved += incoming
                    maxc = max(maxc, len(running))
                    running.sort(key=lambda x: x[1]); now = running[0][1]; running.pop(0)
                wall += now; widths.append(maxc)
            per_job = 1.25 * max(largest, max(alone(t.arm, t.origin, t.variant) for t in tasks))
            estimate = scheduler.projected_stage_seconds(tasks, per_job)
            concurrency = {'max_admitted_per_origin': max(widths), 'min_admitted_per_origin': min(widths),
                           'tasks_per_origin': max(len(g) for g in grouped.values())}
            largest = max(largest, stage_max_runtime)
        remaining = BUDGET - elapsed; admitted = estimate <= remaining
        state = ('PRIMARY_NOT_ADMITTABLE' if mandatory and not admitted else 'LIKELY_DROPPED_WHOLE_STAGE' if not admitted else
                 'ADMITTED_BUT_DEADLINE_LIKELY_INTERRUPTS' if wall > remaining else 'ADMITTED_LIKELY_COMPLETES')
        if admitted: elapsed += min(wall, remaining)
        stages.append({'stage': name, 'mandatory': mandatory, 'runnable_fits': len(tasks), 'frozen_admission_estimate_hours': estimate / 3600,
                       'expected_wall_hours': wall / 3600, 'remaining_budget_before_hours': remaining / 3600, 'state': state,
                       'concurrency': concurrency, 'elapsed_after_hours': elapsed / 3600,
                       'largest_recorded_news_runtime_seconds_after': largest})
    return {'stages': stages, 'total_elapsed_hours': elapsed / 3600, 'counted_pilot_hours': pilot / 3600,
            'lear_daily_job_wall_seconds': lear_job, 'contention_points': [list(p) for p in contention(speed) if p]}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--memory', required=True); parser.add_argument('--speed', required=True)
    parser.add_argument('--code-root', required=True); parser.add_argument('--out', required=True)
    parser.add_argument('--unavailable', default='W_Bai')
    args = parser.parse_args()
    memory = json.loads(Path(args.memory).read_text()); speed = json.loads(Path(args.speed).read_text())
    speed['_alone'] = {'wide': case(memory, 'news_L_chen_last_origin_full_shape')['runtime'],
                       'narrow': case(memory, 'news_N_last_origin_full_shape')['runtime']}
    sys.path.insert(0, str(Path(args.code_root) / 'CONFX2'))
    import execution_adapter as ex  # noqa: E402
    import runtime  # noqa: E402
    scheduler = runtime.conf_module('scheduler'); plan = ex.registered_plan()
    unavailable = {a for a in args.unavailable.split(',') if a}
    result = {'task': 'CONFX7', 'addendum': 3, 'time_utc': dt.datetime.now(dt.timezone.utc).isoformat(), 'synthetic_planning_model': True,
              'inputs': {'memory': args.memory, 'speed': args.speed, 'unavailable_news_arms': sorted(unavailable)},
              'configurations': {c: simulate(c, plan, scheduler, memory, speed, unavailable)
                                 for c in ('confx7_addendum3', 'four_workers_serial_lear')},
              'assumptions': ['news runtime alone scales linearly with training rows and extra columns (N to L_chen); W2_D counted wide',
                              'contention f(k) linear through the measured 4- and 7-worker points; 2 s spawn per fit',
                              'running fits reserved at 1.08 x their class peak; parent and tracker baseline as measured',
                              'frozen whole-stage admission: 1.25 x largest recorded runtime (with contention) x four-worker rounds',
                              'LEAR daily wall from the synthetic daily-job waves; admission floor 288 x 0.5 s unchanged',
                              'synthetic data: real sparsity and pruning may lower memory and runtime']}
    Path(args.out).write_text(json.dumps(result, indent=2, sort_keys=True) + '\n')
    for c, r in result['configurations'].items():
        print('==', c, 'total', round(r['total_elapsed_hours'], 2), 'h')
        for s in r['stages']:
            print(f"   {s['stage']:34s} {s['state']:42s} est {s['frozen_admission_estimate_hours']:6.2f} h wall {s['expected_wall_hours']:6.2f} h {s['concurrency']}")


if __name__ == '__main__':
    main()
