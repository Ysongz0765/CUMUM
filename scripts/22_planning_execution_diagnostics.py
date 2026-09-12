from pathlib import Path
import sys

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).parents[1] / "src"))
from microgrid.config import load_config
from microgrid.execution import solve_fixed_grid_horizon
from microgrid.io import read_actual


ROOT = Path(__file__).parents[1]
OUT = ROOT / "outputs/diagnostics"
OUT.mkdir(parents=True, exist_ok=True)
BATTERY = load_config()["battery"]
raw = read_actual(ROOT / "data/raw")
raw["load_kwh"] = raw.load_kw / 6
raw["pv_actual_kwh"] = raw.pv_actual_kw / 6
raw = raw[["date", "slot", "load_kwh", "pv_actual_kwh"]]

branches = [
    ("Q2", ROOT / "outputs/q2/q2_execution_detail.csv", ROOT / "outputs/q2/planning_diagnostics.csv", "grid_purchase_kwh", "expected_scenario_emergency_cost_yuan"),
    ("Q4-2", ROOT / "outputs/q4/q4_2_execution_detail.csv", ROOT / "outputs/q4/q4_2_planning_diagnostics.csv", "grid_purchase_kwh", "expected_scenario_emergency_cost_yuan"),
]
lower_bound_rows = []
gap_rows = []
for branch, execution_path, planning_path, grid_field, expected_field in branches:
    execution = pd.read_csv(execution_path, parse_dates=["date"])
    planning = pd.read_csv(planning_path, parse_dates=["date"])
    for (policy, date), day in execution.groupby(["policy", "date"], sort=True):
        day = day.sort_values("slot")
        actual = raw[raw.date == date].sort_values("slot")
        if len(actual) != 144 or not np.allclose(day.load_actual_kwh, actual.load_kwh, atol=1e-6, rtol=0) or not np.allclose(day.pv_actual_kwh, actual.pv_actual_kwh, atol=1e-6, rtol=0):
            raise AssertionError(f"{branch} actual values do not match raw Attachment 2 on {date.date()}")
        offline = solve_fixed_grid_horizon(
            day[grid_field].to_numpy(float), actual.load_kwh.to_numpy(float),
            actual.pv_actual_kwh.to_numpy(float), day.price_yuan_per_kwh.to_numpy(float),
            float(day.soc_start_kwh.iloc[0]), BATTERY,
        )
        actual_emergency = float(day.emergency_cost_yuan.sum())
        lower = float(offline.emergency_cost_yuan.sum())
        lower_bound_rows.append({
            "branch": branch, "policy": policy, "date": date,
            "initial_soc_kwh": day.soc_start_kwh.iloc[0],
            "actual_causal_emergency_cost_yuan": actual_emergency,
            "fixed_g_perfect_information_emergency_cost_yuan": lower,
            "causal_execution_gap_yuan": actual_emergency - lower,
            "actual_emergency_purchase_kwh": day.emergency_purchase_kwh.sum(),
            "perfect_information_emergency_purchase_kwh": offline.emergency_purchase_kwh.sum(),
            "perfect_information_terminal_soc_kwh": offline.soc_end_kwh.iloc[-1],
        })
    actual_daily = execution.groupby(["policy", "date"]).emergency_cost_yuan.sum().rename("actual_emergency_cost_yuan").reset_index()
    joined = planning.merge(actual_daily, on=["policy", "date"], validate="one_to_one")
    lower_frame = pd.DataFrame(lower_bound_rows)
    joined = joined.merge(lower_frame[lower_frame.branch == branch][["policy", "date", "fixed_g_perfect_information_emergency_cost_yuan"]], on=["policy", "date"], validate="one_to_one")
    for policy, group in joined.groupby("policy"):
        planned = group[expected_field].sum(min_count=1)
        actual_cost = group.actual_emergency_cost_yuan.sum()
        offline_cost = group.fixed_g_perfect_information_emergency_cost_yuan.sum()
        gap_rows.append({
            "branch": branch, "policy": policy,
            "planning_expected_scenario_emergency_cost_yuan": planned,
            "actual_causal_emergency_cost_yuan": actual_cost,
            "fixed_g_perfect_information_emergency_cost_yuan": offline_cost,
            "actual_minus_planning_expectation_yuan": actual_cost - planned if pd.notna(planned) else np.nan,
            "actual_minus_perfect_information_yuan": actual_cost - offline_cost,
            "actual_to_planning_ratio": actual_cost / planned if pd.notna(planned) and planned > 0 else np.nan,
        })

lower_bounds = pd.DataFrame(lower_bound_rows)
lower_bounds.to_csv(OUT / "fixed_g_perfect_information_recourse.csv", index=False)
gaps = pd.DataFrame(gap_rows)
gaps.to_csv(OUT / "planning_execution_gap.csv", index=False)
print(gaps.to_string(index=False))
