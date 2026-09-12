"""Question 3 forecasts, causal rolling adjustment, and final settlement."""
from dataclasses import dataclass
import numpy as np
import pandas as pd
from .io import build_10min_pv_forecast
from .execution import _solve_fixed_grid_remaining
from .models.stochastic_dispatch import solve_two_stage_dispatch
from .models.adjustment_dispatch import solve_adjustment_dispatch

ISSUE_SLOTS={0:0,6:36,12:72,18:108}

def issue_pv_day(forecast_long,date,issue_hour):
    d=pd.Timestamp(date).normalize();h=int(issue_hour);x=build_10min_pv_forecast(forecast_long,d,f'{h}:00')
    targets=pd.DataFrame({'target_datetime':[d+pd.Timedelta(minutes=10*(s+1)) for s in range(144)],'slot':np.arange(1,145)})
    z=targets.merge(x,on='target_datetime',how='left',validate='one_to_one')
    start=ISSUE_SLOTS[h]
    if z.loc[start:,'pv_forecast_kw'].isna().any(): raise ValueError(f'incomplete attachment3 interpolation {d.date()} {h}:00')
    values=z.pv_forecast_kw.to_numpy(float)/6
    values[:start]=np.nan
    return values

def joint_issue_scenarios(actual,oos,forecast_long,date,issue_hour,load_point,pv_point,count,lookback_days,seed):
    d=pd.Timestamp(date).normalize();start=ISSUE_SLOTS[int(issue_hour)]
    available=sorted(set(actual.loc[actual.date<d,'date']) & set(oos.loc[oos.date<d,'date']))[-int(lookback_days):]
    valid=[]
    issue_dates=set(forecast_long.loc[forecast_long.issue_hour==int(issue_hour),'date'])
    for sd in available:
        if sd in issue_dates: valid.append(pd.Timestamp(sd))
    if not valid: raise ValueError(f'no historical issue residual before {d.date()} {issue_hour}:00')
    rng=np.random.default_rng(int(seed)+int(d.strftime('%j'))*97+int(issue_hour)*1009)
    replace=len(valid)<count; chosen=rng.choice(np.asarray(valid,dtype='datetime64[ns]'),size=count,replace=replace)
    loads=[];pvs=[];sources=[]
    for raw_sd in chosen:
        sd=pd.Timestamp(raw_sd);a=actual[actual.date==sd].sort_values('slot');f=oos[oos.date==sd].sort_values('slot')
        src_pv=issue_pv_day(forecast_long,sd,issue_hour)
        lr=a.load_kwh.to_numpy()[start:]-f.load_pred_kwh.to_numpy()[start:]
        pr=a.pv_actual_kwh.to_numpy()[start:]-src_pv[start:]
        loads.append(np.maximum(0,np.asarray(load_point[start:],float)+lr))
        pvs.append(np.maximum(0,np.asarray(pv_point[start:],float)+pr))
        sources.append(sd)
    return np.asarray(loads),np.asarray(pvs),np.ones(count)/count,pd.DataFrame({'source_date':sources,'target_date':d,'issue_hour':issue_hour,'weight':1/count,'training_cutoff':d-pd.Timedelta(days=1)})

def settlement_components(original_plan,final_plan,price):
    g0=np.asarray(original_plan,float);f=np.asarray(final_plan,float);p=np.asarray(price,float)
    plus=np.maximum(f-g0,0);minus=np.maximum(g0-f,0)
    original=p*g0
    final=original+1.5*p*plus-.5*p*minus
    equivalent=p*f+.5*p*np.abs(f-g0)
    if not np.allclose(final,equivalent,atol=1e-8,rtol=0): raise AssertionError('settlement identity')
    return original,final,plus,minus

@dataclass
class Q3DayResult:
    execution: pd.DataFrame
    revisions: pd.DataFrame
    snapshots: pd.DataFrame
    scenario_sources: pd.DataFrame

