'Prepare word-frequency features, fit the models and save forecast hashes.'
from __future__ import annotations

import gc
import hashlib
import json
import os
import re
import resource
import sys
import time
from collections import Counter
from pathlib import Path

os.environ.setdefault("OPENBLAS_NUM_THREADS", "1")
os.environ.setdefault("MKL_NUM_THREADS", "1")
os.environ.setdefault("OMP_NUM_THREADS", "3")
sys.dont_write_bytecode = True

import numpy as np
import pandas as pd
import pyarrow.parquet as pq
from scipy.stats import f as f_distribution
from statsmodels.tsa.stattools import adfuller

OUT = Path(__file__).resolve().parent
PROJ = OUT.parents[3]
AUD = OUT.parents[1]
notice_fitting = AUD / 'notice_fitting'
B1B, forecast_replication = AUD / "B1b", AUD / 'forecast_replication'
REGISTRY = PROJ.parent.parent / "artifacts/pivot_bq/m463_corrected_notice_timing/corrected_notice_registry.csv"
KEYS = ["region", "issue_time", "target_time", "horizon"]
FOLDS = ("F1", "F2", "F3", "F4", "F5", "F6", "C")
ARMS = ("T", "T_P")
SEEDS = (20260919, 20260920, 20260921)
DAY_NS = 24 * 3600 * 10**9
SHIFT_NS = 28 * DAY_NS
START = time.monotonic()
MAX_RSS = int(1.5 * 1024**3)


def read(path):
    return json.loads(Path(path).read_text())


def sha(path):
    h = hashlib.sha256()
    with Path(path).open("rb") as stream:
        for block in iter(lambda: stream.read(1 << 20), b""):
            h.update(block)
    return h.hexdigest()


def write(path, data):
    path = Path(path)
    assert path.resolve().is_relative_to(OUT), path
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("x") as stream:
        json.dump(data, stream, indent=2, sort_keys=True, allow_nan=False, default=str)
        stream.write("\n")


def rss():
    value = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
    return int(value if sys.platform == "darwin" else value * 1024)


def log(stage, **extra):
    item = dict(stage=stage, elapsed_seconds=round(time.monotonic() - START, 3),
                peak_rss_bytes=rss(), **extra)
    with (OUT / "progress.jsonl").open("a") as stream:
        stream.write(json.dumps(item, default=str) + "\n")
    print(json.dumps(item, default=str), flush=True)
    if rss() > MAX_RSS:
        raise MemoryError('word_features peak RSS exceeded 1.5 GiB')


def frozen(full=False):
    receipt = read(OUT / "FREEZE.json")
    assert receipt["state"] == "TFN2_PREFIT_FROZEN"
    assert sha(OUT / "PROTOCOL_TFN2.md") == receipt["protocol_sha256"]
    for key, digest in receipt["code_sha256"].items():
        assert sha(OUT / key) == digest, ("frozen local file drift", key)
    if full:
        for key, digest in receipt["input_sha256"].items():
            assert sha(key) == digest, ("frozen input drift", key)
    assert not (OUT / "scoring" / "RESULT.json").exists() or not full
    return receipt


def design():
    return read(notice_fitting / "final/design.json")


def metadata(period, columns=None):
    return pd.read_parquet(B1B / f"{period}_metadata.parquet", columns=columns)


def population():
    reg = pd.read_csv(REGISTRY, usecols=["notice_id", "title", "text", "available_time_utc",
                                         "is_relevant_operational", "available_time_valid"])
    reg = reg.loc[reg.is_relevant_operational & reg.available_time_valid].copy()
    reg["notice_id"] = reg.notice_id.astype(str)
    assert not reg.notice_id.duplicated().any()
    reg["available_utc"] = pd.to_datetime(reg.available_time_utc, utc=True)
    reg["title"] = reg.title.fillna("").astype(str)
    reg["text"] = reg.text.fillna("").astype(str).str.replace(r"\s+", " ", regex=True)
    assert reg.available_utc.notna().all()
    return reg.sort_values(["available_utc", "notice_id"], kind="mergesort").reset_index(drop=True)


