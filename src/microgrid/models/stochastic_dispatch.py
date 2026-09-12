"""Sparse two-stage stochastic dispatch with optional CVaR."""
from dataclasses import dataclass
import numpy as np
from scipy.optimize import linprog
from scipy.sparse import coo_matrix, vstack

@dataclass
class StochasticResult:
    grid_purchase_kwh: np.ndarray
    objective_yuan: float
    expected_emergency_cost_yuan: float
    scenario_emergency_cost_yuan: np.ndarray
    cvar_yuan: float | None
    solver_status: str
    max_equality_residual: float

def empirical_cvar(costs, weights, alpha=.95):
    costs=np.asarray(costs,float); weights=np.asarray(weights,float); order=np.argsort(costs); c=costs[order]; w=weights[order]; tail=1-alpha; remaining=tail; total=0.0
    for ci,wi in zip(c[::-1],w[::-1]):
        take=min(remaining,wi); total+=take*ci; remaining-=take
        if remaining<=1e-12: break
    return total/tail

def solve_two_stage_dispatch(load_scenarios_kwh,pv_scenarios_kwh,price_yuan_per_kwh,weights,initial_soc_kwh,battery_config,cvar_alpha=.95,cvar_lambda=0.0):
    load=np.asarray(load_scenarios_kwh,float); pv=np.asarray(pv_scenarios_kwh,float); price=np.asarray(price_yuan_per_kwh,float); weights=np.asarray(weights,float); nsc,T=load.shape
    if pv.shape!=load.shape or len(price)!=T or len(weights)!=nsc: raise ValueError("scenario dimensions")
    weights=weights/weights.sum(); block=5*T; base=T; use_cvar=cvar_lambda>0; zidx=base+nsc*block; uidx=zidx+1; nvar=base+nsc*block+(1+nsc if use_cvar else 0)
    obj=np.zeros(nvar); obj[:T]=price
    for s in range(nsc): obj[base+s*block:base+s*block+T]=weights[s]*5*price
    if use_cvar: obj[zidx]=cvar_lambda; obj[uidx:uidx+nsc]=cvar_lambda*weights/(1-cvar_alpha)
    rr=[];cc=[];vv=[];b=[]; row=0
    for s in range(nsc):
        off=base+s*block; R=off; C=off+T; D=off+2*T; W=off+3*T; S=off+4*T
        for t in range(T):
            for j,val in ((t,1),(R+t,1),(C+t,-1),(D+t,1),(W+t,-1)): rr.append(row);cc.append(j);vv.append(val)
            b.append(load[s,t]-pv[s,t]);row+=1
            for j,val in ((S+t,1),(C+t,-battery_config['charge_efficiency']),(D+t,1/battery_config['discharge_efficiency'])): rr.append(row);cc.append(j);vv.append(val)
            if t: rr.append(row);cc.append(S+t-1);vv.append(-1);b.append(0)
            else: b.append(initial_soc_kwh)
            row+=1
    Aeq=coo_matrix((vv,(rr,cc)),shape=(row,nvar)).tocsr(); beq=np.asarray(b)
    Aub=None;bub=None
    if use_cvar:
        ar=[];ac=[];av=[]
        for s in range(nsc):
            off=base+s*block
            for t in range(T): ar.append(s);ac.append(off+t);av.append(5*price[t])
            ar.extend([s,s]);ac.extend([zidx,uidx+s]);av.extend([-1,-1])
        Aub=coo_matrix((av,(ar,ac)),shape=(nsc,nvar)).tocsr();bub=np.zeros(nsc)
    cmax=battery_config['max_charge_power_kw']/6; dmax=battery_config['max_discharge_power_kw']/6
    bounds=[(0,None)]*T
    for _ in range(nsc): bounds += [(0,None)]*T+[(0,cmax)]*T+[(0,dmax)]*T+[(0,None)]*T+[(battery_config['soc_min_kwh'],battery_config['soc_max_kwh'])]*T
    if use_cvar: bounds += [(None,None)]+[(0,None)]*nsc
    result=linprog(obj,A_ub=Aub,b_ub=bub,A_eq=Aeq,b_eq=beq,bounds=bounds,method='highs')
    if not result.success: raise RuntimeError(result.message)
    costs=[]
    for s in range(nsc): costs.append(float(np.dot(5*price,result.x[base+s*block:base+s*block+T])))
    costs=np.asarray(costs); expected=float(np.dot(weights,costs)); cvar=empirical_cvar(costs,weights,cvar_alpha) if use_cvar else None
    residual=float(np.max(np.abs(Aeq@result.x-beq)))
    if residual>1e-6: raise AssertionError(f"stochastic equality residual {residual}")
    return StochasticResult(result.x[:T],float(result.fun),expected,costs,cvar,"optimal",residual)
