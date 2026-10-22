"""CONFX7 24-hour feasibility estimate under the new memory admission (CONFX7/SPEC.md section 7).

    python feasibility_24h.py --measurements MEMORY_MEASUREMENTS.json --code-root DIR --out FEASIBILITY_24H.json

This is a planning model built only from synthetic measurements and the registered plan; it reads no study value.
It does three things:
1. It simulates the CONFX7 per-task admission in each news origin wave. A fit is admitted if the parent baseline plus
   the peaks of the running fits plus its projection stays below 6.6 GiB. The throttle to one worker applies at
   6.0 GiB, and at most four news workers run.
2. It applies the unchanged frozen whole-stage admission: 1.25 × the largest relevant runtime × the frozen growth
   factors × `projected_stage_seconds` (four-worker rounds), and LEAR's max(1.25 × pilot, 288 × 0.5 s) per daily job.
3. It walks the fixed stage order against the 24-hour wall budget.

Stated assumptions are recorded in the output. Real runtimes depend on real data and pruned widths.
"""
from __future__ import annotations
import argparse, datetime as dt, json, math, sys
from datetime import date, timedelta
from pathlib import Path

GIB = 1024 ** 3
TREE, THROTTLE, BUDGET = 6.6 * GIB, 6.0 * GIB, 86400.
NEWS_SHARED = 872
NEWS_EXTRAS = {'N': 0, 'M': 2, 'L_count': 36, 'L_chen': 386, 'E_raw': 386, 'M_shift': 2, 'P_shift': 386,
               'P_content': 386, 'W2_D': 140, 'W_Bai': None}
NOTICE_SHARED = 61
NOTICE_EXTRAS = {'N': 0, 'M_notice': 3, 'L14': 17, 'L_Laz': 11, 'L_chen_notice': 387, 'R': 17, 'T': 8, 'M_shift_notice': 3,
                 'P_shift': 387, 'P_content': 387, 'NP': 8, 'NPL': 25, 'NPP': 25, 'NPM': 11}
NOTICE_TRAIN = 894901
LEAR_FLOOR = 288 * .5


def run(measurements, label, case):
    entry = next(c for c in measurements['cases'] if c['case']['name'] == case)
    r = entry['runs'][label]
    res = r['result'] or {}
    anonymous = res.get('peak_anonymous_bytes') or r.get('sampled_max_anonymous_bytes')
    return {'anonymous': anonymous, 'rss': max(res.get('peak_rss_bytes') or 0, r.get('sampled_max_rss_bytes') or 0),
            'runtime': res.get('runtime_seconds'), 'wall': res.get('runtime_seconds'), 'process_wall': r.get('wall_seconds'),
            'train_rows': res.get('train_rows'), 'state': res.get('state')}


