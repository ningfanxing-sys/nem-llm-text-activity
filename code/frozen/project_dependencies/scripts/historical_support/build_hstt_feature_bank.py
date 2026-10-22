
'Build monthly target panels and sampled training features without P5MIN inputs.'
from __future__ import annotations

import hashlib
import json
import os
import re
import sys
from pathlib import Path

import duckdb
import numpy as np
import pandas as pd


ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / 'scripts/historical_support'))
from audit_historical_support import load_actuals


PRICE_PANEL = ROOT / "data/gold_issue_time_safe/pivot_h_model_panel_long_windows_5_55.parquet"
EVENT_MANIFEST = ROOT / 'reports/historical_support/event_bank/final_event_manifest.parquet'
STRUCTURAL = ROOT / "artifacts/features/pivot_w_structural_scarcity.parquet"
EXPERT_ROOT = ROOT / "reports/pivot_r/development/r2/expert_bank"
COMBINER_ROOT = ROOT / "reports/pivot_r/development/r2/combiners"
FCAS_ROOT = ROOT / "reports/pivot_al/fcas_reserve/monthly"
NETWORK_ROOT = ROOT / "reports/pivot_al/network/interconnector/monthly"
SCADA_ROOT = ROOT / "reports/pivot_al/scada/monthly"
NOTICE = ROOT / "artifacts/complementarity/notice_mechanism_v1_safe_keys.parquet"
OUT = ROOT / 'artifacts/historical_support/feature_bank'
REPORT = ROOT / 'reports/historical_support'
REGIONS = ("NSW1", "QLD1", "SA1", "TAS1", "VIC1")
HORIZONS = (5, 10, 15, 20, 25, 30)
NEIGHBOURS = {
    "QLD1": ("NSW1",),
    "NSW1": ("QLD1", "VIC1"),
    "VIC1": ("NSW1", "SA1", "TAS1"),
    "SA1": ("VIC1",),
    "TAS1": ("VIC1",),
}
PROHIBITED = re.compile(r"P5MIN|PREDISPATCHPRICE|operator.price", re.I)
KEYS = ["region", "issue_time", "target_time", "horizon"]
EXPERT_COLUMNS = [
    "W90_FILTERED",
    "W28_FILTERED",
    "W28_RAW",
    "W90_RAW",
    "S1_RESTRICTED_STRUCTURAL_LIGHTGBM",
    "DISTRIBUTIONAL_H0_Q50",
    "LEGAL_PERSISTENCE_STABILISER",
]
STRUCTURAL_COLUMNS = [
    "legal_anchor", "A2_14D", "price_lag_5m", "price_lag_10m",
    "price_lag_30m", "price_lag_60m", "ramp_5m", "ramp_10m", "ramp_30m",
    "ramp_60m", "recent_volatility", "observed_pos300", "observed_pos1000",
    "observed_pos5000", "pos300_cluster_length", "pos1000_cluster_length",
    "pos5000_cluster_length", "minutes_since_pos300", "minutes_since_pos1000",
    "minutes_since_pos5000", "pos300_count_30m", "pos300_count_60m",
    "pos300_count_360m", "pos1000_count_30m", "pos1000_count_60m",
    "pos1000_count_360m", "pos5000_count_30m", "pos5000_count_60m",
    "pos5000_count_360m", "other_region_pos300_lag0m", "other_region_pos300_lag5m",
    "other_region_pos300_lag10m", "other_region_pos1000_lag0m",
    "other_region_pos1000_lag5m", "other_region_pos1000_lag10m",
    "other_region_pos5000_lag0m", "other_region_pos5000_lag5m",
    "other_region_pos5000_lag10m", "issue_hour_sin", "issue_hour_cos",
    "weekday_sin", "weekday_cos", "month_sin", "month_cos", "pv_power_latest",
    "pv_ramp_30m", "pv_ramp_60m", "pv_roll_mean_1h", "pv_roll_std_1h",
    "pv_roll_mean_6h", "pv_roll_std_6h", "pv_source_age_minutes",
    "pv_measurement_age_minutes", "pv_source_complete",
]
FCAS_COLUMNS = [
    "region_totaldemand", "region_availablegeneration", "region_demandforecast",
    "region_dispatchablegeneration", "region_netinterchange", "region_reserve_margin",
    "region_supply_demand_gap", "region_fcas_local_dispatch_sum",
    "region_fcas_local_requirement_sum", "region_fcas_scarcity_ratio",
]
NETWORK_COLUMNS = [
    "network_metered_flow_abs_sum", "network_flow_abs_sum", "network_flow_abs_max",
    "network_losses_sum", "network_violation_count", "network_violation_sum",
    "network_export_headroom_min", "network_import_headroom_min",
    "network_utilisation_max", "network_marginal_abs_sum",
]
SCADA_COLUMNS = [
    "total_scada_mw", "unit_count", "lost_mw_5m", "lost_mw_10m", "lost_mw_15m",
    "lost_mw_30m", "renewable_lost_mw_5m", "thermal_lost_mw_5m",
    "simultaneous_drop25_count", "simultaneous_drop50_count",
    "simultaneous_drop100_count", "worst_unit_delta_5m",
]
NOTICE_COLUMNS = [
    "notice_count_region_relevant_60m", "notice_count_region_relevant_360m",
    "notice_count_lor_reserve_60m", "notice_count_constraint_60m",
    "notice_count_interconnector_60m", "notice_count_outage_60m",
    "notice_count_weather_60m", "notice_count_system_security_60m",
    "notice_severity_max_60m", "notice_time_since_last_all_min",
]


