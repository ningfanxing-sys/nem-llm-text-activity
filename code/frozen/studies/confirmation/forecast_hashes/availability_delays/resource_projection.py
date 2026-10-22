'Measure resource use for synthetic structural feature calculations.'
from pathlib import Path
import time
import types


def measure_synthetic(root):
    import common,anchor_patch
    import numpy as np
    import pandas as pd
    root=Path(root).resolve()
    common.require(root.is_relative_to(Path('/private/tmp')),'Projection measurement needs synthetic scratch')
    dly=common.dly_module(); resources=[common.resources(root)]
    count=1024; width=16
    origins=pd.date_range('2026-08-02T00:00:00Z',periods=count//4,freq='5min').repeat(4)
    panel=dly.normalize(pd.DataFrame(dict(origin=origins,target_time=origins+pd.Timedelta(minutes=5),
        region=['NSW1','QLD1','SA1','VIC1']*(count//4),horizon=[5]*count,target_day=['2026-08-02']*count,
        anchor=np.ones(count,dtype=np.float32))))
    columns=['synthetic_'+str(i) for i in range(width)]
    bundles={a:dict(columns=columns,shared_columns=[]) for a in ('L14','L_Laz')}
    notices=[dict(notice_id='SYNTHETIC_ONLY',available_utc='2026-08-02T00:00:00Z',
                  raw_time_local='02/08/2026 00:00:00',aligned=False)]
    def rows(frame,shifted,**unused):
        note=shifted[0]
        stamp=anchor_patch.parse_anchor(note['raw_time_local']) if note['aligned'] else pd.Timestamp(note['raw_time_local'])
        admitted=(frame.origin>=pd.Timestamp(note['available_utc'])).to_numpy(dtype=np.float32)
        extras={}
        for arm in bundles:
            extras[(arm,'main')]={name:admitted*np.float32(stamp.day+i) for i,name in enumerate(columns)}
        yield np.arange(len(frame)),extras,{}
    def disk(_root,planned,_headroom,_reason):
        common.require(planned<common.SCRATCH_LIMIT,'Synthetic planned scratch exceeds cap')
    features=types.SimpleNamespace(load_final3=lambda **_:None,load_corrected_rule=lambda **_:None,
                                  notice_feature_rows=rows,_evict=lambda _:None)
    adapter=types.SimpleNamespace(features=features,storage=types.SimpleNamespace(require_disk_space=disk))
    class FixedSyntheticModel:
        def predict(self,x,*,num_threads):
            common.require(num_threads==1 and x.dtype==np.float32,'Synthetic measurement prediction drift')
            return x[:,0].astype('float64')*.1
    timings=[]
    for delta in (15,60):
        for arm in ('L14','L_Laz'):
            pair=[]
            for aligned in (False,True):
                modified=[dict(notices[0],aligned=aligned)]
                directory=root/(arm+'_'+str(delta)+'_'+str(aligned))
                start=time.perf_counter()
                matrix=dly.rebuild_features(panel,modified,delta,[arm],bundles,adapter,None,directory,{},encoder=object())[arm]
                rebuild=time.perf_counter()-start
                pair.append(matrix)
                start=time.perf_counter()
                result=dly.predict_notice(FixedSyntheticModel(),matrix,panel,{'n_jobs':1},
                                         lambda target:np.full(len(target),1000.,dtype='float64'))
                prediction=time.perf_counter()-start
                common.require(len(result)==count,'Synthetic resource prediction coverage drift')
                resources.append(common.resources(root))
                timings.append(dict(arm=arm,delta_minutes=delta,aligned=aligned,
                                    rebuild_seconds=rebuild,predict_seconds=prediction))
            for matrix in pair:
                filename=Path(matrix.filename); matrix.flush(); matrix._mmap.close(); filename.unlink()
    return dict(schema='FORECAST_BINDING8_SYNTHETIC_RESOURCE_PROJECTION_V1',synthetic_only=True,
        rows=count,columns=width,arms=['L14','L_Laz'],delta_minutes=[15,60],measurements=timings,
        numerical_processes=1,models_refitted=0,
        measured_scope='Unchanged frozen DLY8 matrix assembly/predict with synthetic projection and fixed synthetic model',
        actual_projection_or_model_measured=False,full_D_rows=61*8640,
        additional_rebuilds=8,additional_predictions=8,total_including_plus5_rebuilds=12,
        corrected_prediction_files=6,single_seal=True,
        matrix_pair_bytes_formula='2 * D_rows * retained_columns_for_arm * 4',
        scratch_plan_formula='retained_matrix_bytes + D_rows * columns_for_arm * 4 + D_rows * 80 < 1000000000',
        actual_retained_columns='U',real_notice_projection_seconds='U',real_sealed_model_prediction_seconds='U',
        real_IO_and_gate_seconds='U',real_host_wall_seconds='U',real_output_parquet_bytes='U',
        real_peak_RSS_bytes='U',synthetic_to_real_time_extrapolation=False,
        resources=resources,minimum_memory_free_percent=min(r['memory_free_percent'] for r in resources),
        maximum_synthetic_scratch_bytes=max(r['scratch_bytes'] for r in resources),
        maximum_peak_RSS_bytes=max(r['peak_rss_bytes'] for r in resources))
