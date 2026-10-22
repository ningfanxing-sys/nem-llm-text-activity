"""CONFX7 addendum 4 proof on the real notices (scratch only; run at background priority).

    python a4_prove.py tokens  --code-root R --out OUT.json
    python a4_prove.py encode  --code-root R --mode ref|a4 --plan PLAN.json --cache DIR [--prepopulate SRC] --out OUT.json
    python a4_prove.py loop    --code-root R --mode confx6|a4 --origins ORIGINS.json --out DIR
    python a4_prove.py bench   --code-root R --origins ORIGINS.json --cache DIR --out OUT.json
    python a4_prove.py compare-encode A.json B.json
    python a4_prove.py compare-dirs DIR_A DIR_B

`--code-root` is a scratch copy of CONF (`R/CONFX2`, `R/code`, `R/ENCODER_LOCK.json`). The notices are rebuilt as the
features step does: `load_host_notices` on NRX/results_1_3 with the canonical prefix clocks of the source catalog.
No host_state file is read; no D-window outcome is read.
"""
from __future__ import annotations
import argparse, hashlib, json, shutil, sys, time
from pathlib import Path

CONF = Path(__file__).resolve().parents[1]
PROJ = CONF.parents[2]


def setup(code_root):
    sys.path.insert(0, str(Path(code_root) / 'CONFX2'))
    import runtime
    runtime.PROJ = PROJ                                   # frozen resources resolve in the real project
    import pandas as pd
    import nrx_adapter as nrx
    f = runtime.conf_module('features'); guard = runtime.conf_module('guard')
    permit = guard.ExecutionPermit('SYNTHETIC_ONLY', 'a' * 64, 'b' * 64, True)
    catalog = json.loads((CONF / 'CONFX2/prepared_sources/source_catalog.json').read_text())
    prefix_rows = pd.read_parquet(catalog['notice_prefix']['path'], columns=['notice_id', 'available_utc']).to_dict('records')
    notices = nrx.load_host_notices(PROJ / 'autopilot/q1_audits/NRX/results_1_3', permit=permit, prefix_clock_rows=prefix_rows)
    return runtime, f, permit, notices


def digest_files(root):
    root = Path(root)
    return {str(p.relative_to(root)): hashlib.sha256(p.read_bytes()).hexdigest() for p in sorted(root.rglob('*')) if p.is_file()}


def cmd_tokens(a):
    runtime, f, permit, notices = setup(a.code_root)
    import embedding_adapter as ea
    from transformers import AutoTokenizer
    lock = json.loads((Path(a.code_root) / 'ENCODER_LOCK.json').read_text())
    directory = Path('/Users/stacchining/.cache/huggingface/hub/models--sentence-transformers--all-MiniLM-L6-v2/snapshots') / lock['revision']
    tok = AutoTokenizer.from_pretrained(directory, local_files_only=True, use_fast=True)
    texts = [f.chen_notice_text([n], permit=permit) for n in notices]
    full = f.chen_notice_text(notices, permit=permit)
    per = [tok.encode(t, add_special_tokens=False, truncation=False) for t in texts]
    concat = [i for ids in per for i in ids]
    enc = tok(full, add_special_tokens=False, truncation=False, return_offsets_mapping=True)
    # every token lies inside one notice text: no token spans a "\n\n" boundary, so every prefix tokenizes to a prefix
    starts, pos = [], 0
    for i, t in enumerate(texts):
        starts.append(pos); pos += len(t) + (2 if i < len(texts) - 1 else 0)
    import bisect
    spans_ok = all(bisect.bisect_right(starts, s) == bisect.bisect_right(starts, max(s, e - 1)) for s, e in enc['offset_mapping'])
    out = {'notices': len(notices), 'empty_notice_texts': sum(1 for t in texts if not t), 'tokens': len(enc['input_ids']),
           'complete_chunks': len(enc['input_ids']) // 254, 'chars': len(full),
           'text_identity': full == '\n\n'.join(texts), 'full_ids_equal_concatenated_ids': enc['input_ids'] == concat,
           'tokenizer_encode_equal': tok.encode(full, add_special_tokens=False, truncation=False) == concat,
           'no_token_spans_a_notice_boundary': spans_ok}
    Path(a.out).write_text(json.dumps(out, indent=2) + '\n'); print(json.dumps(out))