def stopwords():
    return frozenset((OUT / "english_stopwords.txt").read_text().splitlines())


def token_counts(value, stops):
    return Counter(token for token in re.findall(r"[a-z0-9]+", str(value).lower())
                   if len(token) >= 3 and not token.isdigit() and token not in stops)


def train_ids(fold):
    spec = design()["folds"][fold]
    for part in ("train", "test"):
        path = Path(spec[f"{part}_indices_path"])
        assert sha(path) == spec[f"{part}_indices_sha256"]
    return np.load(spec["train_indices_path"]), np.load(spec["test_indices_path"])


def price_daily(train):
    points = train[["region", "target_time", "y_true"]].drop_duplicates(["region", "target_time"])
    points = points.assign(day=points.target_time.dt.tz_convert("Australia/Brisbane").dt.floor("D"))
    average = points.groupby("day", sort=True).y_true.mean()
    days = pd.date_range(average.index.min(), average.index.max(), freq="D", tz="Australia/Brisbane")
    average = average.reindex(days)
    assert average.notna().all(), "missing training-price day; no interpolation allowed"
    return days, average.to_numpy("float64"), len(points)


def adf_series(x):
    x = np.asarray(x, dtype="float64")
    if not np.isfinite(x).all() or np.ptp(x) == 0:
        return None, dict(adf_p=None, differenced=False, reason="CONSTANT_OR_NONFINITE")
    try:
        p = float(adfuller(x, regression="c", autolag="AIC")[1])
        changed = bool(p >= .05)
        z = np.diff(x) if changed else x
        if np.ptp(z) == 0:
            return None, dict(adf_p=p, differenced=changed, reason="CONSTANT_AFTER_ADF")
        return z, dict(adf_p=p, differenced=changed, reason=None)
    except (ValueError, np.linalg.LinAlgError) as exc:
        return None, dict(adf_p=None, differenced=False, reason=type(exc).__name__)


def granger_p(target, predictor, lag=30):

    n = len(target)
    if n != len(predictor) or n - lag <= 2 * lag + 1:
        return None
    y = target[lag:]
    past_y = np.column_stack([target[lag-i:n-i] for i in range(1, lag+1)])
    past_x = np.column_stack([predictor[lag-i:n-i] for i in range(1, lag+1)])
    restricted = np.column_stack([np.ones(len(y)), past_y])
    full = np.column_stack([restricted, past_x])
    if np.linalg.matrix_rank(full) < full.shape[1]:
        return None
    br = np.linalg.lstsq(restricted, y, rcond=None)[0]
    bu = np.linalg.lstsq(full, y, rcond=None)[0]
    rss_r = float(np.square(y - restricted @ br).sum())
    rss_u = float(np.square(y - full @ bu).sum())
    df = len(y) - full.shape[1]
    if rss_u <= 0 or df <= 0:
        return None
    statistic = max(0.0, (rss_r - rss_u) / lag) / (rss_u / df)
    return float(f_distribution.sf(statistic, lag, df))


