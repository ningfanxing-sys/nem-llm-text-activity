'Construct the namespace of forecast computation receipts.'
import datetime as dt
from pathlib import Path
import re
from forecast_check_helpers import metadata_path, require

RUNTIME_ACTIONS = ('af-execute', 'verify-seal')


def runtime_root(project, action):
    require(action in RUNTIME_ACTIONS, 'AF runtime receipt action required')
    return Path(project)/'studies/confirmation/forecast_hashes/MINRUN_DRIVER_RECEIPTS'/action


def receipt_directory(project, action, receipt):

    path = metadata_path(receipt)
    root = runtime_root(project, action)
    require(path.is_relative_to(root), 'TIME_ALIGNMENT-A7 runtime receipt must stay inside action forecast_hashes namespace')
    relative = path.relative_to(root)
    require(len(relative.parts) == 2 and path.suffix == '.json', 'TIME_ALIGNMENT-A7 receipt requires <UTC>/<receipt>.json')
    token = relative.parts[0]
    require(re.fullmatch(r'\d{8}T\d{6}(?:\.\d{6})?Z', token), 'TIME_ALIGNMENT-A7 receipt folder requires actual UTC')
    dt.datetime.strptime(token, '%Y%m%dT%H%M%S.%fZ' if '.' in token else '%Y%m%dT%H%M%SZ')
    return path.parent


def new_activity_root(project, action):
    token = dt.datetime.now(dt.timezone.utc).strftime('%Y%m%dT%H%M%S.%fZ')
    directory = runtime_root(project, action)/token
    directory.mkdir(parents=True, exist_ok=False)
    return directory/'activity'
