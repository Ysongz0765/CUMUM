from pathlib import Path
import sys,json,time
import numpy as np,pandas as pd
sys.path.insert(0,str(Path(__file__).parents[1]/'src'))
from microgrid.io import read_processed,get_q2_daily_price
from microgrid.config import load_config
from microgrid.scenarios import generate_joint_scenarios
from microgrid.models.stochastic_dispatch import solve_two_stage_dispatch
from microgrid.execution import execute_fixed_grid_plan
from microgrid.prediction import build_oos_forecasts,ForecastChoice
ROOT=Path(__file__).parents[1];cfg=load_config();b=cfg['battery'];price=get_q2_daily_price(ROOT/'data/raw').price_yuan_per_kwh.to_numpy();actual=read_processed(ROOT/'data/processed/actual_10min.csv');warm=pd.read_csv(ROOT/'outputs/q2/january_initialization.csv',parse_dates=['date'])
formal=ROOT/'outputs/q3/q3_oos_forecasts.csv'
if formal.exists(): oos=pd.read_csv(formal,parse_dates=['date'])
else:
    oos=build_oos_forecasts(actual,pd.date_range('2025-01-08','2025-12-31'),ForecastChoice('ridge','ridge'))
    formal.parent.mkdir(parents=True,exist_ok=True);oos.to_csv(formal,index=False)
rows=[];started=time.time()
for lam in [0,.05,.1,.2,.5]:
    soc=float(warm[warm.date==pd.Timestamp('2025-01-21')].soc_end_kwh.iloc[-1]);costs=[]
    for d in pd.date_range('2025-01-22','2025-01-31'):
        point=oos[oos.date==d].sort_values('slot');sc=generate_joint_scenarios(actual,oos,point,d,20,2026);load=sc.pivot(index='scenario',columns='slot',values='load_kwh').to_numpy();pv=sc.pivot(index='scenario',columns='slot',values='pv_kwh').to_numpy();weights=sc.groupby('scenario').weight.first().to_numpy();plan=solve_two_stage_dispatch(load,pv,price,weights,soc,b,.95,lam);truth=actual[actual.date==d].sort_values('slot');ex=execute_fixed_grid_plan(d,plan.grid_purchase_kwh,truth.load_kwh.to_numpy(),truth.pv_actual_kwh.to_numpy(),point.load_pred_kwh.to_numpy(),point.pv_pred_kwh.to_numpy(),price,soc,b,str(lam));soc=float(ex.soc_end_kwh.iloc[-1]);costs.append(float((ex.plan_cost_yuan+ex.emergency_cost_yuan).sum()))
    rows.append({'lambda':lam,'january_total_cost_yuan':sum(costs),'january_daily_cvar95_yuan':max(costs),'january_max_day_cost_yuan':max(costs)})
selection=pd.DataFrame(rows);recommended=float(selection.sort_values(['january_total_cost_yuan','january_daily_cvar95_yuan']).iloc[0]['lambda']);risk_lambda=float(cfg['q2']['cvar_lambda']);selection['recommended']=selection['lambda'].eq(recommended);selection['risk_preference']=selection['lambda'].eq(risk_lambda);selection.to_csv(ROOT/'outputs/q2/cvar_parameter_selection.csv',index=False)
sens=[];d=pd.Timestamp('2025-01-31');point=oos[oos.date==d].sort_values('slot');truth=actual[actual.date==d].sort_values('slot');soc=float(warm[warm.date==pd.Timestamp('2025-01-30')].soc_end_kwh.iloc[-1])
for count in [20,50,100]:
    for seed in [2026,2027,2028]:
        sc=generate_joint_scenarios(actual,oos,point,d,count,seed);load=sc.pivot(index='scenario',columns='slot',values='load_kwh').to_numpy();pv=sc.pivot(index='scenario',columns='slot',values='pv_kwh').to_numpy();weights=sc.groupby('scenario').weight.first().to_numpy();plan=solve_two_stage_dispatch(load,pv,price,weights,soc,b,.95,risk_lambda);ex=execute_fixed_grid_plan(d,plan.grid_purchase_kwh,truth.load_kwh.to_numpy(),truth.pv_actual_kwh.to_numpy(),point.load_pred_kwh.to_numpy(),point.pv_pred_kwh.to_numpy(),price,soc,b,f'sens_{count}_{seed}');sens.append({'validation_date':d,'scenario_count':count,'random_seed':seed,'unique_historical_dates':sc.source_date.nunique(),'plan_cost_yuan':float(np.dot(price,plan.grid_purchase_kwh)),'planning_expected_emergency_cost_yuan':plan.expected_emergency_cost_yuan,'planning_cvar95_yuan':plan.cvar_yuan,'actual_execution_cost_yuan':float((ex.plan_cost_yuan+ex.emergency_cost_yuan).sum()),'actual_emergency_kwh':float(ex.emergency_purchase_kwh.sum())})
pd.DataFrame(sens).to_csv(ROOT/'outputs/q2/scenario_sensitivity_january.csv',index=False);print(selection.to_string(index=False));print(pd.DataFrame(sens).to_string(index=False));print('recommended',recommended,'risk_preference',risk_lambda,'runtime',time.time()-started)
