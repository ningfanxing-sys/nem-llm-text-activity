"""R8 source metadata only. No feature/label/LLM loader is imported here.

The caller supplies checked source manifests, explicit observed coverage intervals
and an exact source-type lookup fixed before values. Existing model columns are
copied as opaque float32 blocks in build_bundles, then checked byte for byte.
"""
from pathlib import Path
import ast
import bisect
import csv
import hashlib
import json
import re
import numpy as np
import pandas as pd

NEWS_COLUMNS = ('a_d1', 'a_d2', 'a_d3', 'a_d7', 'a_recency_h', 'a_edited_72h', 'a_readmitted_72h', 'a_chars_72h')
NOTICE_COLUMNS = ('n_arr_5m', 'n_arr_10m', 'n_arr_15m', 'n_arr_30m', 'n_arr_60m', 'n_arr_24h', 'n_recency_min')
ALLOWED_IMPORTS = {'pathlib', 'ast', 'bisect', 'csv', 'hashlib', 'json', 're', 'numpy', 'pandas'}

def need(ok, message):
    if not ok:
        raise RuntimeError(message)

def ast_guard(source=None):
    """Closed import allowlist plus rejection of dynamic imports / execution."""
    tree = ast.parse(Path(__file__).read_text() if source is None else source)
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            need(all(a.name.split('.')[0] in ALLOWED_IMPORTS for a in node.names), 'R8 AST forbidden import')
        if isinstance(node, ast.ImportFrom):
            need(node.level == 0 and node.module.split('.')[0] in ALLOWED_IMPORTS, 'R8 AST forbidden import')
        if isinstance(node, ast.Call):
            name = node.func.id if isinstance(node.func, ast.Name) else node.func.attr if isinstance(node.func, ast.Attribute) else ''
            need(name not in {'__import__', 'import_module', 'exec', 'eval', 'spec_from_file_location'}, 'R8 AST dynamic import/execution')
    return True

def verify_source(item):
    p = Path(item['path'])
    need(p.name not in {'labels.parquet', 'EXTRACTION_RECEIPT.json'} and
         all(x not in p.parts for x in ('host_state', 'scored')) and '/semantic_validation/private/' not in str(p), 'R8 forbidden metadata input')
    h = hashlib.sha256()
    with p.open('rb') as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b''):
            h.update(block)
    need(h.hexdigest() == item['sha256'] and p.stat().st_size == item['bytes'], 'Metadata identity drift')
    return p

def validate_contract(contract):
    need(contract.get('news_lag_scope') in ('M_72H_IDS', 'SAME_SOURCE_CENSUS'), 'TODO: bind R8 lag scope')
    need(contract.get('notice_chars') == 'TITLE_PLUS_BODY_NO_SEPARATOR', 'TODO: bind notice character convention')
    need(isinstance(contract.get('notice_type_map'), dict), 'TODO: exact frozen source Notice Type map required')
    tokens = list(contract['notice_type_map'].values())
    need(all(isinstance(v,str) and re.fullmatch(r'[A-Za-z0-9_]+',v) and v not in ('OTHER','MISSING_TYPE') for v in tokens),
         'Frozen type column tokens must be safe and distinct from fallback columns')
    need(len(set(tokens)) == len(tokens), 'Distinct source Notice Types must have distinct frozen columns')
    need(contract.get('coverage') and all(s in contract['coverage'] for s in ('news', 'notice')), 'TODO: observed source coverage intervals required')
    for source in ('news', 'notice'):
        need(bool(contract['coverage'][source]), 'TODO: nonempty observed source coverage intervals required')
        for left, right in contract['coverage'][source]:
            need(pd.Timestamp(left).tzinfo is not None and pd.Timestamp(right).tzinfo is not None and
                 pd.Timestamp(left) < pd.Timestamp(right), 'Invalid metadata coverage interval')
    return True

