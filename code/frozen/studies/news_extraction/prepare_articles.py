'Build the article inventory from source metadata.'
from __future__ import annotations

import csv
import datetime as dt
import hashlib
from html.parser import HTMLParser
import io
import json
import os
from pathlib import Path
import re

HERE = Path(__file__).resolve().parent
PROJ = HERE.parents[2]
SOURCE_MANIFEST = PROJ / 'studies/NEWS2/A/source_manifest.csv'
BASE_START, BASE_END = "2021-09-30", "2025-12-31"
SEPTEMBER_START, SEPTEMBER_END = "2021-09-02", "2021-09-29"
M846_START, M846_END = "2025-12-30", "2026-02-27"
M846_DIR = PROJ.parent.parent / "artifacts/pivot_bq/m846_wattclarity_source_2024_2026"
M846_EXPECTED_SHA256 = "ac1a7b1448864a7ceba5acab5216eead554e8e74f933f66d961798dad55ac605"
REPORTED_OPTIONAL_MODIFIED_IDS = {"44764", "44773", "44783", "44800"}
SOURCE_ENDS = {
    "M917": "m917_wattclarity_source_2016_2024/raw_posts.json",
    "M162": "m162_wattclarity_llm_source_expansion/wattclarity_wp_posts_raw.json",
}


