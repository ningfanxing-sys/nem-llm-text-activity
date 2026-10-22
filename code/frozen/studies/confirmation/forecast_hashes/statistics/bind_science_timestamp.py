'Bind verified timestamp tokens to numerical source hashes.'
from pathlib import Path
import sys
import types
import metadata_io as io
from science_contract import require
from runtime_bridge import frozen_modules,pinned_source,metadata_aliases


def bind(label):
    io.phase(source_flag='FORECAST_BINDING_SOURCE_TIMESTAMP_BIND')
    m=frozen_modules()
    import freeze_science
    path,pin=pinned_source('studies/confirmation/forecast_hashes/availability_delays/bind_delay_timestamp.py')
    module=io.load_source('_af_science_timestamp_binder',path,pin,register=False)
    module.HERE=io.HERE


    from runtime_bridge import delay_freezer_provider
    provider=delay_freezer_provider()
    provider.timestamp_required_identities=freeze_science.timestamp_required_identities
    old=sys.modules.get('delay_freeze');sys.modules['delay_freeze']=provider
    try:
        with metadata_aliases([provider,m['common'],m['run_bound_forecasts'],m['delay_authority']]):
            return module.bind(label)
    finally:
        if old is None:sys.modules.pop('delay_freeze',None)
        else:sys.modules['delay_freeze']=old


def main():
    io.phase(source_flag='FORECAST_BINDING_SOURCE_TIMESTAMP_BIND')
    import argparse
    parser=argparse.ArgumentParser();parser.add_argument('--source-bind',action='store_true',required=True)
    parser.add_argument('--label',required=True);args=parser.parse_args();bind(args.label)

if __name__=='__main__':main()