def read_news(manifests):
    """Original-first ownership, with exact immutable-version conflict refusal."""
    census = {}
    fields = ('article_id', 'publication_utc', 'modified_utc', 'saved_version_available_utc', 'article_text_chars', 'article_text_sha256')
    for item in manifests:
        need(Path(item['path']).name == 'article_manifest.csv', 'R8 reads only frozen article source manifests')
        with verify_source(item).open(newline='') as stream:
            reader = csv.DictReader(stream)
            need(set(fields).issubset(reader.fieldnames), 'News manifest metadata schema drift')
            for row in reader:
                record = {k: row[k] for k in fields}
                aid = record['article_id']
                if aid in census:
                    need(census[aid] == record, 'Conflicting news saved version')
                else:
                    census[aid] = record
    return prepare_news(list(census.values()))

def prepare_news(records):
    out = []
    for row in records:
        available, published, modified = [pd.Timestamp(row[k]) for k in
                                         ('saved_version_available_utc', 'publication_utc', 'modified_utc')]
        need(all(t.tzinfo is not None for t in (available, published, modified)), 'Missing source timezone')
        need(available >= max(published, modified), 'Saved-version admission clock drift')
        chars = int(row['article_text_chars'])
        need(chars >= 0, 'Invalid source character count')
        out.append(dict(id=str(row['article_id']), available=available.tz_convert('UTC'),
                        published=published.tz_convert('UTC'), modified=modified.tz_convert('UTC'), chars=chars))
    need(len({r['id'] for r in out}) == len(out), 'Duplicate news ID')
    return sorted(out, key=lambda r: (r['available'], r['id']))

def read_notices(scope, type_map):
    """NRX scope is an immutable source registry, not its extraction store."""
    rows = []
    need(Path(scope['path']).name == 'scope.jsonl', 'R8 reads only immutable NRX source scope')
    with verify_source(scope).open() as stream:
        for line in stream:
            source = json.loads(line)
            # Only literal source fields are selected; no label/status/pilot field is used.
            rows.append(dict(notice_id=str(source['notice_id']), available=source['clocks']['available_time_utc'],
                             day=source['source_day_aest'], source_type=source.get('source_notice_type', ''),
                             chars=len(source['title']) + len(source['body'])))
    return prepare_notices(rows, type_map)

def prepare_notices(rows, type_map):
    result = []
    for row in rows:
        stamp = pd.Timestamp(row['available'])
        need(stamp.tzinfo is not None and int(row['chars']) >= 0, 'Invalid notice source metadata')
        raw = row.get('source_type', '')
        type_id = 'MISSING_TYPE' if raw is None or str(raw) == '' else type_map.get(str(raw), 'OTHER')
        result.append(dict(id=str(row['notice_id']), available=stamp.tz_convert('UTC'), day=str(row['day'])[:10],
                           type_id=str(type_id), chars=int(row['chars']), unmapped=type_id == 'OTHER'))
    need(len({r['id'] for r in result}) == len(result), 'Duplicate notice ID')
    return sorted(result, key=lambda r: (r['available'], r['id']))

def training_types(records):
    return sorted({r['type_id'] for r in records if '2021-10-01' <= r['day'] <= '2023-12-31'} - {'OTHER', 'MISSING_TYPE'})

def covered(intervals, left, right):
    """Full coverage of (left, right]; source gaps cannot become absence counts."""
    cursor = left
    for a, b in sorted((pd.Timestamp(a), pd.Timestamp(b)) for a, b in intervals):
        if b <= cursor:
            continue
        if a > cursor:
            return False
        cursor = max(cursor, b)
        if cursor >= right:
            return True
    return False