def cmd_encode(a):
    runtime, f, permit, notices = setup(a.code_root)
    import numpy as np
    import embedding_adapter as ea
    cache = Path(a.cache)
    if a.prepopulate:
        shutil.copytree(a.prepopulate, cache)
    cache.mkdir(parents=True, exist_ok=True)
    encoder = ea.build_encoder(permit=permit, cache_directory=cache)
    plan = json.loads(Path(a.plan).read_text())
    calls = []
    def record(step, kind, end, vector, report, hit):
        v = np.asarray(vector)
        calls.append({'step': step, 'kind': kind, 'end': end, 'hit': hit, 'dtype': str(v.dtype), 'shape': list(v.shape),
                      'vector_sha256': hashlib.sha256(v.tobytes()).hexdigest(), 'report': json.dumps(report)})
    def corpus_exists(text_sha, first):
        signature = {'revision': ea.original.REVISION, 'content_budget': 254, 'text_sha256': text_sha,
                     'first_chunk_only': bool(first), 'dimension': 384, 'dtype': 'float32'}
        key = hashlib.sha256(json.dumps(signature, sort_keys=True, separators=(',', ':')).encode()).hexdigest()
        return (cache / 'corpora' / (key + '.npy')).exists()
    started = time.monotonic()
    if a.mode == 'ref':
        for i, step in enumerate(plan):
            for kind, end in (('main', step.get('main')), ('shift', step.get('shift'))):
                if end is None: continue
                text = f.chen_notice_text(notices[:end], permit=permit)
                sha = hashlib.sha256(text.encode()).hexdigest()
                firsts = (False, True) if kind == 'main' else (False,)
                for first in firsts:
                    hit = corpus_exists(sha, first)
                    v, r = ea.encode_cached(encoder, text, cache, permit=permit, first_chunk_only=first)
                    record(i, kind + ('_first' if first else ''), end, v, r, hit)
    else:
        import notice_prefix_encoding as npe
        store = npe.NoticePrefixStore(notices, encoder, permit=permit)
        states = {'main': npe.PrefixState(store, cache, 'main'), 'shift': npe.PrefixState(store, cache, 'shift')}
        for i, step in enumerate(plan):
            for kind, end in (('main', step.get('main')), ('shift', step.get('shift'))):
                if end is None: continue
                state = states[kind]; state.advance(end)
                firsts = (False, True) if kind == 'main' else (False,)
                for first in firsts:
                    hit = corpus_exists(state.hasher.copy().hexdigest(), first)
                    v, r = state.encode_cached(permit=permit, first_chunk_only=first)
                    record(i, kind + ('_first' if first else ''), end, v, r, hit)
        states['main'].check(); states['shift'].check()
    out = {'mode': a.mode, 'seconds': time.monotonic() - started, 'calls': calls,
           'corpus_files': digest_files(cache / 'corpora'), 'chunk_files': digest_files(cache / 'chunks')}
    Path(a.out).write_text(json.dumps(out) + '\n')
    print(json.dumps({'mode': a.mode, 'calls': len(calls), 'hits': sum(c['hit'] for c in calls), 'seconds': round(out['seconds'], 1),
                      'corpus_files': len(out['corpus_files']), 'chunk_files': len(out['chunk_files'])}))


def synthetic_panel(origins):
    import numpy as np, pandas as pd
    rows = []
    for origin in origins:
        o = pd.Timestamp(origin)
        for region in ('NSW1', 'QLD1', 'SA1', 'TAS1', 'VIC1'):
            for h in (5, 10, 15, 20, 25, 30):
                t = o + pd.Timedelta(minutes=h)
                rows.append({'origin': o, 'target_time': t, 'region': region, 'horizon': h,
                             'target_day': t.tz_convert('Australia/Brisbane').strftime('%Y-%m-%d')})
    panel = pd.DataFrame(rows)
    rng = np.random.default_rng(5)
    panel['num_a'] = rng.normal(size=len(panel)).astype('float32'); panel['num_b'] = rng.normal(size=len(panel)).astype('float32')
    return panel


