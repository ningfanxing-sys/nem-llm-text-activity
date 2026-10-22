"""CONFX7 rule: which `COMPLETE_features.json` may start the fit steps (CONFX7/SPEC.md section 4 as superseded by
SPEC_ADDENDUM_2_RESUME_IDENTITY.md section 3).

    python features_completion_rule.py /path/to/host_state/COMPLETE_features.json   # exit 0 accepted, 3 refused

The features rerun started under the CONFX6 adapter freeze, so its completion receipt binds that freeze. A completion
is accepted for the fit steps iff its `adapter_freeze_sha256`:
- equals the CONFX7 freeze recorded in `AMENDED_ADAPTER_CHAIN.json`; or
- equals the CONFX6 freeze, the CONFX7 chain step names that freeze as its parent, `UNCHANGED_CODE.json` has
  `state == PASS`, and the feature path is proven either identical to CONFX6, or identical except the resume
  comparison: `feature_path_identical_to_confx6_except_resume_comparison is True`, `feature_path_change.scope ==
  'RESUME_PANEL_COMPARISON_ONLY'`, `feature_path_change.file == 'features_adapter.py'` and
  `feature_path_change.reconstruction_equals_confx6 is True`.

Why the exception keeps a CONFX6 run valid (addendum 2 section 3): the changed lines write nothing; they only decide
whether a stored panel copy may be reused. A COMPLETE CONFX6 run wrote each panel copy with the unchanged write call,
or reused a copy that passed `DataFrame.equals` (equal columns, dtypes and values after reading), a check that can
fail falsely but accepts no differing content. Every other feature-path line is byte-identical. So the files of a
COMPLETE CONFX6 run are the files the CONFX7 code writes for the same inputs.

Everything else is refused, with the reason. Only the completion receipt and the two CONFX7 records are read.
"""
from __future__ import annotations
import json
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
CONFX6_FREEZE = '51c4f1b8278be8a1fcb152f632ccab5f4c6e0722ee24ba4130822c040498c77c'
RESUME_SCOPE = 'RESUME_PANEL_COMPARISON_ONLY'


def feature_path_proven(unchanged):
    """(accepted, reason) for the feature-path proof in UNCHANGED_CODE.json."""
    unchanged = unchanged or {}
    if unchanged.get('state') != 'PASS':
        return False, 'UNCHANGED_CODE.json did not pass'
    if unchanged.get('feature_path_identical_to_confx6') is True:
        return True, 'feature path identical to CONFX6'
    change = unchanged.get('feature_path_change') or {}
    if (unchanged.get('feature_path_identical_to_confx6_except_resume_comparison') is True and
            change.get('scope') == RESUME_SCOPE and change.get('file') == 'features_adapter.py' and
            change.get('reconstruction_equals_confx6') is True):
        return True, 'feature path identical to CONFX6 except the resume comparison (reconstruction proven)'
    return False, 'UNCHANGED_CODE.json proves neither an identical feature path nor the resume-comparison-only change'


def verdict(complete, chain, unchanged):
    got = (complete or {}).get('adapter_freeze_sha256')
    confx7 = ((chain or {}).get('amended_adapter_freeze') or {}).get('sha256')
    if not got:
        return False, 'COMPLETE_features.json has no adapter_freeze_sha256'
    if not confx7:
        return False, 'CONFX7 chain record has no amended adapter freeze'
    if got == confx7:
        return True, 'bound to the CONFX7 adapter freeze'
    if got == CONFX6_FREEZE:
        steps = (chain or {}).get('steps') or []
        last = steps[-1] if steps else {}
        parent = (last.get('parent_adapter_freeze') or {}).get('sha256')
        if last.get('task') != 'CONFX7' or parent != CONFX6_FREEZE:
            return False, 'the CONFX7 chain step does not name the CONFX6 freeze as its parent'
        proven, why = feature_path_proven(unchanged)
        if not proven:
            return False, why
        return True, 'bound to the CONFX6 freeze; ' + why
    return False, 'bound to adapter freeze ' + str(got) + ', which is neither CONFX7 nor (with proof) CONFX6'


def main(argv=None):
    argv = sys.argv if argv is None else argv
    complete = json.loads(Path(argv[1]).read_text())
    chain = json.loads((HERE / 'AMENDED_ADAPTER_CHAIN.json').read_text())
    unchanged = json.loads((HERE / 'UNCHANGED_CODE.json').read_text())
    accepted, reason = verdict(complete, chain, unchanged)
    print(json.dumps({'accepted': accepted, 'reason': reason, 'completion_adapter_freeze': complete.get('adapter_freeze_sha256'),
                      'confx7_adapter_freeze': (chain.get('amended_adapter_freeze') or {}).get('sha256')}))
    return 0 if accepted else 3


if __name__ == '__main__':
    raise SystemExit(main())
