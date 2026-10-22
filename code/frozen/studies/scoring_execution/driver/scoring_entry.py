'Read the scoring entry point from a checked source snapshot.'
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys
from source_bytes import Sources, checked, identity, require


def namespace(control, sources):
    root = Path(control['original']['cli_source']).parent
    sys.path.insert(0, str(root))
    runtime = sources.module('runtime', root/'runtime.py')
    scorer = sources.module('seal_score', root/'seal_score.py')
    return runtime, scorer


def child(control):
    sources = Sources(control['sources'])
    with sources.imports():
        runtime, scorer = namespace(control, sources)
        cli = sources.module('_minrun_original_cli', control['original']['cli_source'])
        require(sys.argv[1:] == ['score'], 'K2 original CLI arguments')
        require(str(cli.STATE) == control['original']['state_root'], 'K2 original canonical state')
        receipt = control['original']['permit']
        checked(receipt)

        validator = runtime.validate_permit
        cli.validate_permit = lambda **kw: validator(receipt_path=Path(receipt['path']))
        evidence = dict(schema='MINRUN_ORIGINAL_BYTE_IMPORT_V1', argv=control['original']['argv'],
            permit=receipt, cli_source=sources.rows[str(Path(control['original']['cli_source']))],
            compiled_sources=[sources.rows[p] for p in sorted(sources.loaded)],
            fresh_interpreter=True, score_function_source=sources.rows[str(Path(scorer.__file__))])
        from adapters import exclusive_json
        exclusive_json(control['original']['byte_loader_evidence'], evidence)
        return cli.main(sys.argv[1:]) or 0


def invoke(control):
    argv = control['original']['argv']
    cli = control['original']['cli_source']
    expected = ['/usr/bin/caffeinate', '-i', control['interpreter']['path'], cli, 'score']
    require(argv == expected, 'K2 exact real original CLI argv required')
    env = dict(os.environ, PYTHONPATH=str(Path(__file__).parent), PYTHONDONTWRITEBYTECODE='1',
               MINRUN_ORIGINAL_CHILD=control['_control_path'])
    with Path(control['original']['opaque_stdout']).open('xb') as stdout, \
         Path(control['original']['opaque_stderr']).open('xb') as stderr:
        return subprocess.run(argv, env=env, stdout=stdout, stderr=stderr).returncode


def fresh_r2(control, sources):
    runtime, scorer = namespace(control, sources)
    r = control['r2']; original = Path(control['original']['state_root']); fresh = Path(r['state_root'])
    require(fresh != original and not fresh.exists(), 'K3 fresh R2 destination')
    permit = runtime.validate_permit(receipt_path=Path(r['permit']['path']))
    checked(r['permit'])
    ns = dict(vars(scorer))
    original_verify, original_sha = scorer.verify_seal, scorer.sha256
    ns['verify_seal'] = lambda p, features, state: original_verify(p, features, original)
    ns['sha256'] = lambda p: original_sha(original/'SEAL.json' if Path(p) == fresh/'SEAL.json' else p)

    require(r['seal_resolution'] == 'EXACT_IN_PROCESS_ORIGINAL_SEAL_ONLY', 'K3 R2 seal association')
    fresh.mkdir(parents=True, exist_ok=False)
    news = sources.module('_minrun_r2', r['source'])
    from reference_gate import ScoringBoundary
    successor = news.scoring_successor
    news.scoring_successor = lambda parent: ScoringBoundary(successor(parent), 'R2', fresh)
    try:
        return news.official_score(ns, permit, Path(r['feature_root']), fresh)
    finally:
        news.scoring_successor = successor