def news_at(records, issue, intervals, lag_scope='M_72H_IDS', clocks=None, return_ids=True):
    issue = pd.Timestamp(issue)
    clocks = [r['available'] for r in records] if clocks is None else clocks
    end = bisect.bisect_right(clocks, issue)
    start = bisect.bisect_right(clocks, issue - pd.Timedelta(hours=72))
    recent = records[start:end]
    lag_records = recent if lag_scope == 'M_72H_IDS' else records[:end]
    need(lag_scope in ('M_72H_IDS', 'SAME_SOURCE_CENSUS'), 'Invalid frozen lag scope')
    values = []
    for k in (1, 2, 3, 7):
        left, right = issue - pd.Timedelta(days=k), issue - pd.Timedelta(days=k-1)
        values.append(sum(left < r['available'] <= right for r in lag_records) if covered(intervals, left, right) else np.nan)
    known = covered(intervals, issue - pd.Timedelta(hours=168), issue)
    admitted = recent if lag_scope == 'M_72H_IDS' else records[:end]
    latest = admitted[-1]['available'] if admitted else None
    recency = min(168., (issue - latest).total_seconds()/3600) if latest is not None else 168.
    window_known = covered(intervals, issue - pd.Timedelta(hours=72), issue)
    values += [recency if known else np.nan,
               sum(r['modified'] > r['published'] for r in recent) if window_known else np.nan,
               sum(r['published'] < issue - pd.Timedelta(hours=72) for r in recent) if window_known else np.nan,
               sum(r['chars'] for r in recent) if window_known else np.nan]
    return np.asarray(values, dtype='float32'), [r['id'] for r in recent] if return_ids else len(recent)

def notice_at(records, issue, intervals, types, clocks=None, return_ids=True):
    issue = pd.Timestamp(issue)
    clocks = [r['available'] for r in records] if clocks is None else clocks
    end = bisect.bisect_right(clocks, issue)
    values = []
    for minutes in (5, 10, 15, 30, 60, 1440):
        left = issue - pd.Timedelta(minutes=minutes)
        values.append(end - bisect.bisect_right(clocks, left) if covered(intervals, left, issue) else np.nan)
    known24 = covered(intervals, issue - pd.Timedelta(days=1), issue)
    latest = records[end-1]['available'] if end else None
    values.append(min(1440., (issue-latest).total_seconds()/60) if latest is not None else 1440.)
    if not known24:
        values[-1] = np.nan
    start = bisect.bisect_right(clocks, issue - pd.Timedelta(hours=6))
    recent = records[start:end]
    type_order = [*types, 'OTHER', 'MISSING_TYPE']
    counts = dict.fromkeys(type_order, 0)
    for r in recent:
        counts[r['type_id'] if r['type_id'] in counts else 'OTHER'] += 1
    known6 = covered(intervals, issue - pd.Timedelta(hours=6), issue)
    values += [counts[k] if known6 else np.nan for k in type_order]
    values += [sum(r['chars'] for r in recent) if known6 else np.nan]
    # Brackets are mathematical notation in A8.1; LightGBM forbids them in
    # feature names. The explicit ID suffix preserves the mapping exactly.
    columns = [*NOTICE_COLUMNS, *('n_type_6h_'+k for k in type_order), 'n_chars_6h']
    return np.asarray(values, dtype='float32'), columns, [r['id'] for r in records[:end]] if return_ids else end

def metadata_matrix(panel, records, source, contract, types=None, out_path=None, evict=None):
    ast_guard()
    types = training_types(records) if types is None and source == 'notice' else types
    columns = list(NEWS_COLUMNS) if source == 'news' else notice_at(records, panel.origin.iloc[0], contract['coverage'][source], types)[1]
    shape = (len(panel),len(columns))
    if out_path is None:
        values = np.empty(shape,dtype='float32')
    else:
        need(not Path(out_path).exists(), 'Preserve existing/partial R8 metadata matrix')
        values = np.lib.format.open_memmap(out_path,mode='w+',dtype='float32',shape=shape)
    clocks = [r['available'] for r in records]
    # Grouping identical clocks avoids recalculating over repeated replay rows.
    for number,(issue, ids) in enumerate(panel.groupby('origin', sort=True).indices.items()):
        row = news_at(records, issue, contract['coverage'][source], contract['news_lag_scope'],clocks,False)[0] if source == 'news' else notice_at(records, issue, contract['coverage'][source], types,clocks,False)[0]
        values[ids] = row
        if out_path is not None and number % 128 == 0:
            values.flush()
            if evict is not None:
                evict(values)
    if out_path is not None:
        values.flush()
        if evict is not None:
            evict(values)
    return values, columns

