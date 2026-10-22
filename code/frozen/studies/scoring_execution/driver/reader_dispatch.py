'Read evaluation inputs and optional batch comparison summaries.'
from contextlib import contextmanager
from copy import deepcopy
import importlib
from pathlib import Path
import sys
from types import SimpleNamespace
from adapters import exclusive_json
from association import register
from native_entries import reader_modules
from scoring_entry import namespace
from source_bytes import checked, document, identity, require
from batch_adapter import installed as batch_adapter, state_root as batch_state_root


@contextmanager
def r2_readers(a,sources):
    modules=reader_modules(sources,a._control['project']);primary_tests,sensitivity_tests,robustness_tests,sc,_=modules
    news=sources.module('_minrun_r2',a._control['r2']['source'])
    P=sources.module('read_comparisons',Path(a._control['project'])/'studies/inference/code/read_comparisons.py')
    L=sources.module('frozen_losses',P.HERE/'code/frozen_losses.py')
    base=news.a2_inputs(primary_tests.Inputs,L.native_functions());view=a._official_ready['view_inputs']['r2']
    class Inputs(base):
        def __init__(self,*args,**kwargs):
            super().__init__(*args,**kwargs)
            self.receipt=document(view['score_receipt']);self.score_files={Path(i['path']).name:i for i in self.receipt['files']}
    primary_tests.Inputs=Inputs;primary_tests.load_frozen_scoring=lambda *args,**kwargs:news.scoring_successor(sc)
    for key,value in news.a3_successor(sensitivity_tests,primary_tests).items():setattr(sensitivity_tests,key,value)
    yield primary_tests,sensitivity_tests,robustness_tests,news.scoring_successor(sc),None


def batch(a,sources,spec):
    with batch_adapter(a,sources) as patch:
        return _batch(a,sources,spec,patch)


def batch_view(value, original, r2, native_payload):

    require(value['identities']['source_receipt_sha256']==original['sha256'],
            'K4 native batch original parity receipt drift')
    result=deepcopy(value)
    result['identities']['source_receipt_sha256']=r2['sha256']
    result['original_parity_score_receipt']=original
    result['native_batch_payload']=native_payload
    return result


class BatchScoring(SimpleNamespace):

    def __init__(self,parent,news):
        vars(self).update(vars(news.scoring_successor(parent)))
        object.__setattr__(self,'_minrun_parent',parent)
    def __setattr__(self,name,value):
        if name in ('BOOTSTRAP_DRAWS','NEWS_FAMILY','NOTICE_FAMILY'):
            setattr(self._minrun_parent,name,value)
        super().__setattr__(name,value)


def _batch(a,sources,spec,patch):
    root=Path(a._control['project'])/'studies/batch_estimation/fitting/code'
    sys.path.insert(0,str(root))
    BS=patch(sources.module('score_batch',root/'score_batch.py'))
    runtime,native=namespace(a._control,sources)
    original=dict(vars(native));original_validator=runtime.validate_permit;original_conf=runtime.conf_module
    original_parity=BS.parity_by_task
    news=sources.module('_minrun_r2',a._control['r2']['source'])
    A=SimpleNamespace(root=Path(native.__file__).parent,runtime=runtime,
        execution=sources.module('execution_adapter',Path(native.__file__).parent/'execution_adapter.py'))
    permit_id=spec['permit'];checked(permit_id)
    inherited=news.native_namespace(original)
    state=batch_state_root(a,spec);require(not (state/'scoring').exists(),'K3 fresh batch score output')
    try:
        runtime.validate_permit=lambda *args,**kwargs:original_validator(receipt_path=Path(permit_id['path']))
        runtime.conf_module=lambda name:BatchScoring(original_conf(name),news) if name=='scoring' else original_conf(name)
        for key,value in inherited.items():
            if key in original and key not in ('__name__','__file__','__spec__'):setattr(native,key,value)


        native.score=lambda p,f,s:news.official_score(dict(original,verify_seal=native.verify_seal),p,f,s)


        BS.parity_by_task=lambda n,sc,p,main,seal,files:original_parity(
            SimpleNamespace(**original),original_conf('scoring'),p,main,seal,files)
        checked(spec['code'])
        freeze=patch(sources.module('freeze_batch_sources',root/'freeze_batch_sources.py'))
        code=freeze.verify(path=spec['code']['path'],seal_path=a._official_ready['view_inputs']['original']['seal']['path'])
        value=BS.score(state,code,A,a._official_ready['view_inputs']['original']['score_receipt'])


        register(a,value['CS8']['score_receipt'])
        payload=state/'scoring/A8BATCH_POSTSCORE_INPUTS.json'
        original_payload=register(a,identity(payload))
        original_view=a._official_ready['view_inputs']['original']['score_receipt']
        r2_view=a._official_ready['view_inputs']['r2']['score_receipt']
        bound=batch_view(value,original_view,r2_view,original_payload)
        source=register(a,exclusive_json(state/'scoring/MINRUN_R2_A8BATCH_POSTSCORE_INPUTS.json',bound))
        receipt=register(a,exclusive_json(spec['receipt_path'],dict(schema='MINRUN_BATCH_READER_RECEIPT_V1',files=[source,original_payload],
            source_receipt=r2_view,original_parity_receipt=original_view,
            scientific_views=a._official_ready['view_inputs'],scoring_parity=value['scoring_parity'])))
        require(all(v['state']=='PASS' for v in value['scoring_parity'].values()),'K4 original batch internal parity')
        return dict(source=source,receipt=receipt)
    finally:
        vars(native).clear();vars(native).update(original)
        runtime.validate_permit=original_validator;runtime.conf_module=original_conf
        BS.parity_by_task=original_parity