def run_q3_day(date,policy,initial_soc,actual,oos,forecast_long,price,battery,q3,delta_yuan,seed):
    d=pd.Timestamp(date).normalize();day=actual[actual.date==d].sort_values('slot');point=oos[oos.date==d].sort_values('slot')
    if len(day)!=144 or len(point)!=144: raise KeyError(d)
    load_point=point.load_pred_kwh.to_numpy(float);pv0=issue_pv_day(forecast_long,d,0);pv_active=pv0.copy()
    lsc,psc,w,src0=joint_issue_scenarios(actual,oos,forecast_long,d,0,load_point,pv0,q3['scenario_count'],q3['scenario_lookback_days'],seed)
    initial=solve_two_stage_dispatch(lsc,psc,price,w,initial_soc,battery,q3['cvar_alpha'],q3['cvar_lambda'])
    g0=initial.grid_purchase_kwh.copy();current=g0.copy();s=float(initial_soc);rows=[];logs=[];snaps=[];sources=[src0.assign(policy=policy,decision_time=d)]
    for t in range(144):
        issue_hour=t//6 if t in (36,72,108) else None
        if issue_hour is not None and policy in ('C1','C2','C3'):
            pv_active=issue_pv_day(forecast_long,d,issue_hour)
            pv_active[:t]=pv0[:t]
        if issue_hour is not None and policy in ('C2','C3'):
            lsc,psc,w,src=joint_issue_scenarios(actual,oos,forecast_long,d,issue_hour,load_point,pv_active,q3['scenario_count'],q3['scenario_lookback_days'],seed)
            sources.append(src.assign(policy=policy,decision_time=d+pd.Timedelta(hours=issue_hour)))
            keep=solve_adjustment_dispatch(lsc,psc,np.asarray(price)[t:],w,s,battery,g0[t:],current[t:],q3['cvar_alpha'],q3['cvar_lambda'])
            adjust=solve_adjustment_dispatch(lsc,psc,np.asarray(price)[t:],w,s,battery,g0[t:],None,q3['cvar_alpha'],q3['cvar_lambda'])
            nv=keep.objective_yuan-adjust.objective_yuan; threshold=0. if policy=='C2' else float(delta_yuan);trigger=bool(nv>threshold+1e-7)
            candidate=adjust.final_plan_kwh
            before=current[t:].copy()
            if trigger: current[t:]=candidate
            _,final_cost,plus,minus=settlement_components(g0[t:],candidate,np.asarray(price)[t:])
            logs.append({'date':d,'policy':policy,'issue_hour':issue_hour,'decision_time':d+pd.Timedelta(hours=issue_hour),'j_keep_yuan':keep.objective_yuan,'j_adjust_yuan':adjust.objective_yuan,'nv_yuan':nv,'delta_yuan':threshold,'triggered':trigger,'candidate_increase_kwh':plus.sum(),'candidate_decrease_kwh':minus.sum(),'candidate_non_emergency_cost_yuan':final_cost.sum(),'max_candidate_change_kwh':np.max(np.abs(candidate-before))})
            for k in range(t,144):snaps.append({'date':d,'policy':policy,'issue_hour':issue_hour,'decision_time':d+pd.Timedelta(hours=issue_hour),'slot':k+1,'plan_before_kwh':before[k-t],'candidate_plan_kwh':candidate[k-t],'effective_plan_kwh':current[k]})
        before_soc=s
        future_pv=pv0 if policy=='C0' else pv_active
        la=np.r_[day.load_kwh.iloc[t],load_point[t+1:]];pa=np.r_[day.pv_actual_kwh.iloc[t],future_pv[t+1:]]
        r,c,dis,waste,s=_solve_fixed_grid_remaining(current[t:],la,pa,np.asarray(price)[t:],s,battery,None)
        balance=current[t]+r+day.pv_actual_kwh.iloc[t]+dis-day.load_kwh.iloc[t]-c-waste
        rows.append({'date':d,'slot':t+1,'policy':policy,'price_yuan_per_kwh':price[t],'load_actual_kwh':day.load_kwh.iloc[t],'pv_actual_kwh':day.pv_actual_kwh.iloc[t],'load_forecast_kwh':load_point[t],'pv_forecast_kwh':future_pv[t],'original_grid_plan_kwh':g0[t],'final_grid_plan_kwh':current[t],'emergency_purchase_kwh':r,'charge_kwh':c,'discharge_kwh':dis,'remaining_energy_kwh':waste,'soc_start_kwh':before_soc,'soc_end_kwh':s,'balance_error_kwh':balance})
    ex=pd.DataFrame(rows);orig,final,plus,minus=settlement_components(ex.original_grid_plan_kwh,ex.final_grid_plan_kwh,price)
    ex['original_plan_cost_yuan']=orig;ex['final_non_emergency_cost_yuan']=final;ex['adjustment_increase_kwh']=plus;ex['adjustment_decrease_kwh']=minus;ex['adjustment_net_cost_yuan']=final-orig;ex['emergency_cost_yuan']=5*ex.price_yuan_per_kwh*ex.emergency_purchase_kwh;ex['total_cost_yuan']=ex.final_non_emergency_cost_yuan+ex.emergency_cost_yuan
    return Q3DayResult(ex,pd.DataFrame(logs),pd.DataFrame(snaps),pd.concat(sources,ignore_index=True))
