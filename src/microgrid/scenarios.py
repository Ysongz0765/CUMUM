"""Causal joint residual-trajectory bootstrap scenarios."""
import numpy as np
import pandas as pd

def generate_joint_scenarios(actual: pd.DataFrame, oos_forecasts: pd.DataFrame, point: pd.DataFrame, target_date, scenario_count=20, random_seed=2026):
    target=pd.Timestamp(target_date).normalize()
    merged=oos_forecasts.merge(actual[["date","slot","load_kw","pv_actual_kw"]],on=["date","slot"],validate="one_to_one")
    merged=merged[merged.date < target].copy()
    complete=merged.groupby("date").size(); eligible=complete[complete==144].index
    same=[d for d in eligible if d.month in {target.month,max(1,target.month-1),min(12,target.month+1)} and (d.dayofweek>=5)==(target.dayofweek>=5)]
    pool=pd.DatetimeIndex(same if len(same)>=scenario_count else eligible)
    if len(pool)==0: raise ValueError(f"no out-of-sample residual day before {target.date()}")
    rng=np.random.default_rng(random_seed + int(target.strftime("%j")))
    sources=rng.choice(pool.to_numpy(),size=scenario_count,replace=len(pool)<scenario_count)
    scenarios=[]
    for sid,src in enumerate(sources):
        day=merged[merged.date==pd.Timestamp(src)].sort_values("slot")
        load=np.maximum(0,point.load_pred_kw.to_numpy()+day.load_kw.to_numpy()-day.load_pred_kw.to_numpy())/6
        pv=np.maximum(0,point.pv_pred_kw.to_numpy()+day.pv_actual_kw.to_numpy()-day.pv_pred_kw.to_numpy())/6
        scenarios.append(pd.DataFrame({"scenario":sid,"slot":np.arange(1,145),"load_kwh":load,"pv_kwh":pv,"source_date":pd.Timestamp(src),"weight":1/scenario_count,"training_cutoff":target-pd.Timedelta(days=1)}))
    return pd.concat(scenarios,ignore_index=True)
