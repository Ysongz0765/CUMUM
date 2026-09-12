"""Two-stage adjustment model for Question 3 final-vs-original settlement."""
from dataclasses import dataclass
import numpy as np
from scipy.optimize import linprog
from scipy.sparse import coo_matrix
from .stochastic_dispatch import empirical_cvar

@dataclass
class AdjustmentResult:
    final_plan_kwh: np.ndarray
    objective_yuan: float
    expected_emergency_cost_yuan: float
    scenario_emergency_cost_yuan: np.ndarray
    cvar_yuan: float
    max_equality_residual: float

def solve_adjustment_dispatch(load_scenarios_kwh,pv_scenarios_kwh,price,weights,
                              initial_soc_kwh,battery_config,original_plan_kwh,
                              fixed_plan_kwh=None,cvar_alpha=.95,cvar_lambda=0.0):
    load=np.asarray(load_scenarios_kwh,float);pv=np.asarray(pv_scenarios_kwh,float)
    price=np.asarray(price,float);weights=np.asarray(weights,float);g0=np.asarray(original_plan_kwh,float)
    nsc,T=load.shape
    if pv.shape!=load.shape or len(price)!=T or len(g0)!=T or len(weights)!=nsc: raise ValueError('scenario dimensions')
    weights=weights/weights.sum(); base=3*T; block=5*T; use_cvar=cvar_lambda>0
    zidx=base+nsc*block;uidx=zidx+1;nvar=base+nsc*block+(1+nsc if use_cvar else 0)
    # x=[F,Aplus,Aminus,(R,C,D,W,S)_scenario,z,u].
    obj=np.zeros(nvar);obj[:T]=price;obj[T:3*T]=.5*np.r_[price,price]
    for s in range(nsc): obj[base+s*block:base+s*block+T]=weights[s]*5*price
    if use_cvar:
        obj[zidx]=cvar_lambda;obj[uidx:uidx+nsc]=cvar_lambda*weights/(1-cvar_alpha)
    rr=[];cc=[];vv=[];beq=[];row=0
    for t in range(T):
        for col,val in ((t,1),(T+t,-1),(2*T+t,1)):rr.append(row);cc.append(col);vv.append(val)
        beq.append(g0[t]);row+=1
    for s in range(nsc):
        off=base+s*block;R=off;C=off+T;D=off+2*T;W=off+3*T;S=off+4*T
        for t in range(T):
            for col,val in ((t,1),(R+t,1),(C+t,-1),(D+t,1),(W+t,-1)):rr.append(row);cc.append(col);vv.append(val)
            beq.append(load[s,t]-pv[s,t]);row+=1
            for col,val in ((S+t,1),(C+t,-battery_config['charge_efficiency']),(D+t,1/battery_config['discharge_efficiency'])):rr.append(row);cc.append(col);vv.append(val)
            if t:rr.append(row);cc.append(S+t-1);vv.append(-1);beq.append(0.)
            else:beq.append(float(initial_soc_kwh))
            row+=1
    Aeq=coo_matrix((vv,(rr,cc)),shape=(row,nvar)).tocsr();beq=np.asarray(beq)
    ar=[];ac=[];av=[]
    if use_cvar:
        for s in range(nsc):
            off=base+s*block
            for t in range(T):ar.append(s);ac.append(off+t);av.append(5*price[t])
            ar.extend([s,s]);ac.extend([zidx,uidx+s]);av.extend([-1,-1])
        Aub=coo_matrix((av,(ar,ac)),shape=(nsc,nvar)).tocsr();bub=np.zeros(nsc)
    else:Aub=bub=None
    cmax=battery_config['max_charge_power_kw']/6;dmax=battery_config['max_discharge_power_kw']/6
    fbounds=[(0,None)]*T if fixed_plan_kwh is None else [(float(v),float(v)) for v in fixed_plan_kwh]
    bounds=fbounds+[(0,None)]*(2*T)
    for _ in range(nsc):bounds += [(0,None)]*T+[(0,cmax)]*T+[(0,dmax)]*T+[(0,None)]*T+[(battery_config['soc_min_kwh'],battery_config['soc_max_kwh'])]*T
    if use_cvar:bounds += [(None,None)]+[(0,None)]*nsc
    r=linprog(obj,A_ub=Aub,b_ub=bub,A_eq=Aeq,b_eq=beq,bounds=bounds,method='highs')
    if not r.success:raise RuntimeError(f'adjustment LP infeasible: {r.message}')
    costs=np.array([np.dot(5*price,r.x[base+s*block:base+s*block+T]) for s in range(nsc)])
    return AdjustmentResult(r.x[:T],float(r.fun),float(weights@costs),costs,
                            float(empirical_cvar(costs,weights,cvar_alpha)),
                            float(np.max(np.abs(Aeq@r.x-beq))))
