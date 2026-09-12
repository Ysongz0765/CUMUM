"""Question 3 forecasts, causal rolling adjustment, and final settlement."""
from dataclasses import dataclass
import numpy as np
import pandas as pd
from .io import build_10min_pv_forecast
from .execution import _solve_fixed_grid_remaining
from .models.stochastic_dispatch import solve_two_stage_dispatch
from .models.adjustment_dispatch import solve_adjustment_dispatch

ISSUE_SLOTS={0:0,6:36,12:72,18:108}

def _issue_anchor(actual, date, issue_hour):
    d=pd.Timestamp(date).normalize();h=int(issue_hour)
    anchor_date,slot=(d-pd.Timedelta(days=1),144) if h==0 else (d,h*6)
    if actual is None:
        return None,"first_hour_forecast_fallback:no_actual_frame"
    row=actual[(actual.date==anchor_date)&(actual.slot==slot)]
    if row.empty:
        return None,f"first_hour_forecast_fallback:no_completed_interval:{anchor_date.date()}:slot{slot}"
    if len(row)!=1: raise ValueError(f'duplicate PV anchor {anchor_date.date()} slot {slot}')
    if 'pv_actual_kw' in row:
        value=float(row.pv_actual_kw.iloc[0])
    elif 'pv_actual_kwh' in row:
        value=float(row.pv_actual_kwh.iloc[0])*6.0
    else:
        raise KeyError('actual data must contain pv_actual_kw or pv_actual_kwh')
    source=f"attachment2:{anchor_date.date()}:slot{slot}:ended_at:{d+pd.Timedelta(hours=h)}"
    return value,source

def issue_pv_day(forecast_long,date,issue_hour,actual=None,boundary_method='observed_anchor',return_metadata=False):
    d=pd.Timestamp(date).normalize();h=int(issue_hour)
    anchor_kw,anchor_source=_issue_anchor(actual,d,h)
    x=build_10min_pv_forecast(
        forecast_long,d,f'{h}:00',left_anchor_kw=anchor_kw,
        anchor_source=anchor_source,boundary_method=boundary_method,
    )
    targets=pd.DataFrame({'target_datetime':[d+pd.Timedelta(minutes=10*(s+1)) for s in range(144)],'slot':np.arange(1,145)})
    z=targets.merge(x,on='target_datetime',how='left',validate='one_to_one')
    start=ISSUE_SLOTS[h]
    if z.loc[start:,'pv_forecast_kw'].isna().any(): raise ValueError(f'incomplete attachment3 interpolation {d.date()} {h}:00')
    values=z.pv_forecast_kw.to_numpy(float)/6
    values[:start]=np.nan
    if return_metadata:
        cols=['issue_datetime','observation_cutoff','anchor_kw','anchor_source','boundary_method','interpolation_method']
        return values,x.iloc[0][cols].to_dict()
    return values

def joint_issue_scenarios(actual,oos,forecast_long,date,issue_hour,load_point,pv_point,count,lookback_days,seed,boundary_method='observed_anchor'):
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
        src_pv,meta=issue_pv_day(forecast_long,sd,issue_hour,actual,boundary_method,True)
        lr=a.load_kwh.to_numpy()[start:]-f.load_pred_kwh.to_numpy()[start:]
        pr=a.pv_actual_kwh.to_numpy()[start:]-src_pv[start:]
        loads.append(np.maximum(0,np.asarray(load_point[start:],float)+lr))
        pvs.append(np.maximum(0,np.asarray(pv_point[start:],float)+pr))
        sources.append({'source_date':sd,'source_anchor_kw':meta['anchor_kw'],'source_anchor_source':meta['anchor_source'],'source_observation_cutoff':meta['observation_cutoff']})
    source_frame=pd.DataFrame(sources).assign(target_date=d,issue_hour=issue_hour,weight=1/count,training_cutoff=d-pd.Timedelta(days=1),boundary_method=boundary_method)
    return np.asarray(loads),np.asarray(pvs),np.ones(count)/count,source_frame

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

