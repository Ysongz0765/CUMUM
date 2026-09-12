from pathlib import Path
import os
import subprocess
import sys
import numpy as np
import pandas as pd
from microgrid.io import read_pv_forecast,read_processed,get_q2_daily_price
from microgrid.q3 import issue_pv_day,settlement_components,run_q3_day
from microgrid.config import load_config
from microgrid.prediction import build_oos_forecasts,ForecastChoice

ROOT=Path(__file__).parents[1]

def test_q3_validator_uses_raw_attachment2(tmp_path):
    detail=pd.read_csv(ROOT/'outputs/q3/q3_execution_detail.csv')
    detail.loc[0,'load_actual_kwh'] += 1.0
    detail.loc[0,'remaining_energy_kwh'] -= 1.0
    bad_detail=tmp_path/'tampered_q3_detail.csv';detail.to_csv(bad_detail,index=False)
    processed=pd.read_csv(ROOT/'data/processed/actual_10min.csv')
    processed.loc[processed.index[0],'load_kwh'] += 1.0
    processed.to_csv(tmp_path/'tampered_processed.csv',index=False)
    env=os.environ.copy();env['Q3_DETAIL_PATH']=str(bad_detail);env['PYTHONPATH']=str(ROOT/'src')
    result=subprocess.run([sys.executable,'scripts/10_validate_q3.py'],cwd=ROOT,env=env,capture_output=True,text=True)
    assert result.returncode != 0
    assert 'actual_matches_attachment2' in result.stderr or 'FAILED CHECKS' in result.stderr

def test_q3_final_settlement_hand_cases():
    p=np.array([1.])
    assert np.isclose(settlement_components([100],[80],p)[1].sum(),90)
    assert np.isclose(settlement_components([100],[120],p)[1].sum(),130)
    assert np.isclose(settlement_components([100],[100],p)[1].sum(),100)
    # Final-vs-original settlement: 100 -> 140 -> 100 costs 100, not the
    # 140 that would arise from charging every adjacent revision.
    assert np.isclose(settlement_components([100],[100],p)[1].sum(),100)

def test_attachment3_issue_boundary_and_first_hour_fill():
    f=read_pv_forecast(ROOT/'data/raw/附件3.xlsx');x=issue_pv_day(f,'2025-02-01',6)
    assert np.isnan(x[:36]).all() and np.isfinite(x[36:]).all()
    hourly=f[(f.date==pd.Timestamp('2025-02-01'))&(f.issue_hour==6)].sort_values('horizon_hour')
    assert np.allclose(x[36:41],hourly.pv_forecast_kw.iloc[0]/6)

def test_c2_equals_c3_when_delta_zero():
    cfg=load_config();actual=read_processed(ROOT/'data/processed/actual_10min.parquet')
    formal=ROOT/'outputs/q3/q3_oos_forecasts.csv'
    oos=pd.read_csv(formal,parse_dates=['date']) if formal.exists() else build_oos_forecasts(actual,pd.date_range('2025-01-08','2025-02-01'),ForecastChoice('ridge','ridge'))
    forecast=read_pv_forecast(ROOT/'data/raw/附件3.xlsx');price=get_q2_daily_price(ROOT/'data/raw').price_yuan_per_kwh.to_numpy()
    a=run_q3_day('2025-02-01','C2',4910.116222,actual,oos,forecast,price,cfg['battery'],cfg['q3'],0,cfg['random_seed'])
    b=run_q3_day('2025-02-01','C3',4910.116222,actual,oos,forecast,price,cfg['battery'],cfg['q3'],0,cfg['random_seed'])
    cols=['final_grid_plan_kwh','charge_kwh','discharge_kwh','emergency_purchase_kwh','soc_end_kwh']
    assert np.allclose(a.execution[cols],b.execution[cols],atol=1e-7,rtol=0)

def test_future_release_mutation_does_not_change_prior_actions():
    cfg=load_config();actual=read_processed(ROOT/'data/processed/actual_10min.parquet');formal=ROOT/'outputs/q3/q3_oos_forecasts.csv'
    oos=pd.read_csv(formal,parse_dates=['date']) if formal.exists() else build_oos_forecasts(actual,pd.date_range('2025-01-08','2025-02-01'),ForecastChoice('ridge','ridge'))
    forecast=read_pv_forecast(ROOT/'data/raw/附件3.xlsx');mutated=forecast.copy();target=pd.Timestamp('2025-02-01');mutated.loc[(mutated.date==target)&(mutated.issue_hour>=12),'pv_forecast_kw']*=20
    price=get_q2_daily_price(ROOT/'data/raw').price_yuan_per_kwh.to_numpy();a=run_q3_day(target,'C2',4910.116222,actual,oos,forecast,price,cfg['battery'],cfg['q3'],0,cfg['random_seed']);z=run_q3_day(target,'C2',4910.116222,actual,oos,mutated,price,cfg['battery'],cfg['q3'],0,cfg['random_seed'])
    cols=['final_grid_plan_kwh','charge_kwh','discharge_kwh','emergency_purchase_kwh','soc_end_kwh']
    assert np.allclose(a.execution.loc[:71,cols],z.execution.loc[:71,cols],atol=1e-7,rtol=0)
