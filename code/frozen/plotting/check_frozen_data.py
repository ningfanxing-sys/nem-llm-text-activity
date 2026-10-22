'Check saved figure inputs against their hashes and computation records.'
from __future__ import annotations
import argparse
import csv
from datetime import datetime, timedelta
import hashlib
import json
from pathlib import Path
HERE = Path(__file__).resolve().parent
PROJECT = HERE.parents[2]
DEFAULT_RESULTS = HERE.parent.parent / 'minrun_execution_20261010/t5_final/a13f/source_delivery_final/SCORE_ATTEMPT_DECLARED_ONLY/export/OFFICIAL_RESULTS.json'

def identity(path):
    body = path.read_bytes()
    return {'path': str(path.resolve()), 'sha256': hashlib.sha256(body).hexdigest(), 'bytes': len(body)}

def checked(path, expected):
    actual = identity(path)
    assert actual['sha256'] == expected['sha256'], f'Frozen hash mismatch: {path}'
    assert actual['bytes'] == expected['bytes'], f'Frozen size mismatch: {path}'
    return actual

def read_json(path):
    return json.loads(path.read_text(encoding='utf-8'))

def csv_rows(path):
    with path.open(newline='', encoding='utf-8') as stream:
        return list(csv.DictReader(stream))

def link(path, line=None):
    return f'[{path.name}](<{path.resolve()}{(':' + str(line) if line else '')}>)'