def cmd_loop(a):
    runtime, f, permit, notices = setup(a.code_root)
    import numpy as np
    from unittest.mock import patch
    import features_adapter as fa
    import nrx_adapter as nrx
    out = Path(a.out); out.mkdir(parents=True, exist_ok=False)
    origins = json.loads(Path(a.origins).read_text())
    panel = synthetic_panel(origins)
    encoder = fa.build_encoder(permit=permit, cache_directory=out / 'embedding_cache')
    final3 = nrx.load_final3(permit=permit); corrected = nrx.load_corrected_rule(permit=permit)
    vocabulary = fa.load_notice_vocabulary(permit=permit)
    stops = frozenset((PROJ / 'autopilot/q1_audits/TFN2/corrected/english_stopwords.txt').read_text().splitlines())
    started = time.monotonic()
    rows = fa.notice_feature_rows(panel, notices, permit=permit, encoder=encoder, cache_directory=out / 'embedding_cache',
                                  final3=final3, corrected_rule=corrected, vocabulary=vocabulary, stopwords=stops, p5min_columns=())
    with patch.object(fa, 'require_disk_space', return_value={}):
        bundles = fa._write_bundles(panel, ['num_a', 'num_b'], rows, out, 'notice', np.ones(len(panel), bool), permit=permit)
    seconds = time.monotonic() - started
    (out / 'RUN.json').write_text(json.dumps({'mode': a.mode, 'origins': len(origins), 'rows': len(panel), 'seconds': seconds,
                                              'bundles': len(bundles)}) + '\n')
    print(json.dumps({'mode': a.mode, 'origins': len(origins), 'seconds': round(seconds, 1)}))


def cmd_bench(a):
    runtime, f, permit, notices = setup(a.code_root)
    import bisect
    import pandas as pd
    import embedding_adapter as ea
    import notice_prefix_encoding as npe
    from datetime import timedelta
    origins = json.loads(Path(a.origins).read_text())
    cache = Path(a.cache); cache.mkdir(parents=True, exist_ok=False)
    encoder = ea.build_encoder(permit=permit, cache_directory=cache)
    clocks = [f.utc(n['available_utc']) for n in notices]
    store = npe.NoticePrefixStore(notices, encoder, permit=permit)
    main, shift = npe.PrefixState(store, cache, 'main'), npe.PrefixState(store, cache, 'shift')
    last_end = last_shift = -1; calls = 0; started = time.monotonic(); marks = []
    for i, origin in enumerate(origins):
        now = f.utc(pd.Timestamp(origin).to_pydatetime()); end = bisect.bisect_right(clocks, now)
        shift_end = bisect.bisect_right(clocks, now - timedelta(days=28))
        if end != last_end:
            main.advance(end); main.encode_cached(permit=permit); main.encode_cached(permit=permit, first_chunk_only=True)
            last_end = end; calls += 2
        if shift_end != last_shift:
            shift.advance(shift_end); shift.encode_cached(permit=permit); last_shift = shift_end; calls += 1
        if i % 2000 == 0:
            marks.append({'origin_index': i, 'seconds': time.monotonic() - started, 'calls': calls})
    main.check(); shift.check()
    out = {'origins': len(origins), 'encode_calls': calls, 'seconds': time.monotonic() - started, 'marks': marks,
           'complete_chunks_computed': len(store.chunks), 'notices_serialized': len(store.texts)}
    Path(a.out).write_text(json.dumps(out, indent=2) + '\n'); print(json.dumps({k: out[k] for k in ('origins', 'encode_calls', 'seconds')}))