def base_gate(storage, base, new, expected_columns, chunk=2048):
    need(all(c in new['columns'] for c in expected_columns), 'R8 missing base columns')
    h = hashlib.sha256()
    for start in range(0, base['matrix']['shape'][0], chunk):
        ids = slice(start, start+chunk)
        original = storage.load_feature_rows(base, ids, columns=expected_columns)
        reproduced = storage.load_feature_rows(new, ids, columns=expected_columns)
        need(original.shape == reproduced.shape and original.dtype == reproduced.dtype and original.tobytes() == reproduced.tobytes(),
             'R8 base-column byte equality failed')
        h.update(original.tobytes())
    return dict(state='PASS', columns=expected_columns, base_sha256=h.hexdigest(), rows=base['matrix']['shape'][0])

def build_bundles(production, out, adapters, records_by_source, contract, write, ident):
    """Append only. Preserve installed train-only pruning and opaque base bytes."""
    validate_contract(contract)
    ast_guard()
    if 'notice_training_types' in contract:
        need(contract['notice_training_types'] == training_types(records_by_source['notice']), 'Frozen training-only Notice Type list drift')
    out = Path(out)
    out.mkdir(parents=True, exist_ok=True)
    mapping = {'news': [('M0','M',True,False), ('M+0','M',True,True), ('M+','M',False,True),
                        ('L_count+','L_count',False,True), ('L_chen+','L_chen',False,True)],
               'notice': [('M0_n','M_notice',True,False), ('M+0_n','M_notice',True,True), ('M+_n','M_notice',False,True),
                          ('L14+','L14',False,True), ('L_Laz+','L_Laz',False,True), ('L_chen_notice+','L_chen_notice',False,True)]}
    result = dict(production, bundles=list(production['bundles']), r8_base_gates={}, metadata_contract=contract)
    for source, definitions in mapping.items():
        bases = {b['arm']: b for b in production['bundles'] if b['source'] == source and b.get('variant','main') == 'main'}
        primary = bases['M' if source == 'news' else 'M_notice']
        panel = pd.read_parquet(primary['panel_path'], columns=['origin','target_day','label_available'])
        # Independent metadata reconstruction also certifies the admitted source
        # census of M, without any extraction status or label.
        clocks = [r['available'] for r in records_by_source[source]]
        expected_count = np.empty(len(panel),dtype='float32')
        expected_arrival = np.empty(len(panel),dtype='float32') if source == 'notice' else None
        for issue,ids in panel.groupby('origin',sort=True).indices.items():
            end = bisect.bisect_right(clocks,issue)
            left = bisect.bisect_right(clocks,issue-pd.Timedelta(hours=72 if source == 'news' else 6))
            expected_count[ids] = end-left if source == 'news' else end
            if source == 'notice':
                expected_arrival[ids] = end-left
        activity_col = 'article_count' if source == 'news' else 'notice_prefix_count'
        need(activity_col in primary['columns'], 'M activity column unavailable; source support cannot be certified')
        for start in range(0,len(panel),2048):
            stop = min(len(panel),start+2048)
            old = adapters.storage.load_feature_rows(primary,slice(start,stop),columns=[activity_col])[:,0]
            need(old.tobytes() == expected_count[start:stop].tobytes(), 'R8 metadata source census differs from M')
            if source == 'notice' and 'notice_arrivals_6h' in primary['columns']:
                old6 = adapters.storage.load_feature_rows(primary,slice(start,stop),columns=['notice_arrivals_6h'])[:,0]
                need(old6.tobytes() == expected_arrival[start:stop].tobytes(), 'R8 notice 6h source census differs from M')
        extra_path = out / (source + '__R8_unpruned.npy')
        width = len(NEWS_COLUMNS) if source == 'news' else len(NOTICE_COLUMNS)+len(training_types(records_by_source[source]))+3
        adapters.storage.require_disk_space(out,len(panel)*4*(width+sum(len(bases[base]['columns'])+width for _,base,_,_ in definitions)),
                                           adapters.storage.FEATURE_HEADROOM_BYTES,'R8 retained metadata and feature bank')
        values, names = metadata_matrix(panel, records_by_source[source], source, contract,
                                       out_path=extra_path,evict=adapters.features._evict)
        if source == 'news':
            train = panel.target_day.astype(str).between('2021-10-01','2024-12-31').to_numpy() & (pd.to_datetime(panel.label_available, utc=True) < pd.Timestamp('2024-12-31T14:00Z')).to_numpy()
        else:
            train = np.arange(len(panel)) < int(primary['train_rows'])
        keep, pruned = adapters.features.fixed_pruning(values, train, names)
        adapters.storage.require_disk_space(out, values.nbytes + sum(len(panel)*4*(len(bases[base]['columns']) + len(keep)) for _,base,_,_ in definitions),
                                           adapters.storage.FEATURE_HEADROOM_BYTES, 'R8 feature bank')
        result.setdefault('r8_unpruned', {})[source] = ident(extra_path, columns=names, keep=list(map(int,keep)), pruned=pruned)
        for arm, base_name, remove_failure, append in definitions:
            base = bases[base_name]
            adapters.storage.verify_bundle(base)
            failure = 'extraction_failed_count' if source == 'news' else 'notice_failed_prefix_count'
            old_columns = [c for c in base['columns'] if not (remove_failure and c == failure)]
            columns = old_columns + ([names[i] for i in keep] if append else [])
            path = out / (source+'__'+arm+'.npy')
            need(not path.exists(), 'Preserve partial R8 matrix')
            matrix = np.lib.format.open_memmap(path, mode='w+', dtype='float32', shape=(len(panel),len(columns)))
            for start in range(0,len(panel),2048):
                stop = min(len(panel),start+2048)
                matrix[start:stop,:len(old_columns)] = adapters.storage.load_feature_rows(base,slice(start,stop),columns=old_columns)
                if append:
                    matrix[start:stop,len(old_columns):] = values[start:stop,keep]
                adapters.features._evict(matrix)
            matrix.flush()
            matrix._mmap.close()
            # Conventional matrix layout is supported by the unchanged installed worker.
            bundle = dict(source=source,arm=arm,variant='main',state='COMPLETE',rows=len(panel),columns=columns,
                          extra_columns=[c for c in base.get('extra_columns',[]) if c in old_columns]+([names[i] for i in keep] if append else []),
                          pruned_names=base.get('pruned_names',[])+(pruned if append else []),
                          matrix=ident(path,shape=[len(panel),len(columns)],dtype='float32'),
                          panel_path=base['panel_path'],panel_sha256=base['panel_sha256'])
            if source == 'notice':
                bundle['train_rows'] = base['train_rows']
            result['r8_base_gates'][source+'/'+arm] = base_gate(adapters.storage,base,bundle,old_columns)
            result['bundles'].append(bundle)
        values._mmap.close()
    result['state'] = 'FEATURE_BANK_COMPLETE'
    result['metadata_admitted_source_census_gate'] = 'PASS'
    result['notice_type_coverage'] = dict(training_type_ids=training_types(records_by_source['notice']),
                                        total=len(records_by_source['notice']),
                                        unmapped=sum(r['unmapped'] for r in records_by_source['notice']))
    write(out/'manifest.json',result,exclusive=True)
    return result
