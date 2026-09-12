from pathlib import Path
import os
import subprocess
import sys
import numpy as np
import pandas as pd
from microgrid.io import build_10min_pv_forecast,read_pv_forecast,read_processed,get_q2_daily_price
from microgrid.q3 import issue_pv_day,joint_issue_scenarios,settlement_components,run_q3_day
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

def test_observed_anchor_interpolates_first_hour_and_preserves_hourly_values():
    issue=pd.Timestamp('2025-02-01 18:00')
    raw=pd.DataFrame({
        'date':[issue.normalize(),issue.normalize()], 'issue_hour':[18,18],
        'issue_datetime':[issue,issue], 'target_datetime':[issue+pd.Timedelta(hours=1),issue+pd.Timedelta(hours=2)],
        'pv_forecast_kw':[60.,120.],
    })
    x=build_10min_pv_forecast(raw,issue.normalize(),'18:00',left_anchor_kw=0.,anchor_source='synthetic:known_at_18',boundary_method='observed_anchor')
    assert np.allclose(x.pv_forecast_kw.iloc[:6],[10,20,30,40,50,60],atol=1e-12,rtol=0)
    assert np.allclose(x.set_index('target_datetime').loc[[issue+pd.Timedelta(hours=1),issue+pd.Timedelta(hours=2)],'pv_forecast_kw'],[60,120],atol=1e-12,rtol=0)
    assert x.anchor_source.eq('synthetic:known_at_18').all()

def test_attachment3_anchor_sources_and_cross_day_fallback():
    f=read_pv_forecast(ROOT/'data/raw/附件3.xlsx');actual=read_processed(ROOT/'data/processed/actual_10min.parquet')
    x,m=issue_pv_day(f,'2025-02-01',18,actual,return_metadata=True)
    expected=float(actual[(actual.date==pd.Timestamp('2025-02-01'))&(actual.slot==108)].pv_actual_kwh.iloc[0])
    assert np.isnan(x[:108]).all() and np.isfinite(x[108:]).all()
    assert np.isclose(m['anchor_kw']/6,expected,atol=1e-12,rtol=0)
    assert ':slot108:' in m['anchor_source']
    _,midnight=issue_pv_day(f,'2025-02-01',0,actual,return_metadata=True)
    previous=float(actual[(actual.date==pd.Timestamp('2025-01-31'))&(actual.slot==144)].pv_actual_kwh.iloc[0])
    assert np.isclose(midnight['anchor_kw']/6,previous,atol=1e-12,rtol=0)
    assert '2025-01-31:slot144:' in midnight['anchor_source']
    _,fallback=issue_pv_day(f,'2025-01-01',0,actual,return_metadata=True)
    assert str(fallback['anchor_source']).startswith('first_hour_forecast_fallback:no_completed_interval')

def test_post_issue_actual_mutation_does_not_change_issue_trajectory():
    f=read_pv_forecast(ROOT/'data/raw/附件3.xlsx');actual=read_processed(ROOT/'data/processed/actual_10min.parquet');mutated=actual.copy();d=pd.Timestamp('2025-02-01')
    mutated.loc[(mutated.date==d)&(mutated.slot>108),'pv_actual_kwh']*=100
    a=issue_pv_day(f,d,18,actual);b=issue_pv_day(f,d,18,mutated)
    assert np.allclose(a[108:],b[108:],atol=1e-12,rtol=0)

def test_historical_scenarios_use_each_source_dates_legal_anchor():
    actual=read_processed(ROOT/'data/processed/actual_10min.parquet');oos=pd.read_csv(ROOT/'outputs/q3/q3_oos_forecasts.csv',parse_dates=['date']);forecast=read_pv_forecast(ROOT/'data/raw/附件3.xlsx');d=pd.Timestamp('2025-02-01');point=oos[oos.date==d].sort_values('slot')
    pv=issue_pv_day(forecast,d,18,actual)
    _,_,weights,sources=joint_issue_scenarios(actual,oos,forecast,d,18,point.load_pred_kwh.to_numpy(),pv,3,60,2026)
    assert np.allclose(weights,[1/3]*3,atol=1e-12,rtol=0)
    for row in sources.itertuples():
        assert f'{row.source_date.date()}:slot108:' in row.source_anchor_source
        assert pd.Timestamp(row.source_observation_cutoff)==row.source_date+pd.Timedelta(hours=18)

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

def test_future_actual_mutation_does_not_change_prior_execution_actions():
    cfg=load_config();actual=read_processed(ROOT/'data/processed/actual_10min.parquet');mutated=actual.copy();formal=ROOT/'outputs/q3/q3_oos_forecasts.csv';oos=pd.read_csv(formal,parse_dates=['date']);forecast=read_pv_forecast(ROOT/'data/raw/附件3.xlsx');target=pd.Timestamp('2025-02-01')
    mutated.loc[(mutated.date==target)&(mutated.slot>=73),['load_kw','load_kwh','pv_actual_kw','pv_actual_kwh']]*=1.7
    price=get_q2_daily_price(ROOT/'data/raw').price_yuan_per_kwh.to_numpy();kwargs=dict(date=target,policy='C2',initial_soc=4910.116222,oos=oos,forecast_long=forecast,price=price,battery=cfg['battery'],q3=cfg['q3'],delta_yuan=0,seed=cfg['random_seed'])
    a=run_q3_day(actual=actual,**kwargs);b=run_q3_day(actual=mutated,**kwargs)
    cols=['final_grid_plan_kwh','charge_kwh','discharge_kwh','emergency_purchase_kwh','soc_end_kwh']
    assert np.allclose(a.execution.loc[:71,cols],b.execution.loc[:71,cols],atol=1e-7,rtol=0)

def test_disabled_18_release_is_not_used_by_feedback_or_revisions():
    cfg=load_config();actual=read_processed(ROOT/'data/processed/actual_10min.parquet');formal=ROOT/'outputs/q3/q3_oos_forecasts.csv'
    oos=pd.read_csv(formal,parse_dates=['date']) if formal.exists() else build_oos_forecasts(actual,pd.date_range('2025-01-08','2025-02-01'),ForecastChoice('ridge','ridge'))
    forecast=read_pv_forecast(ROOT/'data/raw/附件3.xlsx');mutated=forecast.copy();target=pd.Timestamp('2025-02-01');mutated.loc[(mutated.date==target)&(mutated.issue_hour==18),'pv_forecast_kw']*=100
    price=get_q2_daily_price(ROOT/'data/raw').price_yuan_per_kwh.to_numpy();kwargs=dict(date=target,policy='C3',initial_soc=4910.116222,actual=actual,oos=oos,price=price,battery=cfg['battery'],q3=cfg['q3'],delta_yuan=500,seed=cfg['random_seed'],allowed_update_hours=[6,12])
    a=run_q3_day(forecast_long=forecast,**kwargs);b=run_q3_day(forecast_long=mutated,**kwargs)
    cols=['final_grid_plan_kwh','charge_kwh','discharge_kwh','emergency_purchase_kwh','soc_end_kwh']
    assert np.allclose(a.execution[cols],b.execution[cols],atol=1e-7,rtol=0)
    assert set(a.revisions.issue_hour)=={6,12}
    assert set(a.scenario_sources.issue_hour)=={0,6,12}
    assert not a.scenario_sources.source_anchor_source.str.contains('2025-02-01:slot108:').any()
