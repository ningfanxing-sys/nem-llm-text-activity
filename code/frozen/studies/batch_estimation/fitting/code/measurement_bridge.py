"""Reuse measured kernel evidence while separately testing orchestration repairs."""
import ast
from a8_common import *

KERNEL = ('shifted_notices','predict_notice','parity_frame','run_delays','d_panel','rebuild_features')

def kernel_hashes(path):
    tree = ast.parse(Path(path).read_text())
    found = {n.name:hashlib.sha256(ast.dump(n,include_attributes=False).encode()).hexdigest()
             for n in tree.body if isinstance(n,ast.FunctionDef) and n.name in KERNEL}
    require(set(found) == set(KERNEL),'Incomplete measured kernel inventory')
    return found

def verify_bridge(path,value):
    bridge = read_json(LEGACY_OUT/'test_logs/DLY8_MEASUREMENT_REUSE.json')
    require(bridge['measurement'] == identity(path),'Measurement reuse receipt drift')
    baseline = checked(bridge['baseline'])
    require(sha(baseline) == value['code_sha256']['code/dly8_rebuild.py'],'Measured baseline identity drift')
    require(bridge['kernel_sha256'] == kernel_hashes(baseline) == kernel_hashes(OUT/'code/dly8_rebuild.py'),
            'DLY8 projection kernel changed; old benchmark cannot be reused')
    require(bridge['limit_bytes'] == 2*1024**3 and bridge['full_panel_rerun'] is False,
            'Measurement reuse may not relax resource or full-panel gates')
    return bridge
