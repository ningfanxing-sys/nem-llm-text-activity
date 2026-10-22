'Build physical system features available five minutes after dispatch.'
from __future__ import annotations
import io
from pathlib import Path
import zipfile

import numpy as np
import pandas as pd

RAW = Path('Documents/thesis/data_sources/electricity_price_prediction/raw/aemo_mmsdm_post5ms_core_2021_2023')
FIELDS = ['TOTALDEMAND', 'AVAILABLEGENERATION', 'DISPATCHABLEGENERATION', 'NETINTERCHANGE', 'DEMANDFORECAST']
COLUMNS = ['phys_totaldemand', 'phys_availablegeneration', 'phys_dispatchablegeneration', 'phys_netinterchange',
           'phys_demandforecast', 'phys_margin', 'phys_demand_change_30m', 'phys_margin_change_30m']
LAG = pd.Timedelta(minutes=5)


def read_month(path):
    with zipfile.ZipFile(path) as archive:
        text = archive.read(archive.namelist()[0]).decode()
    lines = [line for line in text.splitlines() if line.startswith(('I,DISPATCH,REGIONSUM', 'D,DISPATCH,REGIONSUM'))]
    if not lines or not lines[0].startswith('I,'):
        raise ValueError('Unexpected MMS layout: ' + str(path))
    frame = pd.read_csv(io.StringIO('\n'.join(lines)), usecols=['SETTLEMENTDATE', 'REGIONID', 'INTERVENTION'] + FIELDS)
    frame = frame.loc[frame.INTERVENTION == 0].drop(columns='INTERVENTION')
    frame['end_utc'] = (pd.to_datetime(frame.SETTLEMENTDATE, format='%Y/%m/%d %H:%M:%S') - pd.Timedelta(hours=10)).dt.tz_localize('UTC')
    return frame.drop(columns='SETTLEMENTDATE')


def build(months):
    paths = [RAW / f"MMSDM_{m.replace('-', '_')}" / f"PUBLIC_DVD_DISPATCHREGIONSUM_{m.replace('-', '')}010000.zip" for m in months]
    frame = pd.concat([read_month(p) for p in paths], ignore_index=True)
    if frame.duplicated(['REGIONID', 'end_utc']).any():
        raise ValueError('Duplicate pricing-run region interval')
    frame = frame.sort_values(['REGIONID', 'end_utc']).reset_index(drop=True)
    frame['phys_margin'] = frame.AVAILABLEGENERATION - frame.TOTALDEMAND
    out = []
    for region, part in frame.groupby('REGIONID'):
        part = part.set_index('end_utc')
        earlier = part[['TOTALDEMAND', 'phys_margin']].reindex(part.index - pd.Timedelta(minutes=30))
        part = part.assign(phys_demand_change_30m=part.TOTALDEMAND.to_numpy() - earlier.TOTALDEMAND.to_numpy(),
                           phys_margin_change_30m=part.phys_margin.to_numpy() - earlier.phys_margin.to_numpy())
        out.append(part.reset_index().assign(region=region))
    frame = pd.concat(out, ignore_index=True).rename(columns={f: 'phys_' + f.lower() for f in FIELDS})
    frame['issue_time'] = frame.end_utc + LAG
    return frame[['region', 'issue_time'] + COLUMNS], [str(p) for p in paths]
