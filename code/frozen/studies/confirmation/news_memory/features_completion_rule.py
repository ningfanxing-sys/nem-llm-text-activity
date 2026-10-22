"""CONFX8 completion acceptance: current freeze, or proven unchanged CONFX7/CONFX6 feature path.
Coordinator use only: python features_completion_rule.py /path/to/COMPLETE_features.json.
Preparation tests pass synthetic dictionaries; no host_state is opened here during preparation.
"""
import json, sys
from pathlib import Path
HERE = Path(__file__).resolve().parent
CONFX6_FREEZE = '51c4f1b8278be8a1fcb152f632ccab5f4c6e0722ee24ba4130822c040498c77c'
CONFX7_FREEZE = '38c3894c4135014e9d3f5a7f296d8e588f50d0290277798bccd9accf6b9627fc'

def feature_path_proven(unchanged):
    u = unchanged or {}
    if u.get('state') != 'PASS' or u.get('feature_path_identical_to_confx7') is not True:
        return False, 'CONFX8 feature path not proven identical to CONFX7'
    prior = u.get('confx7_feature_path_proof') or {}
    if prior.get('state') != 'PASS': return False, 'CONFX7 feature-path proof did not pass'
    if prior.get('feature_path_identical_to_confx6') is True:
        return True, 'feature path identical to CONFX6 through CONFX7'
    change = prior.get('feature_path_change') or {}
    if (prior.get('feature_path_identical_to_confx6_except_resume_comparison') is True and
            change.get('scope') == 'RESUME_PANEL_COMPARISON_ONLY' and change.get('file') == 'features_adapter.py' and
            change.get('reconstruction_equals_confx6') is True):
        return True, 'feature path identical to CONFX6 except the inherited resume comparison'
    return False, 'CONFX7 has unsupported feature-path changes'

def verdict(complete, chain, unchanged):
    got = (complete or {}).get('adapter_freeze_sha256')
    current = ((chain or {}).get('amended_adapter_freeze') or {}).get('sha256')
    if not got or not current: return False, 'completion or chain freeze missing'
    steps = (chain or {}).get('steps') or []
    if [s.get('task') for s in steps] != ['CONFX3', 'CONFX4', 'CONFX5', 'CONFX6', 'CONFX7', 'CONFX8']:
        return False, 'chain is not exactly CONFX3 through CONFX8'
    s7, s8 = steps[-2:]
    if (s7.get('parent_adapter_freeze') or {}).get('sha256') != CONFX6_FREEZE:
        return False, 'CONFX7 parent is not the registered CONFX6 freeze'
    if ((s7.get('adapter_freeze') or {}).get('sha256') != CONFX7_FREEZE or
            (s8.get('parent_adapter_freeze') or {}).get('sha256') != CONFX7_FREEZE or
            (s8.get('adapter_freeze') or {}).get('sha256') != current):
        return False, 'CONFX7 to CONFX8 parent linkage mismatch'
    if got == current: return True, 'bound to the CONFX8 adapter freeze'
    if got in (CONFX6_FREEZE, CONFX7_FREEZE):
        ok, why = feature_path_proven(unchanged)
        return ok, ('bound to registered ancestor; ' + why) if ok else why
    return False, 'completion bound to an unsupported adapter freeze'

def main(argv=None):
    argv = sys.argv if argv is None else argv
    chain = json.loads((HERE / 'AMENDED_ADAPTER_CHAIN.json').read_text())
    unchanged = json.loads((HERE / 'UNCHANGED_CODE.json').read_text())
    complete = json.loads(Path(argv[1]).read_text())
    accepted, reason = verdict(complete, chain, unchanged)
    print(json.dumps({'accepted': accepted, 'reason': reason, 'completion_adapter_freeze': complete.get('adapter_freeze_sha256'),
                      'confx8_adapter_freeze': (chain.get('amended_adapter_freeze') or {}).get('sha256')}))
    return 0 if accepted else 3

if __name__ == '__main__':
    raise SystemExit(main())