def sha_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def sha_file(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as fh:
        for block in iter(lambda: fh.read(1024 * 1024), b""):
            h.update(block)
    return h.hexdigest()


class _Plain(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.parts: list[str] = []
        self.hidden = 0

    def handle_starttag(self, tag, attrs):
        if tag in {"script", "style"}:
            self.hidden += 1
        elif tag in {"p", "br", "li", "div", "h1", "h2", "h3", "h4", "tr"}:
            self.parts.append(" ")

    def handle_endtag(self, tag):
        if tag in {"script", "style"} and self.hidden:
            self.hidden -= 1
        elif tag in {"p", "li", "div", "h1", "h2", "h3", "h4", "tr"}:
            self.parts.append(" ")

    def handle_data(self, data):
        if not self.hidden:
            self.parts.append(data)


def plain(value: str) -> str:
    parser = _Plain()
    parser.feed(value or "")
    parser.close()
    return " ".join("".join(parser.parts).split())


def article_text(post: dict) -> str:
    return plain(post["title"]["rendered"]) + "\n\n" + plain(post["content"]["rendered"])


def source_paths() -> dict[str, Path]:
    rows = list(csv.DictReader(SOURCE_MANIFEST.open(newline="")))
    paths = {}
    for name, suffix in SOURCE_ENDS.items():
        found = [Path(row["source_path"]) for row in rows if row["source_path"].endswith(suffix)]
        if len(found) != 1:
            raise RuntimeError(f"expected one source {name}, got {len(found)}")
        paths[name] = found[0]
    paths["M846"] = M846_DIR / "raw_posts.json"
    return paths


class ScopeConflict(ValueError):
    def __init__(self, conflicts: list[dict[str, object]]):
        self.conflicts = conflicts
        super().__init__(f"{len(conflicts)} non-identical M846 cross-library IDs")


def _nested(post: dict, field: str):
    value = post
    for key in field.split("."):
        value = value.get(key) if isinstance(value, dict) else None
    return value


def load_posts() -> tuple[dict[str, dict], dict[str, str], dict[str, str]]:
    seal = json.loads((HERE / "SCOPE_FREEZE_v2.json").read_text(encoding="utf-8"))
    if sha_file(SOURCE_MANIFEST) != seal["source_manifest_sha256"]:
        raise RuntimeError("M917/M162 source manifest differs from scope seal")
    receipt_path = M846_DIR / "ACQUISITION_COMPLETE.json"
    if sha_file(receipt_path) != seal["m846_acquisition_receipt_sha256"]:
        raise RuntimeError("M846 acquisition receipt differs from scope seal")
    receipt = json.loads(receipt_path.read_text(encoding="utf-8"))
    if receipt["raw_posts_sha256"] != M846_EXPECTED_SHA256:
        raise RuntimeError("M846 acquisition receipt raw-post hash differs from pinned value")
    paths = source_paths()
    by_id: dict[str, dict] = {}
    membership: dict[str, str] = {}
    digests = {}
    conflicts: list[dict[str, object]] = []
    reported_optional_modified: set[str] = set()
    for name in ("M917", "M162", "M846"):
        path = paths[name]
        digests[name] = sha_file(path)
        if digests[name] != seal["source_sha256"][name]:
            raise RuntimeError(f"raw source hash differs from scope seal: {name}")
        seen = set()
        for post in json.loads(path.read_text(encoding="utf-8")):
            ident = str(post["id"])
            if ident in seen:
                raise ValueError(f"within-library duplicate: {name}/{ident}")
            seen.add(ident)
            day = str(post.get("date", ""))[:10]
            selected = (BASE_START <= day <= BASE_END and name != "M846") or \
                (name == "M917" and SEPTEMBER_START <= day <= SEPTEMBER_END) or \
                (name == "M846" and M846_START <= day <= M846_END)
            if not selected:
                continue
            if ident in by_id:
                earlier = by_id[ident]
                if name == "M846":
                    fields = ["title.rendered", "content.rendered", "link", "date", "date_gmt", "modified_gmt"]
                    differing = [field for field in fields if _nested(earlier, field) != _nested(post, field)]
                    if earlier.get("modified") != post.get("modified"):
                        if ident in REPORTED_OPTIONAL_MODIFIED_IDS and earlier.get("modified") is None and isinstance(post.get("modified"), str) and not differing:
                            reported_optional_modified.add(ident)
                        else:
                            differing.append("modified")
                    if differing:
                        conflicts.append({"article_id": ident, "existing_libraries": membership[ident], "differing_fields": differing})
                        continue
                else:
                    fields = ["date", "date_gmt", "modified_gmt", "title", "content", "link"]
                    if any(earlier.get(f) != post.get(f) for f in fields):
                        raise ValueError(f"non-identical M917/M162 article: {ident}")
                membership[ident] += "|" + name
            else:
                by_id[ident] = post
                membership[ident] = name
    if conflicts:
        raise ScopeConflict(conflicts)
    if reported_optional_modified != REPORTED_OPTIONAL_MODIFIED_IDS:
        raise RuntimeError(f"reported optional modified conflicts drifted: {sorted(reported_optional_modified)}")
    return by_id, membership, digests


def utc_clock(value: str) -> dt.datetime | None:
    try:
        return dt.datetime.fromisoformat(value).replace(tzinfo=dt.timezone.utc)
    except (TypeError, ValueError):
        return None


def manifest_row(ident: str, post: dict, membership: str) -> dict[str, str | int]:
    pub, mod = utc_clock(post.get("date_gmt")), utc_clock(post.get("modified_gmt"))
    available = max(pub, mod) + dt.timedelta(minutes=5) if pub and mod else None
    body = article_text(post)
    return {
        "article_id": ident, "libraries": membership, "publication_local_date": post["date"][:10],
        "publication_utc": pub.isoformat() if pub else "", "modified_utc": mod.isoformat() if mod else "",
        "saved_version_available_utc": available.isoformat() if available else "",
        "title": plain(post["title"]["rendered"]), "link": post.get("link", ""),
        "article_text_sha256": sha_bytes(body.encode("utf-8")), "article_text_chars": len(body),
    }


def _csv_bytes(rows: list[dict[str, str | int]]) -> bytes:
    stream = io.StringIO(newline="")
    writer = csv.DictWriter(stream, fieldnames=list(rows[0]))
    writer.writeheader()
    writer.writerows(rows)
    return stream.getvalue().encode("utf-8")


def main() -> None:
    seal = json.loads((HERE / "SCOPE_FREEZE_v2.json").read_text(encoding="utf-8"))
    for name, expected in seal["files_sha256"].items():
        if sha_file(HERE / name) != expected:
            raise RuntimeError(f"scope freeze mismatch: {name}")
    if sha_file(HERE / "SCOPE_FREEZE.json") != seal["previous_freeze_sha256"]:
        raise RuntimeError("previous scope freeze differs")
    try:
        by_id, membership, digests = load_posts()
    except ScopeConflict as exc:
        conflict_path = HERE / "SCOPE_CONFLICTS_v2_unresolved.json"
        conflict_path.write_text(json.dumps({"state": "CONFLICT_ABORT", "conflicts": exc.conflicts}, indent=2, sort_keys=True) + "\n", encoding="utf-8")
        raise
    rows = []
    baseline = []
    for ident, post in by_id.items():
        day = str(post["date"])[:10]
        original_libraries = "|".join(lib for lib in membership[ident].split("|") if lib != "M846")
        if original_libraries and BASE_START <= day <= BASE_END:
            row = manifest_row(ident, post, original_libraries)
            baseline.append(row)
        else:
            row = manifest_row(ident, post, membership[ident])
        rows.append(row)
    baseline.sort(key=lambda r: (r["publication_local_date"], r["article_id"]))
    if sha_bytes(_csv_bytes(baseline)) != seal["previous_manifest_sha256"]:
        raise RuntimeError("original manifest rows/hash not reproduced")
    rows.sort(key=lambda r: (r["publication_local_date"], r["article_id"]))
    path = HERE / "article_manifest.csv"
    current_hash = sha_file(path)
    prior_counts_path = HERE / "SCOPE_COUNTS_v2.json"
    accepted_hashes = {seal["previous_manifest_sha256"]}
    if prior_counts_path.exists():
        accepted_hashes.add(json.loads(prior_counts_path.read_text(encoding="utf-8"))["manifest_sha256"])
    if current_hash not in accepted_hashes:
        raise RuntimeError('existing manifest differs from previous or specified seal')
    rendered = _csv_bytes(rows)
    temp = path.with_suffix(".csv.tmp")
    temp.write_bytes(rendered)
    os.replace(temp, path)
    overlap_m846 = sorted(ident for ident, libs in membership.items() if "M846" in libs and "|" in libs)
    years: dict[str, int] = {}
    for row in rows:
        year = row["publication_local_date"][:4]
        years[year] = years.get(year, 0) + 1
    counts = {
        "rule": "v1 scope plus M917 2021-09-02..29 and M846 2025-12-30..2026-02-27, WordPress local date inclusive",
        "previous_unique_articles": len(baseline), "unique_articles": len(rows),
        "additional_2021_september_articles": sum(SEPTEMBER_START <= r["publication_local_date"] <= SEPTEMBER_END for r in rows),
        "m846_selected_articles": sum("M846" in libs for libs in membership.values()),
        "m846_new_unique_articles": sum(libs == "M846" for libs in membership.values()),
        "m846_overlap_ids": overlap_m846,
        "m846_reported_optional_modified_conflict_ids": sorted(REPORTED_OPTIONAL_MODIFIED_IDS),
        "m846_other_conflicts": 0, "by_publication_year": years,
        "invalid_clocks": sum(not r["saved_version_available_utc"] for r in rows),
        "source_sha256": digests, "manifest_sha256": sha_file(path),
        "scope_freeze_v2_sha256": sha_file(HERE / "SCOPE_FREEZE_v2.json"),
        "previous_manifest_sha256": seal["previous_manifest_sha256"],
    }
    prior_counts_path.write_text(json.dumps(counts, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps(counts, ensure_ascii=False, sort_keys=True))


if __name__ == "__main__":
    main()
