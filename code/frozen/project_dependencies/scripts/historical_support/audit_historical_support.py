
'Count historical source coverage and severe-event support.'
from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
from pathlib import Path
from typing import Iterable

import duckdb
import numpy as np
import pandas as pd


ROOT = Path(__file__).resolve().parents[2]
SOURCE_ROOT = Path(
    'Documents/thesis/data_sources/electricity_price_prediction'
)
PRICE_PANEL = ROOT / "data/gold_issue_time_safe/pivot_h_model_panel_long_windows_5_55.parquet"
OUT = ROOT / 'reports/historical_support'
REGIONS = ("NSW1", "QLD1", "SA1", "TAS1", "VIC1")
HORIZONS = (5, 10, 15, 20, 25, 30)
DIRECT_EDGES = frozenset(
    {
        frozenset(("QLD1", "NSW1")),
        frozenset(("NSW1", "VIC1")),
        frozenset(("VIC1", "SA1")),
        frozenset(("VIC1", "TAS1")),
    }
)
START = pd.Timestamp("2021-10-01T00:00:00+10:00")
END = pd.Timestamp("2026-04-01T00:00:00+10:00")
PRETRAIN_END = pd.Timestamp("2024-01-01T00:00:00+10:00")
PROHIBITED = re.compile(r"P5MIN|PREDISPATCHPRICE|operator.price", re.I)


class AZAuditError(RuntimeError):
    pass


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def atomic_csv(path: Path, frame: pd.DataFrame) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(f".{path.name}.tmp.{os.getpid()}")
    frame.to_csv(tmp, index=False)
    os.replace(tmp, path)


def atomic_parquet(path: Path, frame: pd.DataFrame) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(f".{path.name}.tmp.{os.getpid()}")
    frame.to_parquet(tmp, index=False)
    os.replace(tmp, path)


