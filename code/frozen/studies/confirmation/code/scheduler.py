"""CONF scheduler skeleton. Import and default CLI perform no data reads or fits.

Future execution supplies a frozen adapter and an authorization gate. Scheduling
uses runtime/resource receipts only; it never receives losses, labels or scores.
"""
from __future__ import annotations

from concurrent.futures import ProcessPoolExecutor, wait, FIRST_COMPLETED
from dataclasses import dataclass
from datetime import date, timedelta
import math
import multiprocessing as mp
import os
import time
from typing import Callable
try:
    from .guard import ExecutionPermit, require_execution
except ImportError:
    from guard import ExecutionPermit, require_execution

SEED = 20260919
EXTRA_SEEDS = (20260920, 20260921)
TARGET_WORKERS = 4
THROTTLE_BYTES = 6.0 * 1024**3
STOP_BYTES = 6.6 * 1024**3
FIT_BUDGET_SECONDS = 24 * 3600
LEAR_PAIR_SECONDS_ADMISSION_FLOOR = .5  # project planning floor, not measured runtime
NEWS_PRIMARY = ("N", "M", "L_count", "L_chen")
NEWS_SECONDARY = ("M_shift", "E_raw", "W_Bai", "P_shift", "P_content")
NOTICE_PRIMARY = ("N", "M_notice", "L14", "L_Laz", "L_chen_notice")
NOTICE_SECONDARY = ("M_shift_notice", "R", "T", "P_shift", "P_content", "NP", "NPL", "NPP")


@dataclass(frozen=True)
class FitTask:
    task: str
    origin: str
    arm: str
    seed: int
    variant: str = "main"
    component_pairs: int = 0


def days(start: str = "2026-03-01", end: str = "2026-09-30"):
    d, last = date.fromisoformat(start), date.fromisoformat(end)
    while d <= last:
        yield d.isoformat()
        d += timedelta(days=1)


def news_tasks(arms, seeds=(SEED,), variant="main"):
    return [FitTask("news", d, a, s, variant) for d in days() for a in arms for s in seeds]


def notice_tasks(arms, seeds=(SEED,), variant="main"):
    # One pooled model over the unchanged RF2 C training bank, not 30 models.
    return [FitTask("notice", "prewindow_frozen_C_bank", a, s, variant) for a in arms for s in seeds]


def plan():
    """Priority is fixed now; each stage is a complete run admission unit."""
    return [
        ("primary_notice", notice_tasks(NOTICE_PRIMARY), True),
        ("primary_news", news_tasks(NEWS_PRIMARY), True),
        ("report_only_2025_validation", [FitTask("news", "2025-01-01", a, SEED, "2025_fixed_validation")
                                         for a in (*NEWS_PRIMARY, *NEWS_SECONDARY)], False),
        ("secondary_notice", notice_tasks(NOTICE_SECONDARY), False),
        ("secondary_news", news_tasks(NEWS_SECONDARY), False),
        # Each daily job produces 3 regions x 24 hours x 4 windows = 288
        # LARS-AIC/coordinate-descent pairs. All four windows are indivisible.
        ("secondary_LEAR", [FitTask("lear", d, "LEAR", SEED, component_pairs=288) for d in days()], False),
        ("primary_seed_robustness_notice", notice_tasks(NOTICE_PRIMARY[1:], EXTRA_SEEDS), False),
        ("primary_seed_robustness_news", news_tasks(NEWS_PRIMARY[1:], EXTRA_SEEDS), False),
        ("window_24h", news_tasks(("M", "L_count", "L_chen"), variant="24h"), False),
        ("first_L_notice", notice_tasks(("L_chen_notice",), variant="first_L"), False),
        ("first_L_news", news_tasks(("L_chen", "E_raw"), variant="first_L"), False),
    ]


def plan_counts():
    stages = {name: {"fit_jobs": len(tasks), "component_pairs": sum(t.component_pairs for t in tasks), "mandatory": mandatory}
              for name, tasks, mandatory in plan()}
    return {"stages": stages, "news_lightgbm_fits": sum(len(tasks) for _, tasks, _ in plan() if tasks[0].task == "news"),
            "notice_lightgbm_fits": sum(len(tasks) for _, tasks, _ in plan() if tasks[0].task == "notice"),
            "lear_component_pairs": 214 * 3 * 24 * 4,
            "lear_estimator_fits": 2 * 214 * 3 * 24 * 4,
            "budget_wall_fitting_seconds": FIT_BUDGET_SECONDS}


def worker_init():
    # NEWS only. Notice fits retain RF2 n_jobs=6 and run serially outside pool.
    for key in ("OPENBLAS_NUM_THREADS", "OMP_NUM_THREADS", "MKL_NUM_THREADS", "VECLIB_MAXIMUM_THREADS"):
        os.environ[key] = "1"


def task_tree_rss(pool=None):
    import psutil
    parent = psutil.Process(os.getpid()).memory_info().rss
    workers = []
    for proc in ((pool._processes or {}) if pool is not None else {}).values():
        if proc.pid:
            try:
                workers.append(psutil.Process(proc.pid).memory_info().rss)
            except psutil.NoSuchProcess:
                if proc.exitcode is None:
                    raise RuntimeError("Known live worker vanished during RSS measurement")
    return parent, workers


