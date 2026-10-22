'Define the shared metadata used by synthetic tests.'
import consumer_roots as _C
from pathlib import Path
from contract_io import _phase

def __getattr__(name):
    named={'read':'_read','sha':'_sha','identity':'_identity','checked':'_checked','write':'_write','contained':'_contained','no_symlink_path':'_no_symlink_path','RoutedPath':'_RoutedPath','RepinQ':'_RepinQ','RepinQPath':'_RepinQPath'}
    return getattr(_C,named.get(name,name))

def _artificial(a):
    _phase(a.project,a.synthetic)
    if not a.synthetic or not a.project.is_relative_to(Path('/private/tmp')):raise PermissionError('Fixture helper is artificial only')

class Association(_C.Association):

    def _history_unit(self,method,rows):
        import os,json
        if os.environ.get('SCORING_PHASE')!='accept' or not self.project.is_relative_to(Path('/private/tmp')) or json.loads((self.project/'SYNTHETIC_ONLY.json').read_bytes())!={'synthetic_only':True}:
            raise PermissionError('Artificial metadata UNIT premise only')
        reference_snapshot=_C.ACTIVE;released=self._released


        _C.ACTIVE=self;self._released=True
        try:
            with self._validation():return method(self,rows)
        finally:_C.ACTIVE=reference_snapshot;self._released=released
    def operational_history(self,rows):return self._history_unit(_C.Association.operational_history,rows)
    def remedy_history(self,rows):return self._history_unit(_C.Association.remedy_history,rows)
Association.__module__='consumer_roots'

import types as _types
import sys as _sys
class _Vocabulary(_types.ModuleType):
    def __setattr__(self,name,value):
        if name=='ACTIVE':setattr(_C,name,value)
        else:super().__setattr__(name,value)
_sys.modules[__name__].__class__=_Vocabulary