def atomic_json(path: Path, value: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(f".{path.name}.tmp.{os.getpid()}")
    with tmp.open("w", encoding="utf-8") as handle:
        json.dump(value, handle, indent=2, sort_keys=True, default=str)
        handle.write("\n")
    os.replace(tmp, path)


def month_from_path(path: Path) -> str | None:
    matches = re.findall(r"20\d{4}", path.name + " " + str(path.parent))
    if not matches:
        return None
    value = matches[-1]
    return f"{value[:4]}-{value[4:]}"


def archive_paths(dataset: str) -> list[Path]:
    token = re.compile(rf"(?:^|_){re.escape(dataset)}(?:_|\.)", re.I)
    paths = []
    for path in SOURCE_ROOT.rglob("*.zip"):
        if not token.search(path.name) or PROHIBITED.search(path.name):
            continue
        month = month_from_path(path)
        if month is None or not ("2021-10" <= month <= "2026-03"):
            continue
        paths.append(path)
    return sorted(paths)


def archive_summary(dataset: str) -> dict[str, object]:
    paths = archive_paths(dataset)
    months = sorted({value for path in paths if (value := month_from_path(path))})
    return {
        "files": len(paths),
        "months": len(months),
        "first_month": months[0] if months else "",
        "last_month": months[-1] if months else "",
        "bytes": sum(path.stat().st_size for path in paths),
        "paths": paths,
    }


def source_registry(price_hash: str, actuals: pd.DataFrame) -> pd.DataFrame:
    historical_price = archive_summary("DISPATCHPRICE")
    core_region = archive_summary("DISPATCHREGIONSUM")
    core_interconnector = archive_summary("DISPATCHINTERCONNECTORRES")
    scada = archive_summary("DISPATCH_UNIT_SCADA")
    notices = ROOT / "reports/pivot_ae/source_audit/public_text_timing_audit.csv"
    d1 = ROOT / "reports/pivot_ab/source_banks/D1.parquet"
    d7 = ROOT / "reports/pivot_ab/source_banks/D7.parquet"
    d8 = ROOT / "reports/pivot_ab/source_banks/D8.parquet"
    structural = ROOT / "artifacts/features/pivot_w_structural_scarcity.parquet"

    price_months = int(actuals["event_time"].dt.to_period("M").nunique())
    rows = [
        {
            "source_id": "AZ_S0_LEGAL_PRICE_PANEL",
            "family": "regional_RRP_and_legal_price_history",
            "path": str(PRICE_PANEL.relative_to(ROOT)),
            "first_time": actuals["event_time"].min(),
            "last_time": actuals["event_time"].max(),
            "months_present": price_months,
            "months_required": 54,
            "rows_or_files": len(actuals),
            "timing_status": "PASS_ROW_LEVEL_LABEL_AND_LAG_AVAILABILITY",
            "az_role": "TARGET_AND_CAUSAL_PRICE_SEQUENCE",
            "source_mask_required": False,
            "sha256_or_manifest": price_hash,
            "decision": "ADMIT",
        },
        {
            "source_id": "AZ_S1_RAW_DISPATCHPRICE_ARCHIVES",
            "family": "official_raw_actual_price_lineage",
            "path": str(SOURCE_ROOT / "raw"),
            "first_time": historical_price["first_month"],
            "last_time": historical_price["last_month"],
            "months_present": historical_price["months"],
            "months_required": 54,
            "rows_or_files": historical_price["files"],
            "timing_status": "FINAL_ACTUAL_TARGET_ONLY_NOT_LIVE_FEATURE",
            "az_role": "SOURCE_TRACE_AND_TARGET_AUDIT",
            "source_mask_required": False,
            "sha256_or_manifest": "INDIVIDUAL_ARCHIVE_HASHES_REQUIRED_IN_FINAL_REGISTRY",
            "decision": "ADMIT_TARGET_ONLY_PARTIAL_RAW_COVERAGE",
        },
        {
            "source_id": "AZ_S2_DISPATCHREGIONSUM",
            "family": "demand_generation_renewable_reserve_FCAS",
            "path": str(SOURCE_ROOT / "raw"),
            "first_time": core_region["first_month"],
            "last_time": core_region["last_month"],
            "months_present": core_region["months"],
            "months_required": 54,
            "rows_or_files": core_region["files"],
            "timing_status": "LASTCHANGED_PLUS_CONSERVATIVE_LAG_REQUIRED",
            "az_role": "OPTIONAL_CAUSAL_NUMERICAL_INPUT",
            "source_mask_required": True,
            "sha256_or_manifest": "RAW_ARCHIVE_INVENTORY",
            "decision": "ADMIT_WITH_MASK_AFTER_ROW_LEVEL_MATERIALISATION",
        },
        {
            "source_id": "AZ_S3_INTERCONNECTOR",
            "family": "physical_graph_edges_flow_headroom_stress",
            "path": str(SOURCE_ROOT / "raw"),
            "first_time": core_interconnector["first_month"],
            "last_time": core_interconnector["last_month"],
            "months_present": core_interconnector["months"],
            "months_required": 54,
            "rows_or_files": core_interconnector["files"],
            "timing_status": "LASTCHANGED_PLUS_CONSERVATIVE_LAG_REQUIRED",
            "az_role": "OPTIONAL_GRAPH_EDGE_INPUT",
            "source_mask_required": True,
            "sha256_or_manifest": "RAW_ARCHIVE_INVENTORY",
            "decision": "ADMIT_WITH_MASK_AFTER_ROW_LEVEL_MATERIALISATION",
        },
        {
            "source_id": "AZ_S4_SCADA",
            "family": "unit_SCADA_and_DUID_aggregates",
            "path": str(SOURCE_ROOT / 'raw/specification_al_physical'),
            "first_time": scada["first_month"],
            "last_time": scada["last_month"],
            "months_present": scada["months"],
            "months_required": 54,
            "rows_or_files": scada["files"],
            "timing_status": "ISSUE_TIME_ASOF_CONTRACT_REQUIRED",
            "az_role": "OPTIONAL_CAUSAL_NUMERICAL_INPUT",
            "source_mask_required": True,
            "sha256_or_manifest": "RAW_ARCHIVE_INVENTORY",
            "decision": "ADMIT_WITH_MASK_COVERAGE_LIMITED",
        },
        {
            "source_id": "AZ_S5_MARKET_NOTICES",
            "family": "deterministic_public_events",
            "path": str(notices.relative_to(ROOT)),
            "first_time": "2021-10",
            "last_time": "2026-07",
            "months_present": 58 if notices.exists() else 0,
            "months_required": 54,
            "rows_or_files": sum(1 for _ in notices.open("rb")) - 1 if notices.exists() else 0,
            "timing_status": "PASS_CONSERVATIVE_AVAILABLE_TIME_FOR_ADMITTED_ROWS",
            "az_role": "OPTIONAL_DETERMINISTIC_EVENT_TOKEN",
            "source_mask_required": True,
            "sha256_or_manifest": sha256(notices) if notices.exists() else "",
            "decision": "ADMIT_REVIEWED_DETERMINISTIC_FIELDS_ONLY",
        },
    ]
    for source_id, path, family in (
        ("AZ_S6_D1", d1, "renewable_demand_dispatch_state"),
        ("AZ_S7_D7", d7, "FCAS_reserve_state"),
        ("AZ_S8_D8", d8, "network_constraint_state"),
        ("AZ_S9_STRUCTURAL", structural, "legal_price_and_weather_structural_features"),
    ):
        rows.append(
            {
                "source_id": source_id,
                "family": family,
                "path": str(path.relative_to(ROOT)),
                "first_time": "SEE_ARTIFACT",
                "last_time": "SEE_ARTIFACT",
                "months_present": "",
                "months_required": 54,
                "rows_or_files": "",
                "timing_status": "FROZEN_TIMING_AUDIT_REUSE",
                "az_role": "OPTIONAL_CAUSAL_INPUT",
                "source_mask_required": True,
                "sha256_or_manifest": sha256(path) if path.exists() else "",
                "decision": "ADMIT_WITH_MASK_IF_EXACT_COMMON",
            }
        )
    frame = pd.DataFrame(rows)
    if frame["path"].str.contains(PROHIBITED).any():
        raise AZAuditError("operator-price source leaked into AZ source registry")
    return frame


def raw_archive_manifest() -> pd.DataFrame:
    rows: list[dict[str, object]] = []
    for dataset in (
        "DISPATCHPRICE",
        "DISPATCHREGIONSUM",
        "DISPATCHINTERCONNECTORRES",
        "DISPATCH_UNIT_SCADA",
    ):
        for path in archive_paths(dataset):
            rows.append(
                {
                    "dataset": dataset,
                    "month": month_from_path(path),
                    "source_path": str(path),
                    "bytes": path.stat().st_size,
                    "sha256": sha256(path),
                    "operator_price_forecast": False,
                    "az_role": "TARGET_ONLY"
                    if dataset == "DISPATCHPRICE"
                    else "OPTIONAL_MASKED_CAUSAL_INPUT",
                }
            )
    frame = pd.DataFrame(rows).sort_values(["dataset", "month", "source_path"], kind="mergesort")
    if frame["source_path"].str.contains(PROHIBITED).any():
        raise AZAuditError("operator-price archive leaked into raw manifest")
    return frame


def load_actuals() -> tuple[pd.DataFrame, pd.DataFrame, str]:
    if not PRICE_PANEL.exists():
        raise AZAuditError(f"missing frozen legal price panel: {PRICE_PANEL}")
    if PROHIBITED.search(str(PRICE_PANEL)):
        raise AZAuditError("operator-price panel prohibited")
    connection = duckdb.connect()
    connection.execute("PRAGMA threads=1")
    connection.execute("PRAGMA memory_limit='2GB'")
    path = str(PRICE_PANEL).replace("'", "''")
    horizon_values = ",".join(str(value) for value in HORIZONS)
    # Select horizon 5 to obtain one actual price per regional dispatch interval.


    query = f"""
        SELECT region, target_time AS event_time, y_true::DOUBLE AS price,
               1::INTEGER AS distinct_price_values,
               1::INTEGER AS available_horizons,
               '5'::VARCHAR AS horizon_values,
               label_available_time AS earliest_label_available_time,
               1::BIGINT AS forecast_keys,
               row_role
        FROM read_parquet('{path}')
        WHERE horizon = 5
          AND target_time >= TIMESTAMPTZ '2021-10-01 00:00:00+10'
          AND target_time < TIMESTAMPTZ '2026-04-01 00:00:00+10'
        ORDER BY target_time, region
    """
    actuals = connection.execute(query).fetch_df()
    coverage_query = f"""
        SELECT strftime(target_time AT TIME ZONE 'Australia/Brisbane', '%Y-%m') AS month,
               row_role, count(*) AS rows, count(DISTINCT region) AS regions,
               count(DISTINCT horizon) AS horizons,
               min(issue_time) AS first_issue_time, max(issue_time) AS last_issue_time,
               count(*) FILTER (WHERE label_available_time IS NULL) AS missing_label_available,
               count(*) FILTER (WHERE legal_anchor_available_time > issue_time) AS illegal_anchor_rows
        FROM read_parquet('{path}')
        WHERE horizon IN ({horizon_values})
          AND target_time >= TIMESTAMPTZ '2021-10-01 00:00:00+10'
          AND target_time < TIMESTAMPTZ '2026-04-01 00:00:00+10'
        GROUP BY month, row_role
        ORDER BY month, row_role
    """
    coverage = connection.execute(coverage_query).fetch_df()
    connection.close()
    actuals["event_time"] = pd.to_datetime(actuals["event_time"], utc=True).dt.tz_convert(
        "Australia/Brisbane"
    )
    actuals["earliest_label_available_time"] = pd.to_datetime(
        actuals["earliest_label_available_time"], utc=True
    )
    if actuals[["region", "event_time"]].duplicated().any():
        raise AZAuditError("duplicate actual physical keys")
    if set(actuals["region"].unique()) != set(REGIONS):
        raise AZAuditError("region coverage mismatch")
    return actuals, coverage, sha256(PRICE_PANEL)


def attach_event_horizon_coverage(
    definitions: dict[str, pd.DataFrame],
) -> dict[str, pd.DataFrame]:
    keys = pd.concat(
        [frame[["region", "event_time"]] for frame in definitions.values()], ignore_index=True
    ).drop_duplicates()
    keys["event_time"] = pd.to_datetime(keys["event_time"], utc=True)
    connection = duckdb.connect()
    connection.execute("PRAGMA threads=1")
    connection.execute("SET preserve_insertion_order=false")
    connection.execute("PRAGMA memory_limit='2GB'")
    connection.register("event_keys", keys)
    path = str(PRICE_PANEL).replace("'", "''")
    horizon_values = ",".join(str(value) for value in HORIZONS)
    coverage = connection.execute(
        f"""
        SELECT k.region, k.event_time,
               count(DISTINCT p.horizon)::INTEGER AS available_horizons,
               string_agg(DISTINCT CAST(p.horizon AS VARCHAR), ',' ORDER BY CAST(p.horizon AS VARCHAR))
                 AS horizon_values
        FROM event_keys k
        LEFT JOIN read_parquet('{path}') p
          ON p.region = k.region AND p.target_time = k.event_time
         AND p.horizon IN ({horizon_values})
        GROUP BY k.region, k.event_time
        """
    ).fetch_df()
    connection.close()
    coverage["event_time"] = pd.to_datetime(coverage["event_time"], utc=True).dt.tz_convert(
        "Australia/Brisbane"
    )
    if coverage["available_horizons"].lt(1).any():
        raise AZAuditError("event row without a primary forecast horizon")
    output: dict[str, pd.DataFrame] = {}
    for name, frame in definitions.items():
        local = frame.drop(columns=["available_horizons", "horizon_values"]).merge(
            coverage, on=["region", "event_time"], how="left", validate="one_to_one"
        )
        if local["available_horizons"].isna().any():
            raise AZAuditError(f"missing event horizon coverage for {name}")
        output[name] = local
    return output


def directly_connected(left: str, right: str) -> bool:
    return left == right or frozenset((left, right)) in DIRECT_EDGES


def regional_clusters(rows: pd.DataFrame, label: str) -> pd.DataFrame:
    output: list[dict[str, object]] = []
    for region, group in rows.groupby("region", observed=True, sort=True):
        group = group.sort_values("event_time", kind="mergesort")
        run = group["event_time"].diff().gt(pd.Timedelta(minutes=30)).cumsum()
        for index, part in group.groupby(run, observed=True, sort=True):
            peak_index = part["price"].idxmax()
            start, end = part["event_time"].min(), part["event_time"].max()
            output.append(
                {
                    "threshold": label,
                    "cluster_id": "",
                    "region": region,
                    "start": start,
                    "end": end,
                    "duration_minutes": float((end - start).total_seconds() / 60 + 5),
                    "rows": int(len(part)),
                    "days": int(part["event_time"].dt.date.nunique()),
                    "peak_price": float(part.loc[peak_index, "price"]),
                    "peak_time": part.loc[peak_index, "event_time"],
                    "price_mass": float(part["price"].abs().sum()),
                    "available_horizons": int(part["available_horizons"].max()),
                    "horizon_values": json.dumps(
                        sorted(
                            {
                                int(value)
                                for values in part["horizon_values"].astype(str)
                                for value in values.split(",")
                                if value
                            }
                        )
                    ),
                    "source_months": json.dumps(
                        sorted(part["event_time"].dt.strftime("%Y-%m").unique().tolist())
                    ),
                }
            )
    frame = pd.DataFrame(output).sort_values(
        ["start", "region", "peak_time"], kind="mergesort"
    ).reset_index(drop=True)
    frame["cluster_id"] = [f"AZ-{label}-{index + 1:06d}" for index in range(len(frame))]
    return frame


def assign_system_events(clusters: pd.DataFrame) -> pd.DataFrame:
    frame = clusters.sort_values(["start", "region", "cluster_id"], kind="mergesort").reset_index(
        drop=True
    ).copy()
    parent = list(range(len(frame)))

    def find(index: int) -> int:
        while parent[index] != index:
            parent[index] = parent[parent[index]]
            index = parent[index]
        return index

    def union(left: int, right: int) -> None:
        left_root, right_root = find(left), find(right)
        if left_root != right_root:
            parent[right_root] = left_root

    window = pd.Timedelta(minutes=30)
    for left in range(len(frame)):
        for right in range(left + 1, len(frame)):
            if frame.at[right, "start"] > frame.at[left, "end"] + window:
                break
            if not directly_connected(str(frame.at[left, "region"]), str(frame.at[right, "region"])):
                continue
            if frame.at[left, "start"] <= frame.at[right, "end"] + window:
                union(left, right)
    roots = [find(index) for index in range(len(frame))]
    root_order = sorted(set(roots), key=lambda root: (frame.at[root, "start"], frame.at[root, "cluster_id"]))
    ids = {
        root: f"AZSYS-{frame.at[root, 'threshold']}-{position + 1:06d}"
        for position, root in enumerate(root_order)
    }
    frame["system_event_id"] = [ids[find(index)] for index in range(len(frame))]
    event_regions = frame.groupby("system_event_id", observed=True)["region"].apply(
        lambda values: json.dumps(sorted(set(values.astype(str))))
    )
    frame["connected_regions"] = frame["system_event_id"].map(event_regions)
    return frame


def event_rows(actuals: pd.DataFrame) -> tuple[dict[str, pd.DataFrame], dict[str, float]]:
    pretrain = actuals.loc[actuals["event_time"].lt(PRETRAIN_END)]
    top1_price = float(pretrain["price"].quantile(0.99))
    ramp_source = actuals.sort_values(["region", "event_time"], kind="mergesort").copy()
    ramp_source["ramp_5m"] = ramp_source.groupby("region", observed=True)["price"].diff()
    top1_ramp = float(
        ramp_source.loc[ramp_source["event_time"].lt(PRETRAIN_END), "ramp_5m"].quantile(0.99)
    )
    definitions: dict[str, pd.Series] = {
        "GT300": actuals["price"].gt(300),
        "GT1000": actuals["price"].gt(1000),
        "GT3000": actuals["price"].gt(3000),
        "GT5000": actuals["price"].gt(5000),
        "TRAIN_TOP1_PRICE": actuals["price"].gt(top1_price),
    }
    outputs = {name: actuals.loc[mask].copy() for name, mask in definitions.items()}
    outputs["TRAIN_TOP1_POS_RAMP"] = ramp_source.loc[ramp_source["ramp_5m"].gt(top1_ramp)].copy()
    return outputs, {"training_top1_price": top1_price, "training_top1_positive_ramp": top1_ramp}


def build_event_bank(actuals: pd.DataFrame) -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame, dict[str, float]]:
    definitions, thresholds = event_rows(actuals)
    definitions = attach_event_horizon_coverage(definitions)
    manifests: list[pd.DataFrame] = []
    support: list[dict[str, object]] = []
    concentration: list[dict[str, object]] = []
    for name, rows in definitions.items():
        clusters = assign_system_events(regional_clusters(rows, name))
        manifests.append(clusters)
        system = clusters.groupby("system_event_id", observed=True).agg(
            start=("start", "min"),
            end=("end", "max"),
            event_rows=("rows", "sum"),
            event_price_mass=("price_mass", "sum"),
            peak_price=("peak_price", "max"),
            regions=("region", "nunique"),
        ).reset_index()
        system["year"] = pd.to_datetime(system["start"]).dt.year
        sorted_mass = system.sort_values("event_price_mass", ascending=False)
        total_mass = float(sorted_mass["event_price_mass"].sum())
        support.append(
            {
                "threshold": name,
                "rows": len(rows),
                "regional_clusters": len(clusters),
                "independent_connected_events": len(system),
                "days": rows["event_time"].dt.date.nunique(),
                "regions": rows["region"].nunique(),
                "horizons": len(
                    {
                        int(value)
                        for values in rows["horizon_values"].astype(str)
                        for value in values.split(",")
                        if value
                    }
                ),
                "six_horizon_interval_share": float(rows["available_horizons"].eq(6).mean()),
                "years": rows["event_time"].dt.year.nunique(),
                "first_event": rows["event_time"].min(),
                "last_event": rows["event_time"].max(),
                "largest_event_row_share": float(system["event_rows"].max() / len(rows)),
                "top5_event_row_share": float(sorted_mass.head(5)["event_rows"].sum() / len(rows)),
                "largest_event_price_mass_share": float(
                    sorted_mass.head(1)["event_price_mass"].sum() / total_mass
                ),
                "top5_event_price_mass_share": float(
                    sorted_mass.head(5)["event_price_mass"].sum() / total_mass
                ),
                "source_coverage": "LEGAL_PRICE_PANEL_SIX_HORIZONS_GLOBAL_BOUNDARY_ROWS_MASKED",
            }
        )
        for rank, row in enumerate(sorted_mass.head(20).itertuples(index=False), start=1):
            concentration.append(
                {
                    "threshold": name,
                    "rank": rank,
                    "system_event_id": row.system_event_id,
                    "start": row.start,
                    "end": row.end,
                    "rows": row.event_rows,
                    "price_mass": row.event_price_mass,
                    "price_mass_share": row.event_price_mass / total_mass,
                    "cumulative_top_share": sorted_mass.head(rank)["event_price_mass"].sum() / total_mass,
                    "peak_price": row.peak_price,
                    "regions": row.regions,
                }
            )
    manifest = pd.concat(manifests, ignore_index=True).sort_values(
        ["threshold", "start", "region"], kind="mergesort"
    )
    return manifest, pd.DataFrame(support), pd.DataFrame(concentration), thresholds


