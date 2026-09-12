"""Fresh one-day Q4-2 reproduction without dispatch checkpoints."""
from pathlib import Path
import sys

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).parents[1] / "src"))
from microgrid.config import load_config
from microgrid.execution import execute_fixed_grid_plan
from microgrid.io import read_actual, get_daily_price
from microgrid.models.deterministic_dispatch import solve_deterministic_dispatch
from microgrid.models.stochastic_dispatch import solve_two_stage_dispatch
from microgrid.prediction import ForecastChoice, build_oos_forecasts, forecast_day
from microgrid.scenarios import generate_joint_scenarios


ROOT = Path(__file__).parents[1]
config = load_config(); battery = config["battery"]; q4 = config["q4"]
actual = read_actual(ROOT / "data/raw")
actual["load_kwh"] = actual.load_kw / 6
actual["pv_actual_kwh"] = actual.pv_actual_kw / 6
date = pd.Timestamp("2025-02-01")
oos = build_oos_forecasts(actual, pd.date_range("2025-01-08", date), ForecastChoice("ridge", "ridge"))
point = forecast_day(actual, date, "ridge", "ridge")
price = get_daily_price(ROOT / "data/raw", date, "attachment4").price_yuan_per_kwh.to_numpy(float)
scenario_frame = generate_joint_scenarios(actual, oos, point, date, q4["scenario_count_q4_2"], config["random_seed"])
load_scenarios = scenario_frame.pivot(index="scenario", columns="slot", values="load_kwh").to_numpy()
pv_scenarios = scenario_frame.pivot(index="scenario", columns="slot", values="pv_kwh").to_numpy()
weights = scenario_frame.groupby("scenario").weight.first().to_numpy()
initial_soc = float(pd.read_csv(ROOT / "outputs/q4/q4_january_initialization.csv").soc_end_kwh.iloc[-1])
day = actual[actual.date == date].sort_values("slot")
load_actual = day.load_kwh.to_numpy(float); pv_actual = day.pv_actual_kwh.to_numpy(float)
plans = {
    "B1": solve_deterministic_dispatch(point.load_pred_kwh, point.pv_pred_kwh, price, initial_soc, None, battery).grid_purchase_kwh,
    "B3": solve_two_stage_dispatch(load_scenarios, pv_scenarios, price, weights, initial_soc, battery, q4["cvar_alpha"], 0).grid_purchase_kwh,
    "B4": solve_two_stage_dispatch(load_scenarios, pv_scenarios, price, weights, initial_soc, battery, q4["cvar_alpha"], q4["b4_lambda"]).grid_purchase_kwh,
}
formal = pd.read_csv(ROOT / "outputs/q4/q4_2_execution_detail.csv", parse_dates=["date"])
fields = ["grid_purchase_kwh", "emergency_purchase_kwh", "charge_kwh", "discharge_kwh", "remaining_energy_kwh", "soc_end_kwh"]
errors = {}
for policy, plan in plans.items():
    executed = execute_fixed_grid_plan(
        date, plan, load_actual, pv_actual, point.load_pred_kwh.to_numpy(),
        point.pv_pred_kwh.to_numpy(), price, initial_soc, battery, policy,
    )
    expected = formal[(formal.policy == policy) & (formal.date == date)].sort_values("slot")
    for field in fields:
        errors[f"{policy}_{field}"] = float(np.max(np.abs(executed[field].to_numpy() - expected[field].to_numpy())))
maximum = max(errors.values())
print(f"fresh_q4_2_feb1_max_error={maximum:.12g}")
if maximum > 1e-6:
    print(errors)
    raise SystemExit(1)
