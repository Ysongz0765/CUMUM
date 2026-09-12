from dataclasses import dataclass
import numpy as np
from scipy.optimize import linprog

@dataclass
class DispatchResult:
    grid_purchase_kwh: np.ndarray; charge_kwh: np.ndarray; discharge_kwh: np.ndarray; soc_kwh: np.ndarray; curtailment_kwh: np.ndarray; total_cost_yuan: float; solver_status: str

def solve_deterministic_dispatch(load_kwh, pv_kwh, price_yuan_per_kwh, initial_soc_kwh, terminal_soc_kwh=None, battery_config=None):
    l,p,pr=map(lambda x: np.asarray(x,dtype=float), (load_kwh,pv_kwh,price_yuan_per_kwh)); n=len(l); cfg=battery_config or {'soc_min_kwh':1200,'soc_max_kwh':10800,'max_charge_power_kw':5000,'max_discharge_power_kw':5000,'charge_efficiency':.9,'discharge_efficiency':.9}; lim=cfg['max_charge_power_kw']/6; eta_c=cfg['charge_efficiency']; eta_d=cfg['discharge_efficiency']
    # x=[G,C,D,W,S], all energy in kWh per 10-minute interval
    c=np.r_[pr,np.zeros(4*n)]; Aeq=[]; beq=[]
    for t in range(n):
        row=np.zeros(5*n); row[t]=1; row[n+t]=-1; row[2*n+t]=1; row[3*n+t]=-1; Aeq.append(row); beq.append(l[t]-p[t])
        row=np.zeros(5*n); row[4*n+t]=1; row[ n+t]=-eta_c; row[2*n+t]=1/eta_d; Aeq.append(row); beq.append(initial_soc_kwh if t==0 else 0)
    # substitute previous SOC in recursion RHS via equality coupling
    for t in range(1,n): Aeq[2*t+1][4*n+t-1]=-1
    bounds=[(0,None)]*n+[(0,lim)]*n+[(0,lim)]*n+[(0,None)]*n+[(cfg['soc_min_kwh'],cfg['soc_max_kwh'])]*n
    if terminal_soc_kwh is not None: bounds[-1]=(terminal_soc_kwh,terminal_soc_kwh)
    r=linprog(c,A_eq=np.array(Aeq),b_eq=beq,bounds=bounds,method='highs');
    if not r.success: raise RuntimeError(r.message)
    x=r.x
    # tie-break: retain optimal cost and minimize activity
    c2=np.r_[np.zeros(n),np.ones(3*n),np.zeros(n)]; A2=np.array([c]); b2=np.array([r.fun+1e-6]); r2=linprog(c2,A_ub=A2,b_ub=b2,A_eq=np.array(Aeq),b_eq=beq,bounds=bounds,method='highs');
    if r2.success: x=r2.x
    return DispatchResult(x[:n],x[n:2*n],x[2*n:3*n],x[4*n:],x[3*n:4*n],float(np.dot(pr,x[:n])),'optimal')

def validate_dispatch_result(result, load_kwh, pv_kwh, price_yuan_per_kwh, initial_soc_kwh, terminal_soc_kwh=None, battery_config=None, tol=1e-5):
    cfg=battery_config or {'soc_min_kwh':1200,'soc_max_kwh':10800,'max_charge_power_kw':5000,'max_discharge_power_kw':5000,'charge_efficiency':.9,'discharge_efficiency':.9}; lim=cfg['max_charge_power_kw']/6
    bal=result.grid_purchase_kwh+pv_kwh+result.discharge_kwh-load_kwh-result.charge_kwh-result.curtailment_kwh; soc0=np.r_[initial_soc_kwh,result.soc_kwh[:-1]]; se=result.soc_kwh-(soc0+cfg['charge_efficiency']*result.charge_kwh-result.discharge_kwh/cfg['discharge_efficiency'])
    checks={'max_balance_error':float(np.max(np.abs(bal))),'max_soc_equation_error':float(np.max(np.abs(se))),'simultaneous_charge_discharge_count':int(np.sum((result.charge_kwh>tol)&(result.discharge_kwh>tol))),'cost_recalculated_yuan':float(np.dot(price_yuan_per_kwh,result.grid_purchase_kwh)),'charge_limit_violation_kwh':float(max(0,result.charge_kwh.max()-lim)),'discharge_limit_violation_kwh':float(max(0,result.discharge_kwh.max()-lim))}
    arrays=[result.grid_purchase_kwh,result.charge_kwh,result.discharge_kwh,result.curtailment_kwh,result.soc_kwh]
    if any(not np.isfinite(a).all() for a in arrays) or checks['max_balance_error']>tol or checks['max_soc_equation_error']>tol or result.soc_kwh.min()<cfg['soc_min_kwh']-tol or result.soc_kwh.max()>cfg['soc_max_kwh']+tol or checks['charge_limit_violation_kwh']>tol or checks['discharge_limit_violation_kwh']>tol or abs(result.soc_kwh[0]-(initial_soc_kwh+cfg['charge_efficiency']*result.charge_kwh[0]-result.discharge_kwh[0]/cfg['discharge_efficiency']))>tol or (terminal_soc_kwh is not None and abs(result.soc_kwh[-1]-terminal_soc_kwh)>tol): raise AssertionError(checks)
    return checks