def projected_stage_seconds(tasks, conservative_fit_seconds):
    """Resource estimate from metadata receipts only, never performance losses."""
    if not tasks:
        return 0.0
    if tasks[0].task in ("notice", "lear"):
        return len(tasks) * conservative_fit_seconds
    grouped = {}
    for task in tasks:
        grouped[task.origin] = grouped.get(task.origin, 0) + 1
    return sum(math.ceil(n / TARGET_WORKERS) for n in grouped.values()) * conservative_fit_seconds


def admission_decisions(elapsed_fitting_seconds, conservative_seconds_by_stage):
    """Fixed forward priority; a skipped stage is unavailable as a whole.

    Estimates may only use runtime/RSS/shape metadata from counted pilot receipts.
    Unknown optional runtime means no admission; in execution a counted first
    LEAR daily job may establish its estimate and is never scored by itself.
    No label, effect estimate, p value or diagnostic may enter this function.
    """
    remaining = FIT_BUDGET_SECONDS - float(elapsed_fitting_seconds)
    decisions = []
    for name, tasks, mandatory in plan():
        per_job = conservative_seconds_by_stage.get(name)
        estimate = None if per_job is None else projected_stage_seconds(tasks, per_job)
        admitted = estimate is not None and estimate <= remaining
        if mandatory and not admitted:
            raise RuntimeError("Primary completion cannot be admitted within the frozen fitting budget")
        decisions.append({"stage": name, "admitted": admitted, "estimated_seconds": estimate,
                          "reason": "ADMITTED_BY_RUNTIME_METADATA" if admitted else "BUDGET_OR_RUNTIME_UNKNOWN_WHOLE_STAGE_UNAVAILABLE"})
        if admitted:
            remaining -= estimate
    return decisions


def lear_daily_admission_estimate(counted_whole_issue_pilot_seconds):
    """Use a complete 288-pair first issue; charge this counted pilot to budget."""
    return max(1.25 * float(counted_whole_issue_pilot_seconds), 288 * LEAR_PAIR_SECONDS_ADMISSION_FLOOR)


def run_news_origin(tasks, pool, fit_one: Callable, write_receipt: Callable,
                    projected_worker_bytes: int, deadline: float, permit: ExecutionPermit):
    """v9 pattern: measured admission, 4 workers, barrier before next origin."""
    require_execution(permit)
    waiting, active, records = list(tasks), {}, []
    throttled = False
    while waiting or active:
        parent, worker_rss = task_tree_rss(pool)
        current = parent + sum(worker_rss)
        if current >= STOP_BYTES:
            raise RuntimeError("Known task tree reached the frozen 6.6 GiB stop")
        if current > THROTTLE_BYTES:
            throttled = True
        effective = 1 if throttled else TARGET_WORKERS
        # After the wall budget expires, drain already running fits; launch none.
        if time.monotonic() >= deadline and waiting:
            for future, task in list(active.items()):
                rec = future.result()
                write_receipt(task, rec)
            raise TimeoutError("Fitting budget reached; stage incomplete and ineligible for scoring")
        while waiting and len(active) < effective:
            parent, worker_rss = task_tree_rss(pool)
            current = parent + sum(worker_rss)
            idle = max(0, len(worker_rss) - len(active))
            incoming = max(0, projected_worker_bytes - min(worker_rss)) if idle and worker_rss else projected_worker_bytes
            if current + incoming >= STOP_BYTES:
                if active:
                    break
                raise RuntimeError("No measured/projected memory headroom for one registered fit")
            task = waiting.pop(0)
            active[pool.submit(fit_one, task)] = task
        if not active:
            raise RuntimeError("No admitted fit; stop without changing the task")
        finished, _ = wait(active, timeout=1, return_when=FIRST_COMPLETED)
        for future in finished:
            task = active.pop(future)
            rec = future.result()
            if float(rec["peak_rss_bytes"]) >= 2.0 * 1024**3:
                raise RuntimeError("Worker exceeded CONF per-job 2 GiB ceiling")
            write_receipt(task, rec)
            records.append(rec)
    return records


def execute_stage(tasks, fit_one: Callable, write_receipt: Callable,
                  permit: ExecutionPermit, projected_worker_bytes: int, deadline: float):
    """Execution-task hook. A gate must verify freeze, inputs and authorization.

    This design task does not call this function. The callback must not return
    until the later feature/model-input freeze and execution receipt exist.
    """
    require_execution(permit)
    if tasks[0].task != "news":
        records = []
        for task in tasks:
            if time.monotonic() >= deadline:
                raise TimeoutError("Budget reached; incomplete run cannot be scored")
            rec = fit_one(task)
            if float(rec["peak_rss_bytes"]) >= 2.0 * 1024**3:
                raise RuntimeError("Serial job exceeded CONF 2 GiB ceiling")
            write_receipt(task, rec)
            records.append(rec)
        return records
    grouped = {}
    for task in tasks:
        grouped.setdefault(task.origin, []).append(task)
    records = []
    ctx = mp.get_context("spawn")
    with ProcessPoolExecutor(max_workers=TARGET_WORKERS, mp_context=ctx, initializer=worker_init,
                             max_tasks_per_child=1) as pool:
        for origin in sorted(grouped):
            projected = projected_worker_bytes(origin, records) if callable(projected_worker_bytes) else projected_worker_bytes
            records.extend(run_news_origin(grouped[origin], pool, fit_one, write_receipt,
                                           projected, deadline, permit))
    return records


if __name__ == "__main__":
    # No command-line execution path is exposed in the design task.
    import json
    print(json.dumps(plan_counts(), indent=2))
