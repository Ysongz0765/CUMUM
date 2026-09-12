import numpy as np
from microgrid.models.deterministic_dispatch import solve_deterministic_dispatch
def test_dispatch_solver_success():
 r=solve_deterministic_dispatch([5,5,5],[0,0,0],[1,10,1],5,5,{'soc_min_kwh':0,'soc_max_kwh':20,'max_charge_power_kw':60,'max_discharge_power_kw':60,'charge_efficiency':1,'discharge_efficiency':1}); assert r.solver_status=='optimal'
def test_solver_without_terminal_soc(): assert solve_deterministic_dispatch([1],[0],[1],6000).solver_status=='optimal'
