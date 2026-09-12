"""Causal fixed-plan storage feedback and settlement."""
import numpy as np
import pandas as pd
from scipy.optimize import linprog
from scipy.sparse import coo_matrix
from functools import lru_cache

@lru_cache(maxsize=144)
def _fixed_grid_matrix(h, eta_c, eta_d):
    rr=[];cc=[];vv=[]
    for j in range(h):
        row=2*j
        for col,val in ((j,1),(h+j,-1),(2*h+j,1),(3*h+j,-1)): rr.append(row);cc.append(col);vv.append(val)
        row+=1
        for col,val in ((4*h+j,1),(h+j,-eta_c),(2*h+j,1/eta_d)): rr.append(row);cc.append(col);vv.append(val)
        if j: rr.append(row);cc.append(4*h+j-1);vv.append(-1)
    return coo_matrix((vv,(rr,cc)),shape=(2*h,5*h)).tocsr()

def solve_fixed_grid_horizon(g_kwh, load_kwh, pv_kwh, price, initial_soc_kwh, battery_config, terminal_soc_kwh=None):
    """Solve a fixed-G horizon with fully supplied trajectories.

    This public helper is used for offline diagnostics.  Passing actual values
    for the whole horizon creates a perfect-information recourse lower bound;
    it must not be used by the causal execution policy.
    """
    h=len(g_kwh); eta_c=battery_config['charge_efficiency']; eta_d=battery_config['discharge_efficiency']; cmax=battery_config['max_charge_power_kw']/6; dmax=battery_config['max_discharge_power_kw']/6
    # x=[R,C,D,W,S], all quantities are kWh per 10-minute slot.
    n=5*h; obj=np.zeros(n); obj[:h]=5*np.asarray(price,float); obj[h:4*h]=1e-7
    beq=[]
    for j in range(h):
        beq.append(load_kwh[j]-g_kwh[j]-pv_kwh[j]);beq.append(0. if j else initial_soc_kwh)
    bounds=[(0,None)]*h+[(0,cmax)]*h+[(0,dmax)]*h+[(0,None)]*h+[(battery_config['soc_min_kwh'],battery_config['soc_max_kwh'])]*h
    if terminal_soc_kwh is not None: bounds[-1]=(terminal_soc_kwh,terminal_soc_kwh)
    r=linprog(obj,A_eq=_fixed_grid_matrix(h,eta_c,eta_d),b_eq=np.asarray(beq),bounds=bounds,method='highs')
    if not r.success: raise RuntimeError(f'fixed-G recourse infeasible: {r.message}')
    x=r.x
    return pd.DataFrame({
        'slot':np.arange(1,h+1),
        'emergency_purchase_kwh':x[:h],
        'charge_kwh':x[h:2*h],
        'discharge_kwh':x[2*h:3*h],
        'remaining_energy_kwh':x[3*h:4*h],
        'soc_end_kwh':x[4*h:5*h],
        'emergency_cost_yuan':5*np.asarray(price,float)*x[:h],
    })

def _solve_fixed_grid_remaining(g_kwh, load_kwh, pv_kwh, price, initial_soc_kwh, battery_config, terminal_soc_kwh=None):
    """Solve the remaining fixed-G recourse LP and return its first action."""
    horizon=solve_fixed_grid_horizon(g_kwh,load_kwh,pv_kwh,price,initial_soc_kwh,battery_config,terminal_soc_kwh)
    first=horizon.iloc[0]
    return tuple(float(first[name]) for name in ('emergency_purchase_kwh','charge_kwh','discharge_kwh','remaining_energy_kwh','soc_end_kwh'))

def execute_fixed_grid_plan(date,grid_plan_kwh,load_actual_kwh,pv_actual_kwh,load_forecast_kwh,pv_forecast_kwh,price,initial_soc_kwh,battery_config,policy,terminal_soc_kwh=None):
    T=len(grid_plan_kwh); s=float(initial_soc_kwh); rows=[]; eta_c=battery_config['charge_efficiency'];eta_d=battery_config['discharge_efficiency'];smin=battery_config['soc_min_kwh'];smax=battery_config['soc_max_kwh'];cmax=battery_config['max_charge_power_kw']/6;dmax=battery_config['max_discharge_power_kw']/6
    for t in range(T):
        before=s
        # The current observation replaces only the first forecast point. Future points remain day-ahead forecasts.
        la=np.r_[float(load_actual_kwh[t]),np.asarray(load_forecast_kwh[t+1:],float)]; pa=np.r_[float(pv_actual_kwh[t]),np.asarray(pv_forecast_kwh[t+1:],float)]; gg=np.asarray(grid_plan_kwh[t:],float); pp=np.asarray(price[t:],float)
        emergency,charge,discharge,remaining,next_soc=_solve_fixed_grid_remaining(gg,la,pa,pp,s,battery_config,terminal_soc_kwh); s=next_soc
        balance=grid_plan_kwh[t]+emergency+pv_actual_kwh[t]+discharge-load_actual_kwh[t]-charge-remaining
        if abs(balance)>1e-7 or not (smin-1e-7<=s<=smax+1e-7): raise AssertionError((date,t+1,balance,s))
        rows.append({'date':pd.Timestamp(date),'slot':t+1,'policy':policy,'price_yuan_per_kwh':float(price[t]),'load_actual_kwh':float(load_actual_kwh[t]),'pv_actual_kwh':float(pv_actual_kwh[t]),'load_forecast_kwh':float(load_forecast_kwh[t]),'pv_forecast_kwh':float(pv_forecast_kwh[t]),'grid_purchase_kwh':float(grid_plan_kwh[t]),'emergency_purchase_kwh':emergency,'charge_kwh':charge,'discharge_kwh':discharge,'remaining_energy_kwh':remaining,'soc_start_kwh':before,'soc_end_kwh':s,'plan_cost_yuan':float(price[t]*grid_plan_kwh[t]),'emergency_cost_yuan':float(5*price[t]*emergency),'balance_error_kwh':balance})
    return pd.DataFrame(rows)
