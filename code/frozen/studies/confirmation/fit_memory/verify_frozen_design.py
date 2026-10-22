"""CONFX7 frozen-design verification (template: CONFX6/FROZEN_DESIGN_VERIFICATION.json).

    python verify_frozen_design.py --out FROZEN_DESIGN_VERIFICATION.json

Checks, without opening host_state or any window outcome:
- the 88 design files of FREEZE.json (runtime.verify_design) and the named frozen documents and CONF/code files;
- the archived CONFX6 adapter freeze equals the registered CONFX6 freeze;
- the CONFX7 specification and both addenda equal their freeze records, and the freeze records are read-only;
- the scripts bound by the addendum freezes are unchanged;
- the CONF-A1 files are unchanged;
- the frozen memory constants of the execution adapter are unchanged (CONFX7 adds NOTICE_JOB_LIMIT by decision).
"""
from __future__ import annotations
import argparse, ast, datetime as dt, hashlib, json, stat, sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
CONF = HERE.parent
sys.path.insert(0, str(CONF / 'CONFX2'))
import runtime  # noqa: E402

CONFX6_FREEZE = '51c4f1b8278be8a1fcb152f632ccab5f4c6e0722ee24ba4130822c040498c77c'
NAMED = ('COMPUTE_PLAN.md', 'DESIGN_CONFIG.json', 'FEATURE_SPEC_CONF.md', 'INFERENCE_RULES.md', 'LEAR_SPEC.md', 'PROTOCOL_CONF.md')
A1 = {'A1/A1_FREEZE_CANDIDATE.json': 'fc4d529a3918b534265d6938f05ab65e55149aeb598808470d24ef04c2d52a41',
      'A1/ADDENDUM_A1_FINAL.md': 'd85131c9a12fd6847d778a4068485f661b8068af7354e835151149c8b03ace02',
      'A1/DECISIONS_A1_zh.md': 'dca801989de8834709e93bb0f57934734411506546e13082bfd8df182dddead5'}
FROZEN_CONSTANTS = {'BUDGET': '86400.0', 'JOB_LIMIT': '2 * 1024 ** 3', 'TREE_LIMIT': '6.6 * 1024 ** 3',
                    'THROTTLE': '6.0 * 1024 ** 3', 'FIT_HEADROOM_BYTES': '3 * 1024 ** 3'}


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def constants(path):
    out = {}
    for node in ast.parse(Path(path).read_text()).body:
        if isinstance(node, ast.Assign) and len(node.targets) == 1 and isinstance(node.targets[0], ast.Name):
            out[node.targets[0].id] = ast.unparse(node.value)
    return out


