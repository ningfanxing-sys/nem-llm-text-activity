'Associate forecast calculations with their checked source modules.'
from contextlib import contextmanager, nullcontext
from copy import deepcopy
from datetime import datetime
from pathlib import Path
from types import MethodType
import hashlib
import os
import sys
from source_bytes import checked, document, identity, require


def identities(value):
    if isinstance(value, dict):
        if {'path','bytes','sha256'} <= set(value):
            yield {k:value[k] for k in ('path','bytes','sha256')}
        else:
            for item in value.values(): yield from identities(item)
    elif isinstance(value, list):
        for item in value: yield from identities(item)


def scorer_runtime_contract(contract,control):

    value=deepcopy(contract)
    if value.get('receipt_path_source')=='REAL_CONTROL_AT_RELEASE':
        for role in ('original','r2'):
            value[role]['receipt_path']=control[role]['receipt_path']
    return value


class Members:
    def __init__(self, sources, t5, source_commitment=None):
        self.sources, self.t5 = sources, t5
        self.source_commitment = source_commitment
    def member(self, path):
        key = str(Path(path).absolute()); self.sources.bytes(key)
        row = self.sources.rows[key]
        return dict(path=key, bytes=row['bytes'], sha256=row['sha256'])
    def family(self, path):
        return 'scoring_execution' if str(Path(path).absolute()) in self.sources.rows else None
    def _token(self, path):

        return Path(self.member(path)['path'])
    def revoke(self): self.revoked = True
    def revalidate(self):
        commitment=self.source_commitment
        if commitment is not None:
            require(commitment['state']=='T6_DUAL_OFFLINE_VERIFIED', 'A16 unverified supplementary source timestamp_checks')
        rows=commitment['files'] if commitment is not None else self.t5['source_files']
        listed = {(os.path.normpath(i['path']),i['bytes'],i['sha256']) for i in rows}
        require(all((os.path.normpath(r['path']),r['bytes'],r['sha256']) in listed for r in self.sources.rows.values()),
                'K1/K2 exact source bytes absent from T5 source inventory')


def dual_views(a, items):
    original, r2, execution = (items[k] for k in ('original','r2','execution'))
    require(original['seal'] == r2['seal'], 'K3 different sealed domains')
    require(original['score_receipt']['path'] != r2['score_receipt']['path'] and
            original['score_receipt']['sha256'] != r2['score_receipt']['sha256'], 'K3 distinct score chains')
    for role, view in (('original',original),('r2',r2)):
        receipt = document(view['score_receipt']); report = document(view['score_report'])
        require(receipt['state'] == report['state'] == 'FROZEN_SCORE_COMPLETE' and
                receipt['seal_sha256'] == report['seal_sha256'] == view['seal']['sha256'],
                'K3 score completion/seal association')
        files = receipt['files']
        require(view['score_report'] in files, 'K3 report not receipt-bound')
        contract=a._scorer_contract[role]
        if contract.get('output_census_rule') == 'NATIVE_FRESH_DIRECTORY_RECEIPT_COMPLETE_CENSUS':


            names=[Path(i['path']).name for i in files]
            require(len(names)==len(set(names)) and view['score_report'] in files and
                    'SCORE_RECEIPT.json' not in names, 'K4 complete native fresh output census')
        else:
            require(sorted(Path(i['path']).name for i in files) ==
                    sorted(contract['output_names']), 'K4 native score output census')
        for item in files:
            checked(item); a._reads[item['path']] = item
        a._reads.update({i['path']:i for i in view.values() if isinstance(i,dict) and 'path' in i})
        if role == 'original': require('evaluation_view' not in receipt, 'K5 original view substituted')
        else:
            marker = receipt['evaluation_view']
            require(marker['schema'] == 'PCPRIMARY_R2_NEWS_EVALUATION_V1' and
                marker['sealed_domain_days'] == 214 and marker['primary_days'] == 135 and
                len(marker['issue_days']) == 135 and marker['issue_days'][0] == '2026-05-19' and
                marker['issue_days'][-1] == '2026-09-30' and marker['scientific_source_sha256'] ==
                a._members.member(a._control['r2']['source'])['sha256'], 'K3 exact R2 marker')
    capture = document(execution['capture']); clock = document(execution['clock'])
    require(capture['source_values_decoded'] is False and capture['pending_is_negative'] is False
        and clock['conf_score_receipt'] == original['score_receipt'], 'K3 opaque original capture')
    time = lambda x: datetime.fromisoformat(x.replace('Z','+00:00'))
    require(time(a._t5_value['utc']) < time(execution['armed_utc']) <= time(clock['score_complete_utc'])
        <= time(capture['observed_utc']) <= time(execution['r2_started_utc']) <= time(execution['r2_completed_utc']),
        'K3 capture-before-R2 chronology')
    require(execution['release'] == a._control['release'] and
        execution['quiet_host'] == a._control['quiet_host'], 'K2/K3 released procedural input_checks')
    return dict(schema='C_SCORING_DUAL_OFFICIAL_VIEWS_V1', view_inputs=deepcopy(dict(
        original=original,r2=r2,execution=execution)), source=a._members.member(type(a).__module_file__)
        if hasattr(type(a),'__module_file__') else a._members.member(sys.modules[type(a).__module__].__file__))


