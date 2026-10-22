'Write synthetic exports after checking their input records.'
import importlib.util
import os
from pathlib import Path


def ap6_joint(*,association,request,argv,scientific_scope):
    if os.environ.get('SCORING_PHASE','prepare')!='accept':
        raise ValueError('Prepare/real AP6 publication unavailable before separate owner release')
    path=Path(__file__).resolve().parent.parent/'dispatcher_entry.py'
    association._ap_runtime.member(path)
    spec=importlib.util.spec_from_file_location('_ap_scoring_entry_bridge',path)
    module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module)
    name=module.package(association)
    publish=__import__(name+'.exporter.publish',fromlist=['run'])
    return publish.run(association=association,request=request,argv=argv,scientific_scope=scientific_scope)
