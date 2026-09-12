from pathlib import Path
import json
import sys
import time

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).parents[1] / "src"))
from microgrid.config import load_config
from microgrid.execution import execute_fixed_grid_plan
from microgrid.io import read_processed
from microgrid.models.deterministic_dispatch import solve_deterministic_dispatch
from microgrid.models.stochastic_dispatch import solve_two_stage_dispatch
from microgrid.q4 import (
    FORMAL_DATES, dependency_signature, export_q4_2, get_or_build_oos,
    get_or_build_warmup, price_lookup, summarize_q4_2,
)
from microgrid.scenarios import generate_joint_scenarios


ROOT = Path(__file__).parents[1]
OUT = ROOT / "outputs/q4"
OUT.mkdir(parents=True, exist_ok=True)
CONFIG = load_config()
BATTERY, Q4 = CONFIG["battery"], CONFIG["q4"]
ACTUAL = read_processed(ROOT / "data/processed/actual_10min.parquet")
PRICES = price_lookup(ROOT / "data/raw")
OOS, FORECAST_MANIFEST = get_or_build_oos(ROOT, ACTUAL)
WARMUP, WARMUP_MANIFEST = get_or_build_warmup(ROOT, ACTUAL, PRICES, BATTERY)

dependencies = [
    Path(__file__), ROOT / "src/microgrid/q4.py", ROOT / "src/microgrid/execution.py",
    ROOT / "src/microgrid/scenarios.py", ROOT / "src/microgrid/models/deterministic_dispatch.py",
    ROOT / "src/microgrid/models/stochastic_dispatch.py", ROOT / "configs/config.yaml",
    ROOT / "data/raw/附件1.xlsx", ROOT / "data/raw/附件2.xlsx", ROOT / "data/raw/附件4.xlsx",
]
signature = dependency_signature(dependencies, {
    "prediction_signature": FORECAST_MANIFEST["prediction_signature"],
    "warmup_signature": WARMUP_MANIFEST["warmup_signature"],
    "branch": "q4_2",
})
checkpoint = OUT / "cache/q4_2" / signature[:16]
checkpoint.mkdir(parents=True, exist_ok=True)
started = time.time()
socs = {policy: float(WARMUP_MANIFEST["feb1_initial_soc_kwh"]) for policy in ("B1", "B3", "B4")}


def day_actual(date):
    day = ACTUAL[ACTUAL.date == date].sort_values("slot")
    return day.load_kwh.to_numpy(float), day.pv_actual_kwh.to_numpy(float)


def point_for(date):
    day = OOS[OOS.date == date].sort_values("slot").reset_index(drop=True)
    if len(day) != 144:
        raise KeyError(f"missing Q4 point forecast for {date.date()}")
    return day


