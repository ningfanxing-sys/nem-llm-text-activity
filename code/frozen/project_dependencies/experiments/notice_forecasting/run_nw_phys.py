'Fit notice models with the physical system features.'
from pathlib import Path
import sys

import pandas as pd

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import run_nw as rn
import nw_phys

rn.MONTHS = [str(p) for p in pd.period_range('2021-10', '2023-12', freq='M')]
rn.FOLDS = rn.FOLDS[:6]
rn.OUT = HERE / 'run_phys'
_numeric, _load = rn.numeric_columns, rn.load_bank


def numeric_columns():
    return _numeric() + nw_phys.COLUMNS


def load_bank(features):
    data, hashes = _load([f for f in features if f not in nw_phys.COLUMNS])
    phys, paths = nw_phys.build(rn.MONTHS)
    merged = data.merge(phys, on=['region', 'issue_time'], how='left', validate='many_to_one')
    if len(merged) != len(data) or not merged[['region', 'issue_time']].equals(data[['region', 'issue_time']]):
        raise ValueError('PHYS join changed row order or count')
    rn.write_json(rn.OUT / 'phys_binding.json', dict(
        specification_sha256=rn.sha(HERE / 'PROTOCOL_NW_SPECIFICATION_1.md'), phys_code_sha256=rn.sha(HERE / 'nw_phys.py'),
        runner_sha256=rn.sha(Path(__file__)), sources={p: rn.sha(p) for p in paths},
        missing_share={c: float(merged[c].isna().mean()) for c in nw_phys.COLUMNS}), immutable=True)
    return merged, hashes


rn.numeric_columns, rn.load_bank = numeric_columns, load_bank

if __name__ == '__main__':
    rn.run()