def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--project-root', type=Path, default=PROJECT)
    parser.add_argument('--results', type=Path, default=DEFAULT_RESULTS)
    args = parser.parse_args()
    audits = args.project_root / 'studies'
    official = read_json(args.results)
    checked(args.results, {'sha256': '7fce73ed9e11542e2ec7515e6448e37a4c12c9f60103bf5b899f908544b8b591', 'bytes': 62560216})
    sources = [identity(args.results)]
    clk_root = audits / 'confirmation/inference_design/CLK8'
    clk_path = clk_root / 'CLK8_RESULT.json'
    clk = read_json(clk_path)
    assert official['rows'][341]['slot_id'] == 'metadata/clk8'
    assert official['rows'][341]['value'] == clk, 'Official CLK8 metadata differs from frozen audit'
    sources.append(identity(clk_path))
    rows_path = clk_root / 'CLK8_ROWS.csv'
    sources.append(checked(rows_path, clk['rows_identity']))
    spec_path = audits / 'confirmation/inference_design/CLK8_SPEC.md'
    sources.append(checked(spec_path, clk['rule_identities']['CLK8_SPEC.md']))
    rows = csv_rows(rows_path)
    denominator = clk['coverage']['covered_notices']
    assert denominator == 712 == len(rows) == len({r['notice_id'] for r in rows})
    assert clk['coverage']['total_notices'] == 725
    assert clk['coverage']['uncovered_notices'] == 13
    clock_rows = []
    for r in rows:
        c, a, lo = (datetime.fromisoformat(r[key]) for key in ('C', 'A', 'L_lo'))
        assert all((t.utcoffset() == timedelta(hours=10) for t in (c, a, lo)))
        hi = lo + timedelta(minutes=1)
        c5 = c + timedelta(minutes=5)
        rounded = c5.replace(second=0, microsecond=0)
        if rounded < c5:
            rounded += timedelta(minutes=1)
        rounded += timedelta(minutes=-rounded.minute % 5)
        assert a == rounded
        assert (hi <= a) == (r['listed_by_admission_hi'] == 'True')
        assert (lo <= a) == (r['listed_by_admission_lo'] == 'True')
        assert abs((hi - c).total_seconds() / 60 - float(r['d_hi'])) < 1e-09
        clock_rows.append((r['month'], a, hi))
    coverage = []
    for delay in (0, 5, 15, 60):
        counts = {month: sum((m == month and hi <= a + timedelta(minutes=delay) for m, a, hi in clock_rows)) for month in ('2026-08', '2026-09')}
        total = sum(counts.values())
        coverage.append({'delay_minutes': delay, 'n': total, 'denominator': denominator, 'percent': 100 * total / denominator, 'by_month_n': counts})
    assert coverage[0]['n'] == clk['overall']['listed_by_admission_hi_n'] == 142
    assert coverage[0]['n'] / denominator == clk['overall']['listed_by_admission_hi_share']
    assert [c['n'] for c in coverage] == [142, 243, 402, 570]
    banks = {}
    for code in ('news_extraction', 'confirmation/newsx_extension'):
        root = audits / code
        receipt_path = root / 'EXTRACTION_RECEIPT.json'
        receipt = read_json(receipt_path)
        sources.append(identity(receipt_path))
        manifest_path = root / 'article_manifest.csv'
        manifest_identity = identity(manifest_path)
        assert manifest_identity['sha256'] == receipt['manifest_sha256']
        sources.append(manifest_identity)
        labels_identity = identity(root / 'labels.parquet')
        assert labels_identity['sha256'] == receipt['labels_sha256']
        sources.append(labels_identity)
        manifest = csv_rows(manifest_path)
        articles = {r['article_id']: r for r in manifest}
        assert len(manifest) == len(articles) == receipt['expected_unique_articles']
        failed = set(map(str, receipt['failed_article_ids']))
        assert failed <= articles.keys()
        assert len(failed) == receipt['failures']
        assert len(articles) - len(failed) == receipt['successful']
        banks[code] = {'root': root, 'articles': articles, 'receipt': receipt, 'failed': failed}
    old, new = (banks['news_extraction'], banks['confirmation/newsx_extension'])
    overlap = sorted(old['articles'].keys() & new['articles'].keys(), key=int)
    assert len(overlap) == 24
    fields = ('article_text_sha256', 'publication_utc', 'modified_utc', 'saved_version_available_utc')
    for aid in overlap:
        left, right = (old['articles'][aid], new['articles'][aid])
        assert left['publication_local_date'][:7] == right['publication_local_date'][:7] == '2026-02'
        assert all((left[k] == right[k] for k in fields))
        assert aid not in old['failed'] and aid not in new['failed']
    assert all(('2026-03' <= r['publication_local_date'][:7] <= '2026-09' for aid, r in new['articles'].items() if aid not in overlap))
    distinct = len(old['articles'].keys() | new['articles'].keys())
    assert distinct == 2244 + 286 - 24 == 2506
    conf = audits / 'confirmation/execution'
    adapter_path = conf / 'features_adapter.py'
    freeze_path = conf / 'ADAPTER_FREEZE.json'
    freeze = read_json(freeze_path)
    sources.append(checked(adapter_path, freeze['files']['features_adapter.py']))
    sources.append(identity(freeze_path))
    feature_spec = audits / 'confirmation/FEATURE_DEFINITIONS.md'
    sources.append(identity(feature_spec))
    adapter_lines = adapter_path.read_text().splitlines()
    ownership_line = next((i + 1 for i, line in enumerate(adapter_lines) if 'The original news_extraction bank owns duplicated immutable source' in line))
    assert 'for root,source in ((bank,posts),(extension,extra_posts)):' in adapter_path.read_text()
    assert 'else:result[aid]=article' in adapter_path.read_text()
    output = {'method': 'Read-only frozen row/manifest verification; no main-result recomputation', 'notice_coverage': coverage, 'news_distinct_articles': distinct, 'news_overlap_ids': overlap, 'news_overlap_month': '2026-02', 'news_selected_overlap_extraction': 'Historical news label bank', 'sources': sources}
    (HERE / 'DATA_CHECKS.json').write_text(json.dumps(output, ensure_ascii=False, indent=2) + '\n')
    coverage_table = '\n'.join((f'| a0{(' + ' + str(c['delay_minutes']) + '  minutes ' if c['delay_minutes'] else '')} | {c['by_month_n']['2026-08']} | {c['by_month_n']['2026-09']} | {c['n']}/712 | {c['percent']:.1f}% | {c['percent']:.6f}% |' for c in coverage))
    source_table = '\n'.join((f'| {link(Path(s['path']))} | {s['bytes']} | `{s['sha256']}` |' for s in sources))
    manifest_lines = '\n'.join((f'| `{aid}` | {old['articles'][aid]['publication_local_date']} | {next((i + 2 for i, r in enumerate(old['articles'].values()) if r['article_id'] == aid))} | {next((i + 2 for i, r in enumerate(new['articles'].values()) if r['article_id'] == aid))} |' for aid in overlap))
    text = f"# Input checks \n\n Reads the saved records 、 manifest 、 receipt 、 implementation and official export ； Text extractions are retained 、 feature construction 、 forecast fitting 、 scorer calls 、 tests or  bootstrap。 All output ／ files are in  `figures/`。O  denotes  {link(args.results)}，JSON  pointer array indices start at  0  onward 。\n\n## 1.  Notice listing coverage \n\n** Result ：a0、a0+5、a0+15、a0+60  minutes ， respective counts are  142、243、402、570  notices with conservative listing evidence ； the common denominator is the official set of  CLK8  of  712  matched notices 。**\n\n|  Time  | 8  listed notices in the month  | 9  listed notices in the month  |  full-period numerator ／ denominator  |  one decimal place  |  unrounded percentage  |\n|---|---:|---:|---:|---:|---:|\n{coverage_table}\n\n**a0  check passes ：142/712 = 0.199438202247191 = 19.9438202247191%， rounded to one decimal place  19.9%。**  The reconstructed numerator 、 proportion and flags match  `CLK8_RESULT.json`  and  O  exactly 。\n\n** Definition 。** a0  Yes  CSV  of  `A`， using fixed  AEST（UTC+10） under  `ceil5(C+5 minutes )`，`C`  is the saved notice's  Creation Date。 Directory listing clocks have minute precision ，CSV  of  `L_lo`  is the start of the displayed minute ； The specified  CLK8  conservative rule uses  `L_hi=L_lo+1 minutes `。 For delay  δ∈{{0,5,15,60}}， the counting condition is  `L_hi ≤ A+δ minutes `， including equality ； each notice  ID  is counted once 。 Only the time used for this check varies ， forecast admission rules and results remain fixed 。\n\n The evaluation window is  2026  year  8–9  month ，725  notices include  712  unique directory matches （8  month  246、9  month  466），13  unmatched notices 。 The denominator is  712， rather than  725， or the set including  7  lead-in notices from the month  796。 Unmatched notices imply neither listing ／ nor absence from the directory 。 Coverage describes listing evidence in the saved directory ， it does not establish official publication clocks or continuous live capture 。\n\n** Sources and checks 。**\n\n- {link(rows_path)}： number  1  is the header row ， number  2–713  rows contain all  712  records ； uses  `notice_id`、`month`、`C`、`A`、`L_lo`， and checks every record against  `listed_by_admission_hi`、`listed_by_admission_lo`  and  `d_hi`。 File  SHA-256、 bytes agree with the receipt  `/rows_identity`  match 。\n- {link(spec_path)}：§2  defines the window and  `A`，§3.2  defines  `L_hi`，§4  defines the primary conservative condition  `L_hi≤A`。 source  `d_hi`  bins measure  `L_hi−C`， Summing bins does not establish coverage relative to  `A`  of  +5/+15/+60  minute coverage 。\n- {link(clk_path)}：`/coverage/covered_notices=712`、`/coverage/total_notices=725`、`/coverage/uncovered_notices=13`、`/overall/listed_by_admission_hi_n=142`、`/overall/listed_by_admission_hi_share=0.199438202247191`； Monthly numerators are  `/by_month/2026-08/listed_by_admission_hi_n=46`  and  `/by_month/2026-09/listed_by_admission_hi_n=96`。\n- O：`/rows/341/slot_id=metadata/clk8`，`/rows/341/value`  agrees with the saved  `CLK8_RESULT.json`  in full ； The main denominator and  a0  numerator are respectively  `/rows/341/value/coverage/covered_notices`  and  `/rows/341/value/overall/listed_by_admission_hi_n`。+5/+15/+60  proportions are descriptive counts from the saved  CSV  data ， using the stored  CLK8  main results 。\n-  Using the lower minute bound  `L_lo≤A`，a0  is  164/712=23.0%， is the receipt's auxiliary permissive definition ； The main table uses the same  19.9%  upper-bound definition as the official result 。\n\n** Coverage statement 。** Among the 712 matched notices, conservative directory-listing evidence was available for 19.9% at proxy admission, rising to 34.1%, 56.5% and 80.1% at 5, 15 and 60 minutes after that admission time, respectively.\n\n## 2.  Distinct articles and duplicate extraction ownership \n\n** Conclusion ： The difference consists of  2026  year  2  month's  24  articles extracted in both batches 。 The number of distinct articles is  2,244+286−24=2,506； For these  24  articles ， the inputs use the  news_extraction  historical batch's  v4  extractions （2026-09-29 UTC）， with the  2026  extension extractions retained as provenance （2026-09-30 UTC）。**\n\n|  manifest ／ Definition  |  Articles  |  Successful extractions  |  Failed extractions  |\n|---|---:|---:|---:|\n|  Historical  news_extraction  batch （2021-09  to  2026-02） | 2,244 | 2,043 | 201 |\n| 2026  extension batch （2026-02  to  09） | 286 | 260 | 26 |\n|  Shared across both batches  2026-02  saved text  | 24 | 24 | 0 |\n|  Distinct articles ／ selected extractions  | 2,506 | 2,279 | 227 |\n\n** Manifest checks 。**  Both  `article_manifest.csv`  contain no repeated  ID；ID  set intersection has exactly  24  entries ， the intersecting records'  `publication_local_date`  all belong to  2026-02。 these  24  entries  ID  of  `article_text_sha256`、`publication_utc`、`modified_utc`、`saved_version_available_utc`  agree exactly in both manifests ， and therefore identify the same saved text ， they cannot count as another  24  articles 。 They are absent from both receipts'  `failed_article_ids`  lists ， both extractions succeeded ； The remaining extension batch contains  262  articles from  2026  year  3–9  month 。 Each manifest matches its receipt's  `/manifest_sha256`  identity ， The two saved  `labels.parquet`  also agree with their respective  `/labels_sha256`  identity 。\n\n** Extraction selection 。** {link(adapter_path, 66)}  of  `load_news_articles`  first reads  `(bank, posts)`（ source  news_extraction）， then reads  `(extension, extra_posts)`（ extension ）。 For repeated  ID  the saved text is checked for equality ， then retains  `prior`  labels and failure flags ， adding only  `redundant_extension_source_versions`  provenance fields ； Only previously absent  ID  entries use  `result[aid]=article`。{link(adapter_path, ownership_line)}  documents that  news_extraction  owns duplicate saved texts 、 its labels are retained ， extension labels provide provenance ， selection uses neither labels nor success flags 。 This defines extraction ownership independently of numerical results 。\n\n The implementation's  SHA-256  is  `d5af3bd6bc106f5f3d26c516ebc4f6f3e9b447466ef3a21581c747979dbea478`， and  {link(freeze_path)}  of  `/files/features_adapter.py/sha256`  match （`/bytes=60032`）。{link(feature_spec, 11)}  also requires exact duplicates to be collapsed ， conflicting texts stop integration ； number  26  requires training labels to remain fixed 。 This check reads the saved implementation ／ specification ， without running the loader or feature builder 。\n\n** Batch receipt sources 。**\n\n- {link(old['root'] / 'EXTRACTION_RECEIPT.json')}：`/expected_unique_articles=2244`、`/successful=2043`、`/failures=201`、`/contract_version=4`，`/first_call_utc={old['receipt']['first_call_utc']}`、`/last_call_utc={old['receipt']['last_call_utc']}`。\n- {link(new['root'] / 'EXTRACTION_RECEIPT.json')}：`/expected_unique_articles=286`、`/successful=260`、`/failures=26`、`/contract_version=4`，`/first_call_utc={new['receipt']['first_call_utc']}`、`/last_call_utc={new['receipt']['last_call_utc']}`。\n\n Both  CSV  line numbers include the  1  header row ； The full overlap is listed below ， with source locations ：\n\n|  Article  ID |  First local publication date  |  Historical manifest row  |  Extension manifest row  |\n|---|---|---:|---:|\n{manifest_lines}\n\n Historical manifest ：{link(old['root'] / 'article_manifest.csv')}； Extension manifest ：{link(new['root'] / 'article_manifest.csv')}。\n\n** Table  2  note （ paper text ／ tables ）。** The two extraction batches overlap on 24 articles published in February 2026 (the same saved versions), giving 2,244 + 286 − 24 = 2,506 distinct articles. For these duplicates, the original historical news_extraction extraction is retained; the later extension extraction is kept only as provenance.\n\n## 3.  Figure  1–4  and reproduction \n\n-  Figure  1： shows notice archive gaps  2024-08  to  2025-10、2026-05-19  to  07-26（ inclusive ）。\n-  Figure  2： shows （a）LLM、（b） non  LLM  branches ， and  N、M、L、a(D_t)、φ_L(D_t)； Both representations add to the activity reference  M  inputs 。\n-  Figure  3： uses  O  of  `/rows/11/value/native/effect_percent_reference_mae`  and  `/rows/50/value/native/effect_percent_reference_mae`， news  M−N=−3.58%、 Notices  M_notice−N=+0.55%。\n-  Figure  4： shows  Fields（L_count） largest daily change  2026-07-20； News  Embeddings（L_chen） uses an independent vertical scale in the  inset；（b） has a vertical-axis label ； cumulative endpoint ÷ number of days = mean daily difference 。\n-  Short arm labels 、 representation definitions 、 captions and daily sources are in  [FIGURE_NOTES.md](FIGURE_NOTES.md)。 Checks of the five cumulative curves against their official means are in  [DAILY_VALIDATION.json](DAILY_VALIDATION.json)。\n\n Reproduction command （ run from the paper directory ）：\n\n```sh\nPYTHONDONTWRITEBYTECODE=1 python3 figures/make_figures.py\nPYTHONDONTWRITEBYTECODE=1 python3 figures/check_frozen_data.py\n```\n\n The plotting script reads the official export and saved daily  MAE， and computes differences ／ cumulative sums ； The data checker reads saved records and manifests, counts entries 、 and verifies hashes and ownership 。 Machine-readable checks are in  [DATA_CHECKS.json](DATA_CHECKS.json)。\n\n## 4.  Input identities \n\n|  File  |  bytes  | SHA-256 |\n|---|---:|---|\n{source_table}\n"
    (HERE / 'DATA_CHECKS_window_specification.md').write_text(text, encoding='utf-8')
    print('Notice coverage:', ', '.join((f'+{c['delay_minutes']} min {c['n']}/712={c['percent']:.1f}%' for c in coverage)))
    print(f'News overlap: {len(overlap)} February articles; distinct={distinct}; original news_extraction retained.')
if __name__ == '__main__':
    main()