def selection_for(fold, meta, pop, stops):
    ids, _ = train_ids(fold)
    train = meta.iloc[ids]
    lower = train.issue_time.min() - pd.Timedelta(hours=24)
    upper = train.issue_time.max()
    past = pop.loc[(pop.available_utc > lower) & (pop.available_utc <= upper)].copy()
    days, prices, unique_points = price_daily(train)
    price_z, price_adf = adf_series(prices)
    assert price_z is not None, "training daily price not usable for Granger selection"
    stop = stops
    entries = []
    for field, threshold, column in (("title", 200, "title"), ("body", 5000, "text")):
        counts = [token_counts(value, stop) for value in past[column]]
        corpus = Counter()
        for c in counts:
            corpus.update(c)
        candidates = sorted(word for word, count in corpus.items() if count >= threshold)
        day_index = pd.DatetimeIndex(past.available_utc.dt.tz_convert("Australia/Brisbane").dt.floor("D"))
        offsets = days.get_indexer(day_index)
        word_days = np.zeros((len(days), len(candidates)), dtype="float64")
        lookup = {w: i for i, w in enumerate(candidates)}
        for offset, c in zip(offsets, counts):
            if offset < 0:
                continue
            for word, value in c.items():
                j = lookup.get(word)
                if j is not None:
                    word_days[offset, j] += value
        for j, word in enumerate(candidates):
            x, x_adf = adf_series(word_days[:, j])
            fwd = rev = None
            if x is not None:

                k = min(len(x), len(price_z))
                y_aligned, x_aligned = price_z[-k:], x[-k:]
                fwd = granger_p(y_aligned, x_aligned)
                rev = granger_p(x_aligned, y_aligned)
            selected = fwd is not None and rev is not None and fwd < .05 <= rev
            entries.append(dict(field=field, word=word, corpus_occurrences=int(corpus[word]),
                                threshold=threshold, adf=x_adf, p_word_to_price=fwd,
                                p_price_to_word=rev, selected=bool(selected)))
    selected = [f"{e['field']}__{e['word']}" for e in entries if e["selected"]]
    return dict(fold=fold, train_rows=len(ids), training_notice_rows=len(past),
                training_availability_start=str(lower), training_availability_end=str(upper),
                training_price_days=len(days), unique_region_target_points=unique_points,
                price_adf=price_adf, selected=selected,
                candidates_by_field={field: sum(e["field"] == field for e in entries)
                                     for field in ("title", "body")}, entries=entries)


def prepare():
    frozen(full=True)
    assert not (OUT / "SELECTION_SEAL.json").exists()
    meta = metadata("development", ["region", "issue_time", "target_time", "y_true"])
    pop = population()
    stops = stopwords()
    files = {}
    for fold in FOLDS:
        selection = selection_for(fold, meta, pop, stops)
        path = OUT / "selection" / f"{fold}.json"
        write(path, selection)
        assert sha(path) == sha(OUT.parent / "selection" / f"{fold}.json"), "selection changed under clock repair"
        files[fold] = dict(path=str(path), sha256=sha(path), selected=len(selection["selected"]),
                           candidates=len(selection["entries"]))
        log("selection_complete", fold=fold, selected=files[fold]["selected"],
            candidates=files[fold]["candidates"])
    clock_checks = {}
    c_issues = metadata("C", ["issue_time"]).issue_time
    for fold in FOLDS:
        ids, tids = train_ids(fold)
        selected = read(files[fold]["path"])["selected"]
        train_issue = meta.issue_time.iloc[ids]
        test_issue = c_issues.iloc[tids] if fold == "C" else meta.issue_time.iloc[tids]
        clock_checks[fold] = {}
        for arm in ARMS:
            train_words = text_features(train_issue, pop, selected, arm, stops)
            test_words = text_features(test_issue, pop, selected, arm, stops)
            train_nonzero = int(np.count_nonzero(train_words))
            test_nonzero = int(np.count_nonzero(test_words))
            assert train_nonzero > 0, (fold, arm, "selected training word windows are all zero")
            clock_checks[fold][arm] = dict(train_nonzero_cells=train_nonzero,
                                           test_nonzero_cells=test_nonzero,
                                           train_rows=len(ids), test_rows=len(tids),
                                           selected_columns=len(selected))
            del train_words, test_words
            gc.collect()
    write(OUT / "CLOCK_VALIDATION.json", dict(passed=True, clock_unit="nanoseconds",
                                              checks=clock_checks))
    del meta, pop
    gc.collect()
    write(OUT / "SELECTION_SEAL.json", dict(state="TFN2_SELECTIONS_SEALED_BEFORE_FIRST_FIT",
                                          freeze_sha256=sha(OUT / "FREEZE.json"), files=files,
                                          clock_validation_sha256=sha(OUT / "CLOCK_VALIDATION.json"),
                                          first_fit="F1/T/20260919"))
    log("selection_sealed", folds=len(files))