def news_rows(origin):
    days = (date.fromisoformat(origin) - date(2021, 10, 1)).days - 1     # complete label-legal days before the origin
    return 72 * days


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--measurements'); parser.add_argument('--code-root'); parser.add_argument('--out')
    parser.add_argument('--unavailable', default='W_Bai', help='comma-separated news arms without a bundle')
    args = parser.parse_args()
    m = json.loads(Path(args.measurements).read_text())
    sys.path.insert(0, str(Path(args.code_root) / 'CONFX2'))
    import execution_adapter as ex  # noqa: E402
    import runtime  # noqa: E402
    scheduler = runtime.conf_module('scheduler')
    unavailable = {a for a in args.unavailable.split(',') if a}
    base = m['parent_baseline']['anonymous'] + 20 * 1024 ** 2          # parent + resource tracker
    wide, narrow = run(m, 'new', 'news_L_chen_last_origin_full_shape'), run(m, 'new', 'news_N_last_origin_full_shape')
    full_rows = wide['train_rows']
    def news_anonymous(arm):
        extras = NEWS_EXTRAS[arm]
        return narrow['anonymous'] + extras / 386 * (wide['anonymous'] - narrow['anonymous'])
    def news_runtime(arm, origin, variant):
        extras = NEWS_EXTRAS[arm]
        full = narrow['wall'] + extras / 386 * (wide['wall'] - narrow['wall'])
        rows = 85032 if variant == '2025_fixed_validation' else news_rows(origin)
        return full * rows / full_rows
    n225, n450 = run(m, 'new', 'notice_L_chen_notice_R225000'), run(m, 'new', 'notice_L_chen_notice_R450000')
    l450 = run(m, 'new', 'notice_L14_R450000')
    slope_a = (n450['anonymous'] - n225['anonymous']) / (450000 - 225000)
    slope_t = (n450['wall'] - n225['wall']) / (450000 - 225000)
    notice_wide_anonymous = n450['anonymous'] + slope_a * (NOTICE_TRAIN - 450000)
    notice_wide_runtime = n450['wall'] + slope_t * (NOTICE_TRAIN - 450000)
    notice_full = None
    if any(c['case']['name'] == 'notice_L_chen_notice_full_rows' for c in m['cases']):
        notice_full = run(m, 'new', 'notice_L_chen_notice_full_rows')       # measured directly: preferred
        notice_wide_anonymous, notice_wide_runtime = notice_full['anonymous'], notice_full['wall']
    def notice_estimates(arm):
        cols = NOTICE_SHARED + NOTICE_EXTRAS[arm]; share = cols / 448
        if cols == 448:
            return notice_wide_anonymous, notice_wide_runtime
        anon = l450['anonymous'] + slope_a * share * (NOTICE_TRAIN - 450000)
        t = l450['wall'] * NOTICE_TRAIN / 450000
        return anon, t
    # LEAR per daily job (BASE25 amendment-2 bank: 1,098 s for 365 origins with 3 workers ~ 9.0 s per job and worker)
    lear_job = 1098 * 3 / 365.
    plan = ex.registered_plan()
    stages, elapsed, notes = [], 0., []
    # Counted pilots: first five notice fits, first news origin (4 primary arms), one LEAR job (all reused later).
    pilot = sum(notice_estimates(a)[1] for a in scheduler.NOTICE_PRIMARY) + \
            sum(news_runtime(a, '2026-03-01', 'main') for a in scheduler.NEWS_PRIMARY) + lear_job
    elapsed += pilot
    largest = {'news': 0., 'notice': 0.}
    largest['news'] = max(news_runtime(a, '2026-03-01', 'main') for a in scheduler.NEWS_PRIMARY)
    largest['notice'] = max(notice_estimates(a)[1] for a in scheduler.NOTICE_PRIMARY)
    for name, tasks, mandatory in plan:
        tasks = [t for t in tasks if not (t.task == 'news' and t.arm in unavailable)]
        source = tasks[0].task
        if source == 'lear':
            estimate = len(tasks) * max(1.25 * lear_job, LEAR_FLOOR)
            wall = len(tasks) * lear_job
            concurrency = {'max': 1}
        elif source == 'notice':
            per_job = 1.25 * max(largest['notice'], max(notice_estimates(t.arm)[1] for t in tasks))
            estimate = len(tasks) * per_job
            wall = sum(notice_estimates(t.arm)[1] for t in tasks)
            peaks = [notice_estimates(t.arm)[0] for t in tasks]
            concurrency = {'max': 1, 'largest_anonymous_bytes': max(peaks),
                           'within_6_6_GiB_limit': max(peaks) + base < TREE}
        else:
            per_job = 1.25 * max(largest['news'], max(news_runtime(t.arm, t.origin, t.variant) for t in tasks))
            estimate = scheduler.projected_stage_seconds(tasks, per_job)
            grouped = {}
            for t in tasks: grouped.setdefault(t.origin, []).append(t)
            wall = 0.; widths = []
            for origin, group in grouped.items():
                # event simulation of one origin wave under the CONFX7 admission
                waiting = list(group); running = []; now = 0.; throttled = False; maxc = 0
                while waiting or running:
                    measured = base + sum(news_anonymous(t.arm) for t, _ in running)
                    if measured >= THROTTLE: throttled = True
                    effective = 1 if throttled else 4
                    anon = measured
                    while waiting and len(running) < effective:
                        incoming = 1.08 * news_anonymous(waiting[0].arm)
                        if anon + incoming >= TREE:
                            if running: break
                            raise MemoryError('projected fit exceeds the admission alone')
                        t = waiting.pop(0); running.append((t, now + news_runtime(t.arm, t.origin, t.variant) + 2.))
                        anon += incoming
                    maxc = max(maxc, len(running))
                    running.sort(key=lambda x: x[1]); now = running[0][1]; running.pop(0)
                wall += now; widths.append(maxc)
            concurrency = {'max_admitted_per_origin': max(widths), 'min_admitted_per_origin': min(widths),
                           'tasks_per_origin': max(len(g) for g in grouped.values())}
            largest['news'] = max(largest['news'], max(news_runtime(t.arm, '2026-09-30', 'main') for t in tasks))
        remaining = BUDGET - elapsed
        admitted = estimate <= remaining
        if mandatory and not admitted:
            state = 'PRIMARY_NOT_ADMITTABLE'
        elif not admitted:
            state = 'LIKELY_DROPPED_WHOLE_STAGE'
        elif wall > remaining:
            state = 'ADMITTED_BUT_DEADLINE_LIKELY_INTERRUPTS'
        else:
            state = 'ADMITTED_LIKELY_COMPLETES'
        if admitted:
            elapsed += min(wall, remaining)
        stages.append({'stage': name, 'mandatory': mandatory, 'runnable_fits': len(tasks), 'frozen_admission_estimate_hours': estimate / 3600,
                       'expected_wall_hours_under_confx7': wall / 3600, 'remaining_budget_before_hours': remaining / 3600,
                       'state': state, 'concurrency': concurrency, 'elapsed_after_hours': elapsed / 3600})
    out = {'task': 'CONFX7', 'time_utc': dt.datetime.now(dt.timezone.utc).isoformat(), 'synthetic_planning_model': True,
           'inputs': {'measurements': args.measurements, 'parent_and_tracker_anonymous_bytes': base,
                      'news_wide_anonymous_bytes': wide['anonymous'], 'news_narrow_anonymous_bytes': narrow['anonymous'],
                      'news_wide_full_shape_wall_seconds': wide['wall'], 'news_narrow_full_shape_wall_seconds': narrow['wall'],
                      'notice_wide_full_rows_anonymous_bytes': notice_wide_anonymous,
                      'notice_wide_full_rows_wall_seconds': notice_wide_runtime,
                      'notice_wide_full_rows_source': 'measured' if notice_full else 'extrapolated from 225,000 and 450,000 rows',
                      'notice_wide_extrapolated_from_fractions_anonymous_bytes': n450['anonymous'] + slope_a * (NOTICE_TRAIN - 450000),
                      'lear_job_seconds_assumed': lear_job,
                      'unavailable_news_arms': sorted(unavailable), 'counted_pilot_hours': pilot / 3600},
           'assumptions': ['news runtime scales linearly with training rows and with extra columns between N and L_chen',
                           'running fits are counted at their measured anonymous peak (conservative); 2 s spawn per fit',
                           'notice wide: measured at full rows when available, else extrapolated from 225,000 and 450,000 rows; narrow notice arms scaled',
                           'LEAR job time from the BASE25 2025 bank (no CONF LEAR measurement); frozen 0.5 s/pair floor',
                           'synthetic data: real sparsity and pruning may lower memory and runtime'],
           'stages': stages, 'total_elapsed_hours': elapsed / 3600}
    Path(args.out).write_text(json.dumps(out, indent=2, sort_keys=True) + '\n')
    for s in stages:
        print(f"{s['stage']:34s} {s['state']:42s} est {s['frozen_admission_estimate_hours']:6.2f} h  wall {s['expected_wall_hours_under_confx7']:6.2f} h  conc {s['concurrency']}")
    print('total elapsed', round(elapsed / 3600, 2), 'h')


if __name__ == '__main__':
    main()
