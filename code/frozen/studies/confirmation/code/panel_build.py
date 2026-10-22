"""CONF panel design adapters. No filesystem access or value build on import.

Timestamp helpers are executable on synthetic metadata. Scientific adapters need
a separately authorized execution permit; the current task supplies no permit.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, time, timedelta, timezone
from typing import Iterable, Mapping

try:
    from .guard import require_execution
except ImportError:
    from guard import require_execution

AEST = timezone(timedelta(hours=10), "AEST")
NEWS_REGIONS = ("NSW1", "QLD1", "TAS1")
NOTICE_REGIONS = ("NSW1", "QLD1", "SA1", "TAS1", "VIC1")
NOTICE_HORIZONS_MIN = (5, 10, 15, 20, 25, 30)
NEWS_START = date(2026, 3, 1)
NEWS_END = date(2026, 9, 30)
NEWS_SOURCE_START = date(2026, 2, 22)
NOTICE_START = date(2026, 8, 1)
NOTICE_END = date(2026, 9, 30)
NOTICE_LEADIN_START = date(2026, 7, 27)
NOTICE_SENSITIVITY_START = date(2026, 8, 8)
NOTICE_TRAIN_MONTHS = tuple(
    f"{year:04d}-{month:02d}"
    for year in (2021, 2022, 2023)
    for month in range(1, 13)
    if (year, month) >= (2021, 10)
)
KEY_ONLY_COLUMNS = frozenset({
    "REGIONID", "SETTLEMENTDATE", "RUNNO", "INTERVENTION", "LASTCHANGED",
    "RUN_DATETIME", "DATETIME", "region", "issue_time", "target_time",
    "horizon", "notice_id", "published_at", "modified_at", "captured_at",
})


@dataclass(frozen=True)
class ForecastKey:
    region: str
    issue_time: datetime
    target_time: datetime
    horizon: int


def aest_midnight(day: date) -> datetime:
    return datetime.combine(day, time.min, AEST)


def days_between(first: date, last: date) -> Iterable[date]:
    for offset in range((last - first).days + 1):
        yield first + timedelta(days=offset)


def news_keys() -> Iterable[ForecastKey]:
    """214 x 3 x 24 expected keys; targets are hour starts on issue day."""
    for day in days_between(NEWS_START, NEWS_END):
        issue = aest_midnight(day)
        for region in NEWS_REGIONS:
            for horizon in range(24):
                yield ForecastKey(region, issue, issue + timedelta(hours=horizon), horizon)


def notice_keys() -> Iterable[ForecastKey]:
    """61 x 288 x 5 x 6 keys, grouped by target AEST day as RF2/C.

    Midnight Aug1 targets require Jul31 issue times. Lead-in sources start Jul27.
    This generator performs no event selection and never samples window keys.
    """
    for day in days_between(NOTICE_START, NOTICE_END):
        for interval in range(288):
            target = aest_midnight(day) + timedelta(minutes=5 * interval)
            for region in NOTICE_REGIONS:
                for horizon in NOTICE_HORIZONS_MIN:
                    yield ForecastKey(region, target - timedelta(minutes=horizon), target, horizon)


def news_target_interval_ends(issue: datetime, horizon: int) -> tuple[datetime, ...]:
    if not 0 <= horizon < 24:
        raise ValueError("News target horizon must be 0..23")
    start = issue + timedelta(hours=horizon)
    return tuple(start + timedelta(minutes=5 * step) for step in range(1, 13))


def news_history_interval_ends(issue: datetime, lag: int) -> tuple[datetime, ...]:
    """NEWSD's five-minute-offset hourly history, not target-hour aggregation."""
    if not 1 <= lag <= 72:
        raise ValueError("News history lag must be 1..72")
    return tuple(issue - timedelta(hours=lag) + timedelta(minutes=5 * step)
                 for step in range(12))


def conservative_price_clock(interval_end: datetime, lastchanged: datetime | None) -> datetime:
    if lastchanged is None:
        raise ValueError("Unproven LASTCHANGED: no fallback publication clock")
    return max(interval_end + timedelta(minutes=5), lastchanged)


def physical_proxy_clock(interval_end: datetime) -> datetime:
    return interval_end + timedelta(minutes=5)


def predictor_is_legal(available_at: datetime, issue: datetime) -> bool:
    return available_at <= issue


def news_training_day_is_legal(label_clocks: Iterable[datetime], issue: datetime) -> bool:
    clocks = tuple(label_clocks)
    return len(clocks) == 3 * 24 and all(clock < issue for clock in clocks)


def notice_training_membership(original_c_ids: Iterable[int], label_clocks: Mapping[int, datetime],
                               first_issue: datetime) -> tuple[int, ...]:
    """Preserve RF2 C membership, with B6 strictly-before clock gate.

    A membership mismatch stops execution. No opportunistic filtering or new
    2024--2026 train rows is allowed by this confirmation design.
    """
    ids = tuple(int(i) for i in original_c_ids)
    missing = [i for i in ids if i not in label_clocks]
    illegal = [i for i in ids if i in label_clocks and not label_clocks[i] < first_issue]
    if missing or illegal:
        raise ValueError(f"Frozen C train membership failed clock gate: missing={len(missing)}, illegal={len(illegal)}")
    return ids


def key_projection(columns: Iterable[str]) -> tuple[str, ...]:
    columns = tuple(columns)
    if not set(columns) <= KEY_ONLY_COLUMNS:
        raise PermissionError("Design-stage metadata projection contains non-key columns")
    return columns


def build_news_panel(permit=None, *, frozen_sources=None, adapter=None):
    """Later execution only: extend DAPANEL to Feb22--Sep30 plus JanFeb bridge.

    The adapter must stream frozen PRICE/REGIONSUM projections in <=10,000-row
    chunks; prove Oct1 00:00 price boundary, exact duplicate agreement and all
    15,408 news labels/clocks/weekly-naive keys before fitting. All 72 history
    slots use the helpers above; keep NaN and observed masks, never backfill.
    """
    require_execution(permit)
    if adapter is None or frozen_sources is None:
        raise NotImplementedError("Separate execution task must supply hash-bound DAPANEL streaming adapter")
    return adapter(frozen_sources, news_keys(), history_ends=news_history_interval_ends,
                   target_ends=news_target_interval_ends)


def build_notice_panel(permit=None, *, frozen_sources=None, adapter=None, e3=False):
    """Later execution only: full RF2/B4/B6 keys and unit evaluation weights.

    Adapter must reuse strict B4 sequence/graph semantics and RF2 fixed numeric
    order, and must enforce source availability <= issue. It cannot call the
    legacy whole-archive oos_bank reader or create event-selected test keys.
    P5MIN is loaded only when e3=True under the separately frozen E3 adapter.
    """
    require_execution(permit)
    if adapter is None or frozen_sources is None:
        raise NotImplementedError("Separate execution task must supply hash-bound RF2/B4/B6 streaming adapter")
    return adapter(frozen_sources, notice_keys(), leadin_start=NOTICE_LEADIN_START,
                   unit_evaluation_weights=True, p5min_allowed=bool(e3))


if __name__ == "__main__":
    raise SystemExit("CONF DESIGN ONLY: panel value builds require a separate execution task")
