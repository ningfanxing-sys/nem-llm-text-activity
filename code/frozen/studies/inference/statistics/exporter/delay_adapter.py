'Read notice-delay results through their checked numerical functions.'
from contextlib import contextmanager
import importlib
import json
from pathlib import Path
import sys
from ..input_checks import HERE, require


class Evaluator:
    def __init__(self,runtime):
        self.runtime=runtime
        self.final_reviewed_contract=runtime.final_reviewed_contract
        self.module_root=HERE.parents[1]/'confirmation/notice_evaluation/statistics'

    def check_sources_and_authority(self):
        self.runtime.check_sources_and_authority()
        pins=json.loads(self.runtime.checked_source(HERE/'exporter/RD_REVIEWED_SOURCE_PINS.json'))
        for pin in pins['runtime_files']+[pins['review'],pins['review_inventory'],pins['acceptance_receipt']]:
            data=self.runtime.checked_source(Path(pin['path']))
            import hashlib
            require(len(data)==pin['bytes'] and hashlib.sha256(data).hexdigest()==pin['sha256'],'Reviewed notice_delays source drift')

    @contextmanager
    def modules(self):
        self.check_sources_and_authority()
        prior_path=sys.path[:];reference_snapshot=dict(sys.modules)
        sys.path.insert(0,str(self.module_root))
        try:
            for name in ('evaluator','evaluator.validation','evaluator._predicates'):
                if name in sys.modules:
                    require(Path(sys.modules[name].__file__).resolve().is_relative_to(self.module_root),'Cached notice_delays origin drift')
            with self.runtime.association._source_loading():
                validation=importlib.import_module('evaluator.validation')
                predicates=importlib.import_module('evaluator._predicates')
            yield validation,predicates
            self.check_sources_and_authority()
        finally:
            sys.path[:]=prior_path
            for name in set(sys.modules)-set(reference_snapshot):sys.modules.pop(name,None)
            sys.modules.update(reference_snapshot)

    def validate_scalar(self,*args,**kwargs):
        with self.modules() as (v,p):return v.validate_scalar(*args,**kwargs)
    def reliable_support(self,*args,**kwargs):
        with self.modules() as (v,p):return p.reliable_support(*args,**kwargs)
    def seven_day_definedness(self,*args,**kwargs):
        with self.modules() as (v,p):return p.seven_day_definedness(*args,**kwargs)
    def specified_primary_seed(self,*args,**kwargs):
        with self.modules() as (v,p):return p.specified_primary_seed(*args,**kwargs)