def compare_encode(left_path, right_path):
    left, right = json.loads(Path(left_path).read_text()), json.loads(Path(right_path).read_text())
    keys = ('step', 'kind', 'end', 'hit', 'dtype', 'shape', 'vector_sha256', 'report')
    mismatches = [i for i, (x, y) in enumerate(zip(left['calls'], right['calls'])) if any(x[k] != y[k] for k in keys)]
    out = {'calls': [len(left['calls']), len(right['calls'])], 'call_mismatches': mismatches[:20], 'n_call_mismatches': len(mismatches),
           'corpus_files_equal': left['corpus_files'] == right['corpus_files'], 'chunk_files_equal': left['chunk_files'] == right['chunk_files'],
           'hits': sum(c['hit'] for c in left['calls']), 'seconds': [left['seconds'], right['seconds']]}
    out['identical'] = (out['calls'][0] == out['calls'][1] and not mismatches and out['corpus_files_equal'] and out['chunk_files_equal'])
    return out


def cmd_bench_slice(a):
    """The addendum-4 encoder over production origin slices, with the complete chunks read from a warm chunk cache
    (so only the per-call work is timed: tails, pooling, corpus-cache writes). Calls are timed per slice."""
    runtime, f, permit, notices = setup(a.code_root)
    import bisect
    import pandas as pd
    import embedding_adapter as ea
    import notice_prefix_encoding as npe
    from datetime import timedelta
    origins = json.loads(Path(a.origins).read_text())
    cache = Path(a.cache); cache.mkdir(parents=True, exist_ok=False)
    shutil.copytree(Path(a.chunks_from) / 'chunks', cache / 'chunks')
    encoder = ea.build_encoder(permit=permit, cache_directory=cache)
    clocks = [f.utc(n['available_utc']) for n in notices]
    results = []
    for spec in a.slice:
        i0, i1 = map(int, spec.split(':'))
        store = npe.NoticePrefixStore(notices, encoder, permit=permit)
        main, shift = npe.PrefixState(store, cache, 'main'), npe.PrefixState(store, cache, 'shift')
        first = f.utc(pd.Timestamp(origins[i0]).to_pydatetime())
        warm = time.monotonic()
        main.advance(bisect.bisect_right(clocks, first)); shift.advance(bisect.bisect_right(clocks, first - timedelta(days=28)))
        for k in range(main.store.offsets[main.end] // 254):
            store.complete_chunk(k)                                  # warm chunks from the copied cache (disk hits)
        warm = time.monotonic() - warm
        last_end, last_shift, calls, started = main.end, shift.end, 0, time.monotonic()
        for origin in origins[i0:i1]:
            now = f.utc(pd.Timestamp(origin).to_pydatetime()); end = bisect.bisect_right(clocks, now)
            shift_end = bisect.bisect_right(clocks, now - timedelta(days=28))
            if end != last_end:
                main.advance(end); main.encode_cached(permit=permit); main.encode_cached(permit=permit, first_chunk_only=True)
                last_end = end; calls += 2
            if shift_end != last_shift:
                shift.advance(shift_end); shift.encode_cached(permit=permit); last_shift = shift_end; calls += 1
        seconds = time.monotonic() - started
        results.append({'slice': spec, 'calls': calls, 'seconds': seconds, 'seconds_per_call': seconds / max(calls, 1),
                        'warm_seconds': warm, 'main_end_range': [main.end], 'complete_chunks': len(store.chunks)})
        print(json.dumps(results[-1]), flush=True)
    Path(a.out).write_text(json.dumps({'slices': results}, indent=2) + '\n')


def cmd_compare_encode(a):
    print(json.dumps(compare_encode(a.left, a.right)))


def compare_dirs(left_path, right_path):
    left, right = digest_files(left_path), digest_files(right_path)
    skip = lambda k: k.startswith('embedding_cache/') or k == 'RUN.json'
    l = {k: v for k, v in left.items() if not skip(k)}; r = {k: v for k, v in right.items() if not skip(k)}
    differ = sorted(k for k in set(l) | set(r) if l.get(k) != r.get(k))
    cache_l = {k: v for k, v in left.items() if k.startswith('embedding_cache/')}
    cache_r = {k: v for k, v in right.items() if k.startswith('embedding_cache/')}
    return {'files_compared': len(l), 'differing': differ, 'identical': not differ and set(l) == set(r),
            'embedding_cache_identical': cache_l == cache_r, 'cache_files': [len(cache_l), len(cache_r)]}


def cmd_compare_dirs(a):
    print(json.dumps(compare_dirs(a.left, a.right)))


def cmd_summarize(a):
    w = Path(a.work)
    tokens = json.loads((w / 'tokens.json').read_text())
    encode = {name: compare_encode(w / (name + '_ref.json'), w / (name + '_a4.json')) for name in a.encode}
    loop = compare_dirs(w / 'loop_confx6', w / 'loop_a4')
    loop_runs = {m: json.loads((w / ('loop_' + m) / 'RUN.json').read_text()) for m in ('confx6', 'a4')}
    bench = json.loads((w / 'bench_slice.json').read_text())
    calls = json.loads((w / 'production_calls.json').read_text())
    spc = max(s['seconds_per_call'] for s in bench['slices'])
    stride_checks = calls['main_changes'] // 500 + calls['shift_changes'] // 500 + 2
    bench.update(production_calls=calls, max_seconds_per_call=spc,
                 projected_encoding_seconds=spc * calls['encode_calls'] + 5522 * 0.25 + stride_checks * 15.,
                 projection_rule='max seconds per call over the dense slices (background priority, efficiency core) x all '
                                 'production encode calls + 5,522 complete chunks x 0.25 s + one 15 s full-prefix check per '
                                 '500 new prefixes of each state')
    out = {'task': 'CONFX7', 'addendum': 4, 'synthetic_panel_real_notices': True, 'host_state_contents_read': False,
           'window_outcomes_read': False, 'script_sha256': hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
           'tokens': tokens, 'encode_comparisons': encode, 'loop': {**loop, 'runs': loop_runs}, 'bench': bench}
    out['all_identical'] = (tokens['text_identity'] and tokens['full_ids_equal_concatenated_ids'] and tokens['tokenizer_encode_equal']
                            and tokens['no_token_spans_a_notice_boundary'] and all(e['identical'] for e in encode.values())
                            and loop['identical'] and loop['embedding_cache_identical'])
    Path(a.out).write_text(json.dumps(out, indent=2) + '\n')
    print(json.dumps({'all_identical': out['all_identical'], 'encode': {k: v['identical'] for k, v in encode.items()},
                      'loop': loop['identical'], 'loop_cache': loop['embedding_cache_identical']}))


def main():
    p = argparse.ArgumentParser(description=__doc__); sub = p.add_subparsers(dest='cmd', required=True)
    s = sub.add_parser('tokens'); s.add_argument('--code-root', required=True); s.add_argument('--out', required=True)
    s = sub.add_parser('encode'); s.add_argument('--code-root', required=True); s.add_argument('--mode', choices=['ref', 'a4'], required=True)
    s.add_argument('--plan', required=True); s.add_argument('--cache', required=True); s.add_argument('--prepopulate'); s.add_argument('--out', required=True)
    s = sub.add_parser('loop'); s.add_argument('--code-root', required=True); s.add_argument('--mode', required=True)
    s.add_argument('--origins', required=True); s.add_argument('--out', required=True)
    s = sub.add_parser('bench'); s.add_argument('--code-root', required=True); s.add_argument('--origins', required=True)
    s.add_argument('--cache', required=True); s.add_argument('--out', required=True)
    s = sub.add_parser('bench-slice'); s.add_argument('--code-root', required=True); s.add_argument('--origins', required=True)
    s.add_argument('--cache', required=True); s.add_argument('--chunks-from', required=True); s.add_argument('--slice', action='append', required=True)
    s.add_argument('--out', required=True)
    s = sub.add_parser('compare-encode'); s.add_argument('left'); s.add_argument('right')
    s = sub.add_parser('compare-dirs'); s.add_argument('left'); s.add_argument('right')
    s = sub.add_parser('summarize'); s.add_argument('--work', required=True); s.add_argument('--encode', nargs='+', required=True)
    s.add_argument('--out', required=True)
    a = p.parse_args()
    {'tokens': cmd_tokens, 'encode': cmd_encode, 'loop': cmd_loop, 'bench': cmd_bench, 'bench-slice': cmd_bench_slice,
     'compare-encode': cmd_compare_encode, 'compare-dirs': cmd_compare_dirs, 'summarize': cmd_summarize}[a.cmd](a)


if __name__ == '__main__':
    main()
