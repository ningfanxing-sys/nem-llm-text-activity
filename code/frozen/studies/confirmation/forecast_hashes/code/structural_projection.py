'Compute structural notice features using the frozen record resolver.'
import bisect
from types import SimpleNamespace
import numpy as np
import pandas as pd
from common import resources

class NoEncoder:
    def encode_corpus(self, *args, **kwargs):
        raise RuntimeError('forecast_hashes cannot encode unchanged text')

def structural_adapter(A, arms, scratch, checkpoints):
    f = A.features
    def rows(panel, notices, *, permit, source_relations, **unused):
        f.require_execution(permit)
        records, sides = f.normalize_notices(notices, source_relations, permit=permit)
        checkpoints.append(resources(scratch))
        keys = panel[['origin','target_time','region']].rename(columns={'origin':'issue_time'})
        l14 = f.f.l14_projection(records,keys,source_relations.features,permit=permit) if 'L14' in arms else None
        resolved = source_relations.resolve_event_states(records) if 'L_Laz' in arms else None
        side_lookup = {(side['notice_id'],side['nrx_window_id']):side for side in sides}
        clocks = [f.f.utc(n['available_utc']) for n in notices]
        failures = np.r_[0,np.cumsum([n['extraction_status']!='SUCCESS' for n in notices])]
        for number,(origin,frame) in enumerate(panel.groupby('origin',sort=True)):
            now=f.f.utc(origin); end=bisect.bisect_right(clocks,now)
            meta={'notice_prefix_count':end,
                  'notice_arrivals_6h':end-bisect.bisect_right(clocks,now-pd.Timedelta(hours=6)),
                  'notice_failed_prefix_count':int(failures[end])}
            if resolved is not None:
                active=f._active_laz(resolved,origin,frame.target_time.min(),frame.target_time.max())
                active_keys=set(zip(active.notice_id.astype(str),active.nrx_window_id.astype(str)))
                active_sides=[side_lookup[key] for key in active_keys]
            for region,regional in frame.groupby('region',sort=True):
                indices=regional.index.to_numpy(); extras={}
                if l14 is not None:
                    extras[('L14','main')]={**meta,**{c:l14.loc[indices,c].to_numpy(dtype=np.float32) for c in l14}}
                if resolved is not None:
                    by_target={}
                    for target in regional.target_time.drop_duplicates():
                        output,_report=f.laz_asof(active,active_sides,origin,target,region,permit=permit)
                        by_target[target]=output
                    laz=pd.DataFrame([by_target[row.target_time] for row in regional.itertuples(index=False)],index=indices)
                    extras[('L_Laz','main')]={**meta,**{c:laz.loc[indices,c].to_numpy(dtype=np.float32) for c in laz}}
                yield indices,extras,{}
            if number%48==0:
                checkpoints.append(resources(scratch))
    proxy=SimpleNamespace(**vars(f))
    proxy.notice_feature_rows=rows
    proxy.build_encoder=lambda **kwargs:NoEncoder()
    return SimpleNamespace(features=proxy,storage=A.storage,execution=A.execution)