class FeatureError(RuntimeError):
    pass


def atomic_parquet(path: Path, frame: pd.DataFrame) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(f".{path.name}.tmp.{os.getpid()}")
    frame.to_parquet(tmp, index=False, compression="zstd")
    os.replace(tmp, path)


def atomic_json(path: Path, value: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(f".{path.name}.tmp.{os.getpid()}")
    tmp.write_text(json.dumps(value, indent=2, sort_keys=True, default=str) + "\n", encoding="utf-8")
    os.replace(tmp, path)


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def timestamp_ns(values: pd.Series) -> np.ndarray:

    return pd.to_datetime(values, utc=True).to_numpy(dtype="datetime64[ns]").astype(np.int64)


def assert_safe_path(path: Path) -> None:
    if PROHIBITED.search(str(path)):
        raise FeatureError(f"operator-price source prohibited: {path}")


def read_month(path: Path, month: str, columns: list[str]) -> pd.DataFrame:
    start = pd.Timestamp(f"{month}-01", tz="Australia/Brisbane")
    end = start + pd.offsets.MonthBegin(1)
    return pd.read_parquet(
        path,
        columns=columns,
        filters=[("target_time", ">=", start.tz_convert("UTC")), ("target_time", "<", end.tz_convert("UTC"))],
    )


def event_blocks() -> pd.DataFrame:
    events = pd.read_parquet(EVENT_MANIFEST)
    events = events.loc[events["threshold"].eq("GT300")]
    rows: list[tuple[str, pd.Timestamp, str]] = []
    for item in events.itertuples(index=False):
        for stamp in pd.date_range(
            pd.Timestamp(item.start) - pd.Timedelta(minutes=30),
            pd.Timestamp(item.end) + pd.Timedelta(minutes=30),
            freq="5min",
        ):
            rows.append((str(item.region), stamp.tz_convert("UTC"), str(item.system_event_id)))
    frame = pd.DataFrame(rows, columns=["region", "target_time", "event_block_id"])
    return frame.sort_values(["region", "target_time", "event_block_id"], kind="mergesort").drop_duplicates(
        ["region", "target_time"], keep="first"
    )


class PriceHistory:
    def __init__(self) -> None:
        actuals, _, _ = load_actuals()
        self.by_region: dict[str, tuple[np.ndarray, np.ndarray, np.ndarray]] = {}
        price_rows = []
        for region, part in actuals.groupby("region", observed=True, sort=True):
            part = part.sort_values("event_time", kind="mergesort")
            available = timestamp_ns(part["earliest_label_available_time"])
            event_time = timestamp_ns(part["event_time"])
            price = part["price"].to_numpy(dtype=np.float32)
            self.by_region[str(region)] = (available, event_time, price)
            price_rows.append(
                pd.DataFrame(
                    {
                        "region": str(region),
                        "event_time": pd.to_datetime(event_time, utc=True),
                        "label_available_time": pd.to_datetime(available, utc=True),
                        "price": price,
                    }
                )
            )
        atomic_parquet(OUT / "canonical_price_series.parquet", pd.concat(price_rows, ignore_index=True))

    def attach(self, frame: pd.DataFrame) -> pd.DataFrame:
        output = frame.copy()
        sequence = np.zeros((len(output), 24), dtype=np.float32)
        sequence_mask = np.zeros(len(output), dtype=np.float32)
        issue_ns = timestamp_ns(output["issue_time"])
        for region, positions in output.groupby("region", observed=True, sort=False).indices.items():
            positions = np.asarray(positions, dtype=int)
            available, event_time, price = self.by_region[str(region)]
            last = np.searchsorted(available, issue_ns[positions], side="right") - 1
            indices = last[:, None] - np.arange(23, -1, -1, dtype=int)[None, :]
            valid = (indices[:, 0] >= 0) & (last >= 0)
            safe = np.clip(indices, 0, len(price) - 1)
            values = price[safe]
            if valid.any():
                times = event_time[safe[valid]]
                continuous = np.all(np.diff(times, axis=1) == 300_000_000_000, axis=1)
                valid_positions = np.flatnonzero(valid)
                valid[valid_positions[~continuous]] = False
            fallback = output.iloc[positions]["legal_anchor"].to_numpy(dtype=np.float32)
            values[~valid] = fallback[~valid, None]
            sequence[positions] = values
            sequence_mask[positions] = valid.astype(np.float32)
        for index in range(24):
            output[f"price_seq_{index:02d}"] = sequence[:, index]
        output["price_sequence_mask"] = sequence_mask
        output["price_seq_ramp_last"] = sequence[:, -1] - sequence[:, -2]
        output["price_seq_volatility"] = np.std(np.diff(sequence, axis=1), axis=1).astype(np.float32)
        return output


def attach_calendar(frame: pd.DataFrame) -> pd.DataFrame:
    output = frame.copy()
    local = pd.to_datetime(output["issue_time"], utc=True).dt.tz_convert("Australia/Brisbane")
    hour = local.dt.hour + local.dt.minute / 60.0
    output["calendar_hour_sin"] = np.sin(2 * np.pi * hour / 24).astype(np.float32)
    output["calendar_hour_cos"] = np.cos(2 * np.pi * hour / 24).astype(np.float32)
    output["calendar_weekday_sin"] = np.sin(2 * np.pi * local.dt.dayofweek / 7).astype(np.float32)
    output["calendar_weekday_cos"] = np.cos(2 * np.pi * local.dt.dayofweek / 7).astype(np.float32)
    output["calendar_month_sin"] = np.sin(2 * np.pi * (local.dt.month - 1) / 12).astype(np.float32)
    output["calendar_month_cos"] = np.cos(2 * np.pi * (local.dt.month - 1) / 12).astype(np.float32)
    output["region_code"] = output["region"].map({region: i for i, region in enumerate(REGIONS)}).astype("int8")
    output["horizon_code"] = output["horizon"].map({h: i for i, h in enumerate(HORIZONS)}).astype("int8")
    output["horizon_group"] = pd.cut(
        output["horizon"], bins=[0, 10, 20, 30], labels=[0, 1, 2]
    ).astype("int8")
    return output


def fill_structural_from_sequence(frame: pd.DataFrame) -> pd.DataFrame:

    output = frame.copy()
    sequence = output[[f"price_seq_{index:02d}" for index in range(24)]].to_numpy(dtype=np.float32)
    defaults: dict[str, np.ndarray | float] = {
        "legal_anchor": sequence[:, -1],
        "price_lag_5m": sequence[:, -2],
        "price_lag_10m": sequence[:, -3],
        "price_lag_30m": sequence[:, -7],
        "price_lag_60m": sequence[:, -13],
        "ramp_5m": sequence[:, -1] - sequence[:, -2],
        "ramp_10m": sequence[:, -1] - sequence[:, -3],
        "ramp_30m": sequence[:, -1] - sequence[:, -7],
        "ramp_60m": sequence[:, -1] - sequence[:, -13],
        "recent_volatility": np.std(np.diff(sequence, axis=1), axis=1),
        "observed_pos300": (sequence[:, -1] > 300).astype(np.float32),
        "observed_pos1000": (sequence[:, -1] > 1000).astype(np.float32),
        "observed_pos5000": (sequence[:, -1] > 5000).astype(np.float32),
        "pos300_count_30m": (sequence[:, -6:] > 300).sum(axis=1),
        "pos300_count_60m": (sequence[:, -12:] > 300).sum(axis=1),
        "pos300_count_360m": (sequence > 300).sum(axis=1),
        "pos1000_count_30m": (sequence[:, -6:] > 1000).sum(axis=1),
        "pos1000_count_60m": (sequence[:, -12:] > 1000).sum(axis=1),
        "pos1000_count_360m": (sequence > 1000).sum(axis=1),
        "pos5000_count_30m": (sequence[:, -6:] > 5000).sum(axis=1),
        "pos5000_count_60m": (sequence[:, -12:] > 5000).sum(axis=1),
        "pos5000_count_360m": (sequence > 5000).sum(axis=1),
    }
    for threshold in (300, 1000, 5000):
        mask = sequence > threshold
        reverse = mask[:, ::-1]
        any_seen = reverse.any(axis=1)
        since = np.where(any_seen, reverse.argmax(axis=1) * 5.0, 9999.0)
        run = np.zeros(len(output), dtype=np.float32)
        active = np.ones(len(output), dtype=bool)
        for offset in range(24):
            active &= reverse[:, offset]
            run += active.astype(np.float32)
        defaults[f"minutes_since_pos{threshold}"] = since
        defaults[f"pos{threshold}_cluster_length"] = run
    for column in STRUCTURAL_COLUMNS:
        if column == "A2_14D":
            continue
        if column not in output:
            output[column] = np.nan
        fallback = defaults.get(column, 0.0)
        output[column] = pd.to_numeric(output[column], errors="coerce").fillna(
            pd.Series(fallback, index=output.index) if isinstance(fallback, np.ndarray) else fallback
        )
    output["structural_source_mask"] = output.get("pv_source_complete", 0.0).fillna(0.0).astype(np.float32)
    return output


def attach_graph(frame: pd.DataFrame) -> pd.DataFrame:
    output = frame.copy()
    state = output[["issue_time", "region", "legal_anchor", "ramp_5m"]].drop_duplicates(
        ["issue_time", "region"]
    )
    lookup = state.set_index(["issue_time", "region"])[["legal_anchor", "ramp_5m"]]
    anchors = np.zeros(len(output), dtype=np.float32)
    ramps = np.zeros(len(output), dtype=np.float32)
    masks = np.zeros(len(output), dtype=np.float32)
    for region, positions in output.groupby("region", observed=True, sort=False).indices.items():
        positions = np.asarray(positions, dtype=int)
        issues = output.iloc[positions]["issue_time"]
        values = []
        for neighbour in NEIGHBOURS[str(region)]:
            key = pd.MultiIndex.from_arrays([issues, np.repeat(neighbour, len(issues))])
            values.append(lookup.reindex(key).to_numpy(dtype=np.float32))
        stack = np.stack(values, axis=0)
        valid = np.isfinite(stack).all(axis=(0, 2))
        mean = np.nanmean(stack, axis=0)
        anchors[positions] = np.nan_to_num(mean[:, 0], nan=0.0)
        ramps[positions] = np.nan_to_num(mean[:, 1], nan=0.0)
        masks[positions] = valid.astype(np.float32)
    output["graph_neighbor_anchor_mean"] = anchors
    output["graph_neighbor_ramp_mean"] = ramps
    output["graph_source_mask"] = masks
    return output


def merge_physical(frame: pd.DataFrame, month: str) -> pd.DataFrame:
    output = frame
    joins = [
        (FCAS_ROOT / f"{month}.parquet", FCAS_COLUMNS, "fcas"),
        (NETWORK_ROOT / f"{month}.parquet", NETWORK_COLUMNS, "network"),
        (SCADA_ROOT / f"{month}.parquet", SCADA_COLUMNS, "scada"),
    ]
    for path, columns, prefix in joins:
        assert_safe_path(path)
        if not path.exists():
            for column in columns:
                output[column] = 0.0
            output[f"{prefix}_source_mask"] = 0.0
            continue
        source = pd.read_parquet(path, columns=["region", "available_time", *columns])
        source["issue_time"] = pd.to_datetime(source.pop("available_time"), utc=True)
        source = source.sort_values(["region", "issue_time"]).drop_duplicates(
            ["region", "issue_time"], keep="last"
        )
        output = output.merge(source, on=["region", "issue_time"], how="left", validate="many_to_one")
        output[f"{prefix}_source_mask"] = output[columns].notna().any(axis=1).astype(np.float32)
        output[columns] = output[columns].fillna(0.0)
    return output


def merge_notices(frame: pd.DataFrame, month: str) -> pd.DataFrame:
    output = frame
    if NOTICE.exists() and month >= "2025-12":
        notices = read_month(NOTICE, month, [*KEYS, *NOTICE_COLUMNS])
        output = output.merge(notices, on=KEYS, how="left", validate="one_to_one")
        output["notice_source_mask"] = output[NOTICE_COLUMNS].notna().any(axis=1).astype(np.float32)
        output[NOTICE_COLUMNS] = output[NOTICE_COLUMNS].fillna(0.0)
    else:
        for column in NOTICE_COLUMNS:
            output[column] = 0.0
        output["notice_source_mask"] = 0.0
    return output


def target_month(month: str, history: PriceHistory) -> pd.DataFrame:
    expert_path = EXPERT_ROOT / f"{month}.parquet"
    combiner_path = COMBINER_ROOT / month / "predictions.parquet"
    for path in (expert_path, combiner_path, STRUCTURAL):
        assert_safe_path(path)
        if not path.exists():
            raise FeatureError(f"missing frozen target-free source: {path}")
    expert = pd.read_parquet(expert_path, columns=[*KEYS, *EXPERT_COLUMNS])
    combiner = pd.read_parquet(combiner_path, columns=[*KEYS, "C1_DELAYED_EXPONENTIAL"])
    structural = read_month(STRUCTURAL, month, [*KEYS, *STRUCTURAL_COLUMNS])
    output = expert.merge(combiner, on=KEYS, validate="one_to_one").merge(
        structural, on=KEYS, how="left", validate="one_to_one"
    )
    output = output.rename(columns={"C1_DELAYED_EXPONENTIAL": "LS_DASE"})
    output["legal_anchor"] = output.get("legal_anchor", pd.Series(np.nan, index=output.index)).fillna(
        output["LEGAL_PERSISTENCE_STABILISER"]
    )
    a2_raw = output.get("A2_14D", pd.Series(np.nan, index=output.index))
    output["a2_source_mask"] = a2_raw.notna().astype(np.float32)
    output["A2_14D"] = a2_raw.fillna(output["legal_anchor"])
    output["component_disagreement"] = output[EXPERT_COLUMNS].std(axis=1).astype(np.float32)
    output["ls_dase_source_mask"] = 1.0
    output = merge_physical(output, month)
    output = merge_notices(output, month)
    output = history.attach(output)
    output = fill_structural_from_sequence(output)
    output = attach_graph(output)
    output = attach_calendar(output)
    if output.duplicated(KEYS).any() or len(output) != len(expert):
        raise FeatureError(f"target key integrity failure for {month}")
    if any(PROHIBITED.search(column) for column in output.columns):
        raise FeatureError("operator-price column leaked into target feature bank")
    return output.sort_values(KEYS, kind="mergesort").reset_index(drop=True)


def fallback_training_features(frame: pd.DataFrame, history: PriceHistory) -> pd.DataFrame:
    output = frame.copy()
    output = output.rename(
        columns={
            "price_lag_5m_available": "price_lag_5m",
            "price_lag_10m_available": "price_lag_10m",
            "price_lag_30m_available": "price_lag_30m",
            "price_lag_60m_available": "price_lag_60m",
        }
    )
    output["A2_14D"] = output["legal_anchor"]
    output["ramp_5m"] = output["legal_anchor"] - output["price_lag_5m"]
    output["ramp_10m"] = output["legal_anchor"] - output["price_lag_10m"]
    output["ramp_30m"] = output["legal_anchor"] - output["price_lag_30m"]
    output["ramp_60m"] = output["legal_anchor"] - output["price_lag_60m"]
    output["recent_volatility"] = output[["legal_anchor", "price_lag_5m", "price_lag_10m", "price_lag_30m", "price_lag_60m"]].std(axis=1)
    output["observed_pos300"] = output["legal_anchor"].gt(300).astype(np.float32)
    output["observed_pos1000"] = output["legal_anchor"].gt(1000).astype(np.float32)
    output["observed_pos5000"] = output["legal_anchor"].gt(5000).astype(np.float32)
    for column in STRUCTURAL_COLUMNS:
        if column not in output:
            output[column] = 0.0
    output["LEGAL_PERSISTENCE_STABILISER"] = output["legal_anchor"]
    output["LS_DASE"] = output["legal_anchor"]
    for column in EXPERT_COLUMNS:
        if column not in output:
            output[column] = output["legal_anchor"]
    output["component_disagreement"] = 0.0
    output["ls_dase_source_mask"] = 0.0
    for column in [*FCAS_COLUMNS, *NETWORK_COLUMNS, *SCADA_COLUMNS, *NOTICE_COLUMNS]:
        output[column] = 0.0
    for prefix in ("fcas", "network", "scada", "notice"):
        output[f"{prefix}_source_mask"] = 0.0
    output = history.attach(output)
    output = attach_calendar(output)
    output = attach_graph(output)
    return output


def sample_training_month(month: str, blocks: pd.DataFrame, history: PriceHistory) -> pd.DataFrame:
    start = pd.Timestamp(f"{month}-01", tz="Australia/Brisbane").tz_convert("UTC")
    end = (pd.Timestamp(f"{month}-01", tz="Australia/Brisbane") + pd.offsets.MonthBegin(1)).tz_convert("UTC")
    connection = duckdb.connect()
    connection.execute("PRAGMA threads=1")
    connection.execute("PRAGMA memory_limit='2GB'")
    connection.execute("SET preserve_insertion_order=false")
    connection.register("event_blocks", blocks)
    path = str(PRICE_PANEL).replace("'", "''")
    query = f"""
        WITH physical AS (
          SELECT p.region, p.issue_time, p.target_time, p.horizon, p.y_true,
                 p.label_available_time, p.legal_anchor,
                 p.price_lag_5m_available, p.price_lag_10m_available,
                 p.price_lag_30m_available, p.price_lag_60m_available,
                 row_number() OVER (
                   PARTITION BY p.region,p.issue_time,p.target_time,p.horizon
                   ORDER BY CASE WHEN p.row_role='scored_historical_development' THEN 0 ELSE 1 END
                 ) AS physical_rank
          FROM read_parquet('{path}') p
          WHERE p.row_role IN ('training_support_shared','scored_historical_development')
            AND p.horizon IN (5,10,15,20,25,30)
            AND p.target_time >= TIMESTAMPTZ '{start.isoformat()}'
            AND p.target_time < TIMESTAMPTZ '{end.isoformat()}'
        )
        SELECT p.region, p.issue_time, p.target_time, p.horizon, p.y_true,
               p.label_available_time, p.legal_anchor,
               p.price_lag_5m_available, p.price_lag_10m_available,
               p.price_lag_30m_available, p.price_lag_60m_available,
               b.event_block_id
        FROM physical p
        LEFT JOIN event_blocks b
          ON p.region=b.region AND p.target_time=b.target_time
        WHERE p.physical_rank=1
          AND (b.event_block_id IS NOT NULL OR hash(p.region,p.issue_time,p.target_time,p.horizon)%50=0)
        ORDER BY p.issue_time,p.region,p.horizon
    """
    sampled = connection.execute(query).fetch_df()
    connection.close()
    for column in ("issue_time", "target_time", "label_available_time"):
        sampled[column] = pd.to_datetime(sampled[column], utc=True)
    if sampled.duplicated(KEYS).any():
        raise FeatureError(f"duplicate sampled training keys for {month}")
    target_path = OUT / "target" / f"{month}.parquet"
    if target_path.exists():
        target = pd.read_parquet(target_path)
        target_columns = [column for column in target if column not in KEYS]
        output = sampled.merge(target, on=KEYS, how="left", validate="one_to_one", suffixes=("", "_target"))
        available = output["LS_DASE"].notna()
        fallback = fallback_training_features(sampled.loc[~available].copy(), history) if (~available).any() else None
        if fallback is not None:
            for column in target_columns:
                output.loc[~available, column] = fallback[column].to_numpy()
    else:
        output = fallback_training_features(sampled, history)
    output["event_block_id"] = output["event_block_id"].fillna("")
    output["event_replay_flag"] = output["event_block_id"].ne("").astype(np.float32)
    output["label_gt300"] = output["y_true"].gt(300).astype(np.float32)
    output["label_gt1000"] = output["y_true"].gt(1000).astype(np.float32)
    output["label_gt3000"] = output["y_true"].gt(3000).astype(np.float32)
    output["label_gt5000"] = output["y_true"].gt(5000).astype(np.float32)
    output["target_delta_persistence"] = output["y_true"] - output["legal_anchor"]
    output["target_residual_lsdase"] = output["y_true"] - output["LS_DASE"]
    if any(PROHIBITED.search(column) for column in output.columns):
        raise FeatureError("operator-price column leaked into sampled training bank")
    return output.sort_values(KEYS, kind="mergesort").reset_index(drop=True)


def main() -> None:
    for path in (PRICE_PANEL, EVENT_MANIFEST, STRUCTURAL, EXPERT_ROOT, COMBINER_ROOT):
        assert_safe_path(path)
    history = PriceHistory()
    target_months = pd.period_range("2024-06", "2025-12", freq="M").astype(str).tolist()
    receipts = []
    for month in target_months:
        target = target_month(month, history)
        path = OUT / "target" / f"{month}.parquet"
        atomic_parquet(path, target)
        receipts.append(
            {"bank": "target", "month": month, "rows": len(target), "sha256": sha256(path), "truth_column": False}
        )
        print(json.dumps(receipts[-1]))

    blocks = event_blocks()
    training_months = pd.period_range("2021-10", "2025-12", freq="M").astype(str).tolist()
    for month in training_months:
        training = sample_training_month(month, blocks, history)
        path = OUT / "training" / f"{month}.parquet"
        atomic_parquet(path, training)
        receipts.append(
            {
                "bank": "training",
                "month": month,
                "rows": len(training),
                "event_rows": int(training["event_replay_flag"].sum()),
                "sha256": sha256(path),
                "truth_column": True,
            }
        )
        print(json.dumps(receipts[-1]))
    receipt_frame = pd.DataFrame(receipts)
    receipt_path = REPORT / "hstt/feature_bank_receipts.csv"
    receipt_path.parent.mkdir(parents=True, exist_ok=True)
    receipt_frame.to_csv(receipt_path, index=False)
    summary = {
        "status": "AZ_P5MIN_FREE_FEATURE_BANK_SEALED",
        "target_rows": int(receipt_frame.loc[receipt_frame.bank.eq("target"), "rows"].sum()),
        "training_rows": int(receipt_frame.loc[receipt_frame.bank.eq("training"), "rows"].sum()),
        "event_training_rows": int(receipt_frame.get("event_rows", pd.Series(dtype=float)).fillna(0).sum()),
        "target_months": len(target_months),
        "training_months": len(training_months),
        "p5min_access": "CLOSED_EVALUATOR_ONLY",
        "target_truth_columns": 0,
    }
    atomic_json(REPORT / "hstt/feature_bank_seal.json", summary)
    print(json.dumps(summary, indent=2))


if __name__ == "__main__":
    main()