for day_number, date in enumerate(FORMAL_DATES, start=1):
    stem = date.strftime("%Y-%m-%d")
    state_path = checkpoint / f"{stem}_state.json"
    paths = {name: checkpoint / f"{stem}_{name}.csv" for name in ("execution", "plans", "scenarios", "planning")}
    reusable = state_path.exists() and all(path.exists() for path in paths.values())
    if reusable:
        state = json.loads(state_path.read_text(encoding="utf-8"))
        expected_initial = state.get("initial_socs", {})
        reusable = state.get("signature") == signature and all(
            abs(float(expected_initial.get(policy, np.inf)) - socs[policy]) <= 1e-7 for policy in socs
        )
    if reusable:
        socs = {policy: float(value) for policy, value in state["terminal_socs"].items()}
    else:
        initial_socs = socs.copy()
        point = point_for(date)
        load_actual, pv_actual = day_actual(date)
        price = PRICES[date]
        scenarios = generate_joint_scenarios(
            ACTUAL, OOS, point, date, Q4["scenario_count_q4_2"], CONFIG["random_seed"]
        )
        load_scenarios = scenarios.pivot(index="scenario", columns="slot", values="load_kwh").to_numpy()
        pv_scenarios = scenarios.pivot(index="scenario", columns="slot", values="pv_kwh").to_numpy()
        weights = scenarios.groupby("scenario").weight.first().to_numpy()
        deterministic = solve_deterministic_dispatch(
            point.load_pred_kwh, point.pv_pred_kwh, price, socs["B1"], None, BATTERY
        )
        plans = {"B1": (deterministic.grid_purchase_kwh, np.nan, np.nan, 0.0)}
        for policy, risk_lambda in (("B3", 0.0), ("B4", float(Q4["b4_lambda"]))):
            planned = solve_two_stage_dispatch(
                load_scenarios, pv_scenarios, price, weights, socs[policy], BATTERY,
                Q4["cvar_alpha"], risk_lambda,
            )
            plans[policy] = (
                planned.grid_purchase_kwh, planned.expected_emergency_cost_yuan,
                planned.cvar_yuan, planned.max_equality_residual,
            )
        execution_rows, plan_rows, planning_rows = [], [], []
        for policy, (grid_plan, expected_emergency, scenario_cvar, residual) in plans.items():
            executed = execute_fixed_grid_plan(
                date, grid_plan, load_actual, pv_actual,
                point.load_pred_kwh.to_numpy(), point.pv_pred_kwh.to_numpy(),
                price, socs[policy], BATTERY, policy,
            )
            executed["total_cost_yuan"] = executed.plan_cost_yuan + executed.emergency_cost_yuan
            execution_rows.append(executed)
            plan_rows.append(pd.DataFrame({
                "date": date, "slot": np.arange(1, 145), "policy": policy,
                "grid_plan_kwh": grid_plan,
            }))
            socs[policy] = float(executed.soc_end_kwh.iloc[-1])
            planning_rows.append({
                "date": date, "policy": policy, "initial_soc_kwh": float(executed.soc_start_kwh.iloc[0]),
                "terminal_soc_kwh": socs[policy], "expected_scenario_emergency_cost_yuan": expected_emergency,
                "planning_scenario_emergency_cvar95_yuan": scenario_cvar,
                "max_planning_residual": residual,
            })
        pd.concat(execution_rows, ignore_index=True).to_csv(paths["execution"], index=False)
        pd.concat(plan_rows, ignore_index=True).to_csv(paths["plans"], index=False)
        scenarios[["scenario", "source_date", "weight", "training_cutoff"]].drop_duplicates().assign(
            target_date=date
        ).to_csv(paths["scenarios"], index=False)
        pd.DataFrame(planning_rows).to_csv(paths["planning"], index=False)
        state_path.write_text(json.dumps({
            "signature": signature, "date": stem, "initial_socs": initial_socs,
            "terminal_socs": socs,
        }, indent=2), encoding="utf-8")
    if day_number % 5 == 0 or day_number == len(FORMAL_DATES):
        print(f"q4-2 {day_number}/{len(FORMAL_DATES)} elapsed={time.time()-started:.1f}s", flush=True)

execution = pd.concat([pd.read_csv(checkpoint / f"{d:%Y-%m-%d}_execution.csv", parse_dates=["date"]) for d in FORMAL_DATES], ignore_index=True)
plans = pd.concat([pd.read_csv(checkpoint / f"{d:%Y-%m-%d}_plans.csv", parse_dates=["date"]) for d in FORMAL_DATES], ignore_index=True)
sources = pd.concat([pd.read_csv(checkpoint / f"{d:%Y-%m-%d}_scenarios.csv", parse_dates=["source_date", "training_cutoff", "target_date"]) for d in FORMAL_DATES], ignore_index=True)
planning = pd.concat([pd.read_csv(checkpoint / f"{d:%Y-%m-%d}_planning.csv", parse_dates=["date"]) for d in FORMAL_DATES], ignore_index=True)
execution.to_csv(OUT / "q4_2_execution_detail.csv", index=False)
plans.to_csv(OUT / "q4_2_day_ahead_plans.csv", index=False)
sources.to_csv(OUT / "q4_2_scenario_sources.csv", index=False)
planning.to_csv(OUT / "q4_2_planning_diagnostics.csv", index=False)
daily, comparison = summarize_q4_2(execution)
daily.to_csv(OUT / "q4_2_daily_summary.csv", index=False)
comparison.to_csv(OUT / "q4_2_strategy_comparison.csv", index=False)
export_q4_2(ROOT, execution, plans, Q4["main_policy_q4_2"])
manifest = {
    "signature": signature, "runtime_seconds": time.time() - started,
    "price_source": "attachment4", "price_information_assumption": Q4["price_information_assumption"],
    "prediction_signature": FORECAST_MANIFEST["prediction_signature"],
    "warmup_signature": WARMUP_MANIFEST["warmup_signature"],
    "common_feb1_soc_kwh": WARMUP_MANIFEST["feb1_initial_soc_kwh"],
    "scenario_count": Q4["scenario_count_q4_2"], "b3_lambda": 0.0,
    "b4_lambda": Q4["b4_lambda"], "main_policy": Q4["main_policy_q4_2"],
    "rows": len(execution), "checkpoint_directory": str(checkpoint.relative_to(ROOT)),
}
(OUT / "q4_2_run_manifest.json").write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")
print(comparison.to_string(index=False))
print(json.dumps(manifest, ensure_ascii=False, indent=2))