@contextmanager
def installed(control, sources, *, synthetic=False, source_commitment=None):
    path = control['c']['archived_source']

    row = sources.rows[str(Path(path).absolute())]
    require(row['sha256'] == control['c']['archived_sha256'], 'K2 archived C V1 SHA')
    sys.path.insert(0,str(Path(path).parent))


    previous_hook=sys.addaudithook
    sys.addaudithook=lambda hook:None
    try:c = sources.module('consumer_roots',path)
    finally:sys.addaudithook=previous_hook
    a = c.Association(Path(control['project']),synthetic=synthetic)
    a._control = control; a._sources = sources; a._t5_value = document(control['t5'])
    a._members = Members(sources,a._t5_value,source_commitment); a._ap_runtime = a._members
    a._reads = {i['path']:i for i in identities(control) if i['path'] not in sources.rows}
    a._science_binding = document(control['c']['entry_contract'])
    a._scorer_contract = scorer_runtime_contract(document(control['c']['scorer_contract']),control)
    a._effective_sources = {str(Path(p).relative_to(c.LIVE)):dict(identity=dict(bytes=r['bytes'],sha256=r['sha256']))
                            for p,r in sources.rows.items() if Path(p).is_relative_to(c.LIVE)}
    a.verify_code = MethodType(lambda self,p:self._members.member(p),a)
    a.verify_t5_coverage = MethodType(lambda self:self._members.revalidate(),a)
    a._source_loading = MethodType(lambda self:nullcontext(),a)
    a._validation = MethodType(lambda self:nullcontext(),a)
    a._read_identity = MethodType(lambda self,p:self._reads.get(str(p)),a)
    def load(self, relative):
        relative = c.ENTRIES.get(relative,relative)
        p = Path(relative); p = p if p.is_absolute() else c.LIVE/p
        return sources.module(p.stem,p)
    a._load_verified = MethodType(load,a)
    a._official_score = MethodType(dual_views,a)
    def recheck(self, certificate):
        require(certificate == self._official_ready, 'K2 official certificate altered')
        self.verify_t5_coverage()
        for role in ('original','r2'):
            for item in certificate['view_inputs'][role].values():
                if isinstance(item,dict) and 'path' in item: checked(item)
        for role in ('capture','clock','release','quiet_host'):
            checked(certificate['view_inputs']['execution'][role])
    a._check_official_score = MethodType(recheck,a)
    previous = c.ACTIVE; c.ACTIVE = a
    try:
        a.verify_t5_coverage()
        if source_commitment is None:
            yield a
        else:
            from historical_source_hashes import installed as historical_pins
            with historical_pins(a,sources,source_commitment) as router:
                a._historical_source_pins = router
                yield a
    finally: c.ACTIVE = previous


def register(a, item):
    checked(item); a._reads[item['path']] = item
    return item