def selected_for(fold):
    seal = read(OUT / "SELECTION_SEAL.json")
    assert seal["freeze_sha256"] == sha(OUT / "FREEZE.json")
    assert sha(OUT / "CLOCK_VALIDATION.json") == seal["clock_validation_sha256"]
    assert read(OUT / "CLOCK_VALIDATION.json")["passed"]
    for f, entry in seal["files"].items():
        assert sha(entry["path"]) == entry["sha256"], f
    return read(seal["files"][fold]["path"])["selected"]


def text_features(issue, pop, selected, arm, stops):
    if not selected:
        return np.empty((len(issue), 0), dtype="float32")
    chosen = [(field, word) for field, word in (x.split("__", 1) for x in selected)]
    lookup = {(field, word): j for j, (field, word) in enumerate(chosen)}
    counts = np.zeros((len(pop), len(chosen)), dtype="int32")
    for i, row in enumerate(pop.itertuples(index=False)):
        for field, value in (("title", row.title), ("body", row.text)):
            for word, n in token_counts(value, stops).items():
                col = lookup.get((field, word))
                if col is not None:
                    counts[i, col] += n
    cumulative = np.zeros((len(pop)+1, len(chosen)), dtype="int32")
    cumulative[1:] = np.cumsum(counts, axis=0, dtype="int32")
    available = pop.available_utc.dt.as_unit("ns").astype("int64").to_numpy()
    if arm == "T_P":
        available = available + SHIFT_NS
    assert np.all(available[1:] >= available[:-1])
    assert available.min() > 10**18, "availability clock must be nanoseconds"
    issue_ns = issue.dt.as_unit("ns").astype("int64").to_numpy()
    assert issue_ns.min() > 10**18, "issue clock must be nanoseconds"
    right = np.searchsorted(available, issue_ns, side="right")
    left = np.searchsorted(available, issue_ns-DAY_NS, side="right")
    assert np.all(left <= right)
    output = (cumulative[right] - cumulative[left]).astype("float32")
    assert np.isfinite(output).all() and (output >= 0).all()
    return output


def price_cap(target):
    local = target.dt.tz_convert("Australia/Brisbane")
    tz = "Australia/Brisbane"
    return np.select([local < pd.Timestamp("2022-07-01", tz=tz),
                      local < pd.Timestamp("2023-07-01", tz=tz),
                      local < pd.Timestamp("2024-07-01", tz=tz)],
                     [15000., 15500., 16600.], 17500.)