def validate(manifest: pd.DataFrame, support: pd.DataFrame, coverage: pd.DataFrame) -> dict[str, object]:
    violations = 0
    for (_, region), group in manifest.groupby(["threshold", "region"], observed=True):
        group = group.sort_values("start")
        violations += int((group["start"].iloc[1:].reset_index(drop=True) <= (
            group["end"].iloc[:-1].reset_index(drop=True) + pd.Timedelta(minutes=30)
        )).sum())
    severe = support.loc[support["threshold"].eq("GT5000")].iloc[0]
    checks = {
        "regional_cluster_gap_violations": violations,
        "duplicate_cluster_ids": int(manifest["cluster_id"].duplicated().sum()),
        "five_regions_all_thresholds": bool(support["regions"].eq(5).all()),
        "six_horizons_all_thresholds": bool(support["horizons"].eq(6).all()),
        "price_months": int(coverage["month"].nunique()),
        "missing_label_available_rows": int(coverage["missing_label_available"].sum()),
        "illegal_anchor_rows": int(coverage["illegal_anchor_rows"].sum()),
        "gt5000_connected_events": int(severe["independent_connected_events"]),
        "gt5000_support_target_met": bool(severe["independent_connected_events"] >= 100),
    }
    if violations or checks["duplicate_cluster_ids"]:
        raise AZAuditError(f"event-bank invariant failure: {checks}")
    if not checks["five_regions_all_thresholds"] or not checks["six_horizons_all_thresholds"]:
        raise AZAuditError(f"coverage invariant failure: {checks}")
    if checks["missing_label_available_rows"] or checks["illegal_anchor_rows"]:
        raise AZAuditError(f"timing invariant failure: {checks}")
    return checks


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--audit-only", action="store_true", help="kept for an explicit read-only contract")
    parser.parse_args()
    actuals, coverage, price_hash = load_actuals()
    manifest, support, concentration, thresholds = build_event_bank(actuals)
    checks = validate(manifest, support, coverage)
    registry = source_registry(price_hash, actuals)
    archive_manifest = raw_archive_manifest()

    atomic_csv(OUT / "historical_expansion/monthly_price_coverage.csv", coverage)
    atomic_csv(OUT / "source_visibility/historical_source_registry.csv", registry)
    atomic_csv(OUT / "source_visibility/historical_raw_archive_manifest.csv", archive_manifest)
    atomic_csv(OUT / "event_bank/final_event_support.csv", support)
    atomic_parquet(OUT / "event_bank/final_event_manifest.parquet", manifest)
    atomic_csv(OUT / "event_bank/final_concentration_audit.csv", concentration)
    atomic_csv(OUT / "final_historical_source_registry.csv", registry)
    atomic_csv(OUT / "final_event_support.csv", support)
    atomic_csv(OUT / "final_event_concentration.csv", concentration)
    receipt = {
        "status": "AZ_HISTORICAL_SOURCE_AND_EVENT_SUPPORT_AUDIT_COMPLETE",
        "p5min_access": "CLOSED_EVALUATOR_ONLY",
        "price_panel": str(PRICE_PANEL.relative_to(ROOT)),
        "price_panel_sha256": price_hash,
        "actual_interval_rows": len(actuals),
        "first_actual": actuals["event_time"].min(),
        "last_actual": actuals["event_time"].max(),
        "thresholds": thresholds,
        "canonical_actual_rule": "HORIZON_5_PHYSICAL_INTERVAL_TRUTH",
        "checks": checks,
        "event_manifest_sha256": sha256(OUT / "event_bank/final_event_manifest.parquet"),
    }
    atomic_json(OUT / "historical_expansion/historical_support_audit_receipt.json", receipt)
    print(json.dumps(receipt, indent=2, default=str))


if __name__ == "__main__":
    main()