def main():
    parser = argparse.ArgumentParser(description=__doc__); parser.add_argument('--out', required=True)
    args = parser.parse_args()
    freeze = runtime.verify_design()                     # raises on any drift of the 88 design files
    frozen = freeze['frozen_files']
    named = {name: name in frozen and sha(CONF / name) == frozen[name]['sha256'] for name in NAMED}
    code = {rel: sha(CONF / rel) == item['sha256'] for rel, item in frozen.items() if rel.startswith('code/')}
    archived = HERE / 'archive/pre_CONFX7/CONFX2/ADAPTER_FREEZE.json'
    spec_freeze = json.loads((HERE / 'SPEC_FREEZE.json').read_text())
    add1 = json.loads((HERE / 'SPEC_ADDENDUM_1_FREEZE.json').read_text())
    add2 = json.loads((HERE / 'SPEC_ADDENDUM_2_FREEZE.json').read_text())
    add3 = json.loads((HERE / 'SPEC_ADDENDUM_3_FREEZE.json').read_text())
    add4 = json.loads((HERE / 'SPEC_ADDENDUM_4_FREEZE.json').read_text())
    records = {'SPEC.md': sha(HERE / 'SPEC.md') == spec_freeze['spec']['sha256'],
               'SPEC_ADDENDUM_1_FULL_ROWS.md': sha(HERE / 'SPEC_ADDENDUM_1_FULL_ROWS.md') == add1['addendum_spec']['sha256'],
               'SPEC_ADDENDUM_2_RESUME_IDENTITY.md': sha(HERE / 'SPEC_ADDENDUM_2_RESUME_IDENTITY.md') == add2['addendum_spec']['sha256'],
               'SPEC_FREEZE.json bound by addendum 1': sha(HERE / 'SPEC_FREEZE.json') == add1['spec_freeze']['sha256'],
               'SPEC_FREEZE.json bound by addendum 2': sha(HERE / 'SPEC_FREEZE.json') == add2['spec_freeze']['sha256'],
               'SPEC_ADDENDUM_1_FREEZE.json bound by addendum 2': sha(HERE / 'SPEC_ADDENDUM_1_FREEZE.json') == add2['addendum_1_freeze']['sha256'],
               'SPEC_ADDENDUM_3_THROUGHPUT.md': sha(HERE / 'SPEC_ADDENDUM_3_THROUGHPUT.md') == add3['addendum_spec']['sha256'],
               'SPEC_ADDENDUM_4_INCREMENTAL_NOTICE_ENCODING.md': sha(HERE / 'SPEC_ADDENDUM_4_INCREMENTAL_NOTICE_ENCODING.md') == add4['addendum_spec']['sha256'],
               'SPEC_ADDENDUM_3_FREEZE.json bound by addendum 4': sha(HERE / 'SPEC_ADDENDUM_3_FREEZE.json') == add4['previous_freezes']['SPEC_ADDENDUM_3_FREEZE.json']['sha256']}
    scripts = {'measure_fit_memory.py': sha(HERE / 'measure_fit_memory.py') == add1['measurement_script']['sha256'],
               'feasibility_24h.py': sha(HERE / 'feasibility_24h.py') == add1['feasibility_script']['sha256'],
               'diagnose_resume_drift.py': sha(HERE / 'diagnose_resume_drift.py') == add2['diagnosis_script']['sha256']}
    read_only = {name: not (HERE / name).stat().st_mode & (stat.S_IWUSR | stat.S_IWGRP | stat.S_IWOTH)
                 for name in ('SPEC_FREEZE.json', 'SPEC_ADDENDUM_1_FREEZE.json', 'SPEC_ADDENDUM_2_FREEZE.json',
                              'SPEC_ADDENDUM_3_FREEZE.json', 'SPEC_ADDENDUM_4_FREEZE.json')}
    a1 = {rel: sha(CONF / rel) == digest for rel, digest in A1.items()}
    found = constants(CONF / 'CONFX2/execution_adapter.py')
    memory = {name: found.get(name) == value for name, value in FROZEN_CONSTANTS.items()}
    ok = (all(named.values()) and all(code.values()) and sha(archived) == CONFX6_FREEZE and all(records.values())
          and all(scripts.values()) and all(read_only.values()) and all(a1.values()) and all(memory.values()))
    result = {'task': 'CONFX7', 'state': 'PASS' if ok else 'FAIL', 'time_utc': dt.datetime.now(dt.timezone.utc).isoformat(),
              'design_freeze': runtime.file_identity(CONF / 'FREEZE.json'), 'design_frozen_files_verified': len(frozen),
              'named_frozen_documents_unchanged': named, 'conf_code_files_verified': len(code),
              'conf_code_files_unchanged': all(code.values()),
              'archived_confx6_freeze': runtime.file_identity(archived),
              'archived_confx6_freeze_equals_registered': sha(archived) == CONFX6_FREEZE,
              'spec_and_addenda_equal_freeze_records': records, 'bound_scripts_unchanged': scripts,
              'spec_freezes_read_only': read_only, 'a1_files_unchanged': a1,
              'frozen_memory_constants_unchanged': memory,
              'compute_plan_memory_rules': 'COMPUTE_PLAN.md is frozen and byte-identical. JOB_LIMIT, TREE_LIMIT, THROTTLE, '
                                           'FIT_HEADROOM_BYTES and BUDGET are unchanged; CONFX7 measures them as anonymous '
                                           'memory and adds NOTICE_JOB_LIMIT = TREE_LIMIT by the coordinator decision of '
                                           '2026-10-02 (resource-only).',
              'host_state_contents_read': False, 'window_outcomes_read': False, 'production_commands_run': []}
    Path(args.out).write_text(json.dumps(result, indent=2, sort_keys=True) + '\n')
    print(json.dumps({'state': result['state'], 'design_files': len(frozen), 'code_files': len(code)}))
    raise SystemExit(0 if ok else 1)


if __name__ == '__main__':
    main()