def run_q3_day(date,policy,initial_soc,actual,oos,forecast_long,price,battery,q3,delta_yuan,seed,allowed_update_hours=None,boundary_method='observed_anchor'):
    d=pd.Timestamp(date).normalize();day=actual[actual.date==d].sort_values('slot');point=oos[oos.date==d].sort_values('slot')
    if len(day)!=144 or len(point)!=144: raise KeyError(d)
    configured_updates={int(h) for h in q3.get('issue_hours',[0,6,12,18]) if int(h)!=0}
    allowed_updates=configured_updates if allowed_update_hours is None else {int(h) for h in allowed_update_hours}
    if not allowed_updates.issubset(configured_updates): raise ValueError(f'unsupported update hour(s): {sorted(allowed_updates-configured_updates)}')
    load_point=point.load_pred_kwh.to_numpy(float);pv0,pv0_meta=issue_pv_day(forecast_long,d,0,actual,boundary_method,True);pv_active=pv0.copy()
    lsc,psc,w,src0=joint_issue_scenarios(actual,oos,forecast_long,d,0,load_point,pv0,q3['scenario_count'],q3['scenario_lookback_days'],seed,boundary_method)
    initial=solve_two_stage_dispatch(lsc,psc,price,w,initial_soc,battery,q3['cvar_alpha'],q3['cvar_lambda'])
    g0=initial.grid_purchase_kwh.copy();current=g0.copy();s=float(initial_soc);rows=[];logs=[];snaps=[];sources=[src0.assign(policy=policy,decision_time=d,target_anchor_kw=pv0_meta['anchor_kw'],target_anchor_source=pv0_meta['anchor_source'],target_observation_cutoff=pv0_meta['observation_cutoff'])]
    for t in range(144):
        candidate_hour=t//6 if t in (36,72,108) else None
        issue_hour=candidate_hour if candidate_hour in allowed_updates else None
        if issue_hour is not None and policy in ('C1','C2','C3'):
            pv_active,pv_meta=issue_pv_day(forecast_long,d,issue_hour,actual,boundary_method,True)
            pv_active[:t]=pv0[:t]
        if issue_hour is not None and policy in ('C2','C3'):
            lsc,psc,w,src=joint_issue_scenarios(actual,oos,forecast_long,d,issue_hour,load_point,pv_active,q3['scenario_count'],q3['scenario_lookback_days'],seed,boundary_method)
            sources.append(src.assign(policy=policy,decision_time=d+pd.Timedelta(hours=issue_hour),target_anchor_kw=pv_meta['anchor_kw'],target_anchor_source=pv_meta['anchor_source'],target_observation_cutoff=pv_meta['observation_cutoff']))
            keep=solve_adjustment_dispatch(lsc,psc,np.asarray(price)[t:],w,s,battery,g0[t:],current[t:],q3['cvar_alpha'],q3['cvar_lambda'])
            adjust=solve_adjustment_dispatch(lsc,psc,np.asarray(price)[t:],w,s,battery,g0[t:],None,q3['cvar_alpha'],q3['cvar_lambda'])
            nv=keep.objective_yuan-adjust.objective_yuan; threshold=0. if policy=='C2' else float(delta_yuan);trigger=bool(nv>threshold+1e-7)
            candidate=adjust.final_plan_kwh
            before=current[t:].copy()
            if trigger: current[t:]=candidate
            _,final_cost,plus,minus=settlement_components(g0[t:],candidate,np.asarray(price)[t:])
            logs.append({'date':d,'policy':policy,'issue_hour':issue_hour,'decision_time':d+pd.Timedelta(hours=issue_hour),'anchor_kw':pv_meta['anchor_kw'],'anchor_source':pv_meta['anchor_source'],'observation_cutoff':pv_meta['observation_cutoff'],'boundary_method':boundary_method,'j_keep_yuan':keep.objective_yuan,'j_adjust_yuan':adjust.objective_yuan,'nv_yuan':nv,'delta_yuan':threshold,'triggered':trigger,'candidate_increase_kwh':plus.sum(),'candidate_decrease_kwh':minus.sum(),'candidate_non_emergency_cost_yuan':final_cost.sum(),'max_candidate_change_kwh':np.max(np.abs(candidate-before))})
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