def matrices(fold, arm, selected, pop, stops):
    spec = design()["folds"][fold]
    ids, tids = train_ids(fold)
    meta = metadata("development", KEYS+["y_true", "legal_anchor", "weight"])
    target_meta = metadata("C", KEYS+["legal_anchor"]) if fold == "C" else meta.iloc[tids]
    train_meta = meta.iloc[ids]
    names = spec["numeric_kept"] + ["wf_" + x for x in selected]
    numeric_names = design()["numeric_names"]
    num_idx = [numeric_names.index(n) for n in spec["numeric_kept"]]
    train_num = np.load(forecast_replication / "corrected_numeric.npy", mmap_mode="r")
    test_num = np.load(forecast_replication / ("numeric_C.npy" if fold == "C" else "corrected_numeric.npy"), mmap_mode="r")
    x = np.empty((len(ids), len(names)), dtype="float32")
    z = np.empty((len(tids), len(names)), dtype="float32")
    for first in range(0, len(ids), 20000):
        chunk = ids[first:first+20000]
        x[first:first+len(chunk), :len(num_idx)] = train_num[np.ix_(chunk, num_idx)]
    for first in range(0, len(tids), 20000):
        chunk = tids[first:first+20000]
        z[first:first+len(chunk), :len(num_idx)] = test_num[np.ix_(chunk, num_idx)]
    del train_num, test_num
    if selected:
        x[:, len(num_idx):] = text_features(train_meta.issue_time, pop, selected, arm, stops)
        z[:, len(num_idx):] = text_features(target_meta.issue_time, pop, selected, arm, stops)
    y = train_meta.y_true.to_numpy("float64")-train_meta.legal_anchor.to_numpy("float64")
    weight = train_meta.weight.to_numpy("float32")
    anchor = target_meta.legal_anchor.to_numpy("float64")
    caps = price_cap(target_meta.target_time)
    keys = target_meta[KEYS].reset_index(drop=True)
    reference = pd.read_parquet(notice_fitting / f"final/predictions/{fold}.parquet", columns=KEYS)
    assert reference.equals(keys), (fold, "test-key order differs")
    assert x.shape[1] == z.shape[1] == len(names)
    assert len(y) == len(weight) == len(x)
    return x, z, y, weight, anchor, caps, keys, names


def fit(fold, arm):
    assert fold in FOLDS and arm in ARMS
    frozen(full=True)
    assert read(OUT / "N_REPLAY.json")["passed"]
    assert not (OUT / "final/candidate_seal.json").exists()
    selected = selected_for(fold)
    pop, stops = population(), stopwords()
    x, z, y, weight, anchor, caps, keys, names = matrices(fold, arm, selected, pop, stops)
    del pop
    gc.collect()
    import lightgbm as lgb
    feature_hashes = dict(train=hashlib.sha256(x.tobytes()).hexdigest(),
                          test=hashlib.sha256(z.tobytes()).hexdigest(),
                          target=hashlib.sha256(y.tobytes()).hexdigest(),
                          weight=hashlib.sha256(weight.tobytes()).hexdigest())
    for seed in SEEDS:
        receipt_path = OUT / "receipts" / f"{fold}_{arm}_{seed}.json"
        if receipt_path.exists():
            prior = read(receipt_path)
            assert prior["feature_matrix_sha256"] == feature_hashes
            assert sha(prior["model_path"]) == prior["model_sha256"]
            assert sha(prior["prediction_path"]) == prior["prediction_sha256"]
            log("fit_verified_existing", fold=fold, arm=arm, seed=seed)
            continue
        model_path = OUT / "final/models" / f"{fold}_{arm}_s{seed}.txt"
        prediction_path = OUT / "final/seed_predictions" / f"{fold}_{arm}_s{seed}.parquet"
        assert not model_path.exists() and not prediction_path.exists(), "partial fit requires engineering review"
        if fold == "F1" and arm == "T" and seed == SEEDS[0]:
            assert not list((OUT / "receipts").glob("*.json")) if (OUT / "receipts").exists() else True
        t0 = time.monotonic()
        params = dict(design()["params_by_seed"][str(seed)])
        assert params.pop("n_jobs") == 6
        params["n_jobs"] = 3
        model = lgb.LGBMRegressor(**params).fit(x, y, sample_weight=weight, feature_name=names)
        model_path.parent.mkdir(parents=True, exist_ok=True)
        model.booster_.save_model(str(model_path))
        prediction = np.clip(anchor+model.booster_.predict(z, num_threads=3), -1000., caps).astype("float32")
        assert np.isfinite(prediction).all()
        pred = keys.copy()
        pred[f"{arm}_s{seed}"] = prediction
        prediction_path.parent.mkdir(parents=True, exist_ok=True)
        pred.to_parquet(prediction_path, index=False, compression="zstd")
        receipt = dict(fold=fold, arm=arm, seed=seed, counted_pilot=bool(fold == "F1" and arm == "T" and seed == SEEDS[0]),
                       freeze_sha256=sha(OUT / "FREEZE.json"), selection_seal_sha256=sha(OUT / "SELECTION_SEAL.json"),
                       model_path=str(model_path), model_sha256=sha(model_path),
                       prediction_path=str(prediction_path), prediction_sha256=sha(prediction_path),
                       train_rows=len(x), test_rows=len(z), text_features=len(selected), features=names,
                       feature_matrix_sha256=feature_hashes, params=params,
                       seconds=time.monotonic()-t0, peak_rss_bytes=rss())
        write(receipt_path, receipt)
        log("fit_complete", fold=fold, arm=arm, seed=seed, seconds=round(receipt["seconds"], 2),
            text_features=len(selected))
        del model, pred, prediction
        gc.collect()
    del x, z, y, weight
    gc.collect()