def optional(a,sources,spec):


    dispositions=document(spec['dispositions']);results={}
    require(dispositions['KCX']['state']=='WITHDRAWN','K4 DEC13 KCX disposition')
    with r2_readers(a,sources) as modules:
        primary_tests,sensitivity_tests,robustness_tests,sc,_=modules
        if spec['r2_batch_label']['execute']:
            news=sources.module('_minrun_r2',a._control['r2']['source'])
            runtime,_=namespace(a._control,sources)
            cfg=spec['r2_batch_label'];permit=runtime.validate_permit(receipt_path=Path(cfg['permit']['path']))
            checked(cfg['permit'])
            loader=primary_tests.Inputs(a._control['original']['state_root'])
            results.update(news.score_optional_inputs(primary_tests,sc,permit,loader,cfg['batch_seal'],cfg['replacement_seal'],cfg['output_directory']))
            for role,filename in [('a2batch','R2_BATCH.json'),('a2batch_receipt','R2_BATCH_RECEIPT.json'),
                ('label','R2_LABEL.json'),('label_receipt','R2_LABEL_RECEIPT.json')]:
                results[role]=register(a,identity(Path(cfg['output_directory'])/filename))
        for role in ('PC','matched_controls'):
            cfg=spec[role]
            if cfg['execute']:
                mod=sources.module('_minrun_optional_'+role,cfg['source'])

                mod.main(cfg['argv'])
                results[role.lower()]=register(a,identity(cfg['output_path']))
    results['dispositions']=spec['dispositions']
    receipt=register(a,exclusive_json(spec['receipt_path'],dict(schema='MINRUN_OPTIONAL_RECEIPT_V1',
        files=list(results.values()),native_dispositions=dispositions)))
    return dict(outputs=results,receipt=receipt)


def run(a,sources,order):
    cfg=a._control['readers'];out={}
    for role in order:
        if role=='batch-parity':out[role]=batch(a,sources,cfg[role]);continue
        if role=='authorized-optional':out[role]=optional(a,sources,cfg[role]);continue
        task={'primary_tests':0,'sensitivity_tests':1,'robustness_tests':2,'sensitivity_tests':1,'robustness_tests':2}[role];spec=cfg[role]
        with r2_readers(a,sources) as modules:
            native=modules[task]
            kwargs=deepcopy(spec['kwargs'])
            require(kwargs['state']==a._control['original']['state_root'],'K2 reader original sealed input root')
            require(not Path(kwargs['out']).exists(),'K3 fresh native reader destination')
            native.run(**kwargs)
        source=register(a,identity(spec['output_path']))
        receipt=register(a,identity(spec['receipt_path']))
        out[role]=dict(source=source,receipt=receipt)
    return out
