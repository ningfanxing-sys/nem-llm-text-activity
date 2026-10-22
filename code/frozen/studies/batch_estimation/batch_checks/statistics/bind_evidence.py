'Bind synthetic test records to their source hashes.'
from pathlib import Path
import json
import shutil
import consumer_roots as C
from contract_io import _phase,ContractError
from bootstrap import _collect
Association=C.Association

def propose():
    a=Association();_phase(a.project,a.synthetic)
    if not a.synthetic or not a.project.is_relative_to(Path('/private/tmp')):raise ContractError('Artificial regression component only')
    a.sources();reference_snapshot=C.ACTIVE
    destination=a.project.parent/'component_evidence_proposal'
    shutil.rmtree(destination,ignore_errors=True);destination.mkdir()
    a._bootstrap_source_ready=True;a._bootstrap_depth=1;C.ACTIVE=a
    try:
        with a._validation():
            evidence,source=_collect(a,destination,_legacy_artificial_component=True)
            evidence['prior_metadata_component_fixture_only']=True
            C._write(a.out/'OUTPUT_EVIDENCE_BINDINGS.afterseal.template.json',evidence)
        return evidence
    finally:
        C.ACTIVE=reference_snapshot;a._bootstrap_source_ready=False;a._bootstrap_depth=0
        a._released=False;a._official_ready=None;a.revoke_ap_route();shutil.rmtree(destination)
if __name__=='__main__':raise PermissionError('No production binder or command; use separately reviewed source bootstrap')