def seal():
    frozen(full=True)
    assert read(OUT / "N_REPLAY.json")["passed"]
    assert not (OUT / "final/candidate_seal.json").exists()
    records = {}
    for fold in FOLDS:
        refpath = notice_fitting / f"final/predictions/{fold}.parquet"
        refseal = read(notice_fitting / "final/candidate_seal.json")["files"][fold]
        assert sha(refpath) == refseal["sha256"]
        cols = KEYS + [f"{a}_s{s}" for a in ("N", "L", "R") for s in SEEDS] + ["N", "L", "R"]
        frame = pd.read_parquet(refpath, columns=cols)
        for arm in ARMS:
            seed_values = []
            for seed in SEEDS:
                receipt = read(OUT / "receipts" / f"{fold}_{arm}_{seed}.json")
                assert receipt["freeze_sha256"] == sha(OUT / "FREEZE.json")
                assert receipt["selection_seal_sha256"] == sha(OUT / "SELECTION_SEAL.json")
                assert sha(receipt["model_path"]) == receipt["model_sha256"]
                assert sha(receipt["prediction_path"]) == receipt["prediction_sha256"]
                part = pd.read_parquet(receipt["prediction_path"])
                assert part[KEYS].equals(frame[KEYS])
                values = part[f"{arm}_s{seed}"].to_numpy("float32")
                frame[f"{arm}_s{seed}"] = values
                seed_values.append(values.astype("float64"))
            frame[arm] = (sum(seed_values) / len(SEEDS)).astype("float32")
        assert not set(frame.columns).intersection({"y_true", "weight", "event_replay_flag"})
        path = OUT / "final/predictions" / f"{fold}.parquet"
        path.parent.mkdir(parents=True, exist_ok=True)
        assert not path.exists()
        frame.to_parquet(path, index=False, compression="zstd")
        records[fold] = dict(path=str(path), sha256=sha(path), rows=len(frame),
                             q90=design()["folds"][fold]["q90"], reference_sha256=sha(refpath))
        log("candidate_fold_sealed", fold=fold, rows=len(frame))
        del frame
        gc.collect()
    write(OUT / "final/candidate_seal.json",
          dict(state="TFN2_CANDIDATES_SEALED_BEFORE_SCORING", files=records,
               freeze_sha256=sha(OUT / "FREEZE.json"),
               protocol_sha256=sha(OUT / "PROTOCOL_TFN2.md"),
               selection_seal_sha256=sha(OUT / "SELECTION_SEAL.json"),
               n_replay_sha256=sha(OUT / "N_REPLAY.json"),
               test_scored_before_bank_seal=False, fits=42))
    log("all_candidates_sealed", fits=42)


if __name__ == "__main__":
    command = sys.argv[1]
    if command == "prepare":
        assert len(sys.argv) == 2
        prepare()
    elif command == "fit":
        assert len(sys.argv) == 4
        fit(sys.argv[2], sys.argv[3])
    elif command == "seal":
        assert len(sys.argv) == 2
        seal()
    else:
        raise SystemExit('usage: run_word_features.py prepare|fit FOLD ARM|seal')
