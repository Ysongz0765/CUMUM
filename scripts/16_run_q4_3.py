from pathlib import Path
import json
import sys
import time

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).parents[1] / "src"))
from microgrid.config import load_config
from microgrid.io import read_processed, read_pv_forecast
from microgrid.models.stochastic_dispatch import empirical_cvar
from microgrid.q3 import run_q3_day
from microgrid.q4 import (
    FORMAL_DATES, dependency_signature, export_q4_3, get_or_build_oos,
    get_or_build_warmup, price_lookup, summarize_q4_3,
)


ROOT = Path(__file__).parents[1]
OUT = ROOT / "outputs/q4"
OUT.mkdir(parents=True, exist_ok=True)
CONFIG = load_config()
BATTERY, Q4 = CONFIG["battery"], CONFIG["q4"]
ACTUAL = read_processed(ROOT / "data/processed/actual_10min.parquet")
FORECAST_LONG = read_pv_forecast(ROOT / "data/raw/附件3.xlsx")
PRICES = price_lookup(ROOT / "data/raw")
OOS, FORECAST_MANIFEST = get_or_build_oos(ROOT, ACTUAL)
WARMUP, WARMUP_MANIFEST = get_or_build_warmup(ROOT, ACTUAL, PRICES, BATTERY)
Q3 = dict(CONFIG["q3"])
Q3.update({
    "scenario_count": Q4["scenario_count_q4_3"], "cvar_alpha": Q4["cvar_alpha"],
    "cvar_lambda": Q4["b4_lambda"], "delta_candidates_yuan": Q4["delta_candidates_yuan"],
    "calibration_start": Q4["calibration_start"], "calibration_end": Q4["calibration_end"],
})
dependencies = [
    Path(__file__), ROOT / "src/microgrid/q3.py", ROOT / "src/microgrid/q4.py",
    ROOT / "src/microgrid/execution.py", ROOT / "src/microgrid/models/adjustment_dispatch.py",
    ROOT / "src/microgrid/models/stochastic_dispatch.py", ROOT / "configs/config.yaml",
    ROOT / "data/raw/附件2.xlsx", ROOT / "data/raw/附件3.xlsx", ROOT / "data/raw/附件4.xlsx",
]
signature = dependency_signature(dependencies, {
    "prediction_signature": FORECAST_MANIFEST["prediction_signature"],
    "warmup_signature": WARMUP_MANIFEST["warmup_signature"], "branch": "q4_3",
})
started = time.time()

# Freeze delta using only January 22-31 and the Q4-price warm-up state at Jan 21.
jan21_soc = float(WARMUP[WARMUP.date == pd.Timestamp("2025-01-21")].soc_end_kwh.iloc[-1])
calibration_rows = []
for delta in Q3["delta_candidates_yuan"]:
    soc = jan21_soc
    daily_costs, daily_emergency, revisions = [], [], 0
    for date in pd.date_range(Q3["calibration_start"], Q3["calibration_end"]):
        result = run_q3_day(
            date, "C3", soc, ACTUAL, OOS, FORECAST_LONG, PRICES[date], BATTERY,
            Q3, float(delta), CONFIG["random_seed"],
        )
        soc = float(result.execution.soc_end_kwh.iloc[-1])
        daily_costs.append(float(result.execution.total_cost_yuan.sum()))
        daily_emergency.append(float(result.execution.emergency_cost_yuan.sum()))
        revisions += int(result.revisions.triggered.sum())
    weights = np.ones(len(daily_costs)) / len(daily_costs)
    calibration_rows.append({
        "delta_yuan": delta, "january_total_cost_yuan": sum(daily_costs),
        "january_daily_total_cvar95_yuan": empirical_cvar(daily_costs, weights, .95),
        "january_daily_emergency_cvar95_yuan": empirical_cvar(daily_emergency, weights, .95),
        "revision_count": revisions, "terminal_soc_kwh": soc,
    })
calibration = pd.DataFrame(calibration_rows)
best = calibration.sort_values(["january_total_cost_yuan", "january_daily_emergency_cvar95_yuan", "revision_count"]).iloc[0]
selected_delta = float(best.delta_yuan)
calibration["selected"] = calibration.delta_yuan.eq(selected_delta)
calibration.to_csv(OUT / "q4_delta_selection.csv", index=False)

checkpoint = OUT / "cache/q4_3" / signature[:16]
checkpoint.mkdir(parents=True, exist_ok=True)
socs = {policy: float(WARMUP_MANIFEST["feb1_initial_soc_kwh"]) for policy in ("C0", "C1", "C2", "C3")}
for day_number, date in enumerate(FORMAL_DATES, start=1):
    stem = date.strftime("%Y-%m-%d")
    state_path = checkpoint / f"{stem}_state.json"
    names = ("execution", "revisions", "snapshots", "sources")
    paths = {name: checkpoint / f"{stem}_{name}.csv" for name in names}
    reusable = state_path.exists() and all(path.exists() for path in paths.values())
    if reusable:
        state = json.loads(state_path.read_text(encoding="utf-8"))
        reusable = state.get("signature") == signature and state.get("selected_delta") == selected_delta and all(
            abs(float(state.get("initial_socs", {}).get(policy, np.inf)) - socs[policy]) <= 1e-7 for policy in socs
        )
    if reusable:
        socs = {policy: float(value) for policy, value in state["terminal_socs"].items()}
    else:
        initial_socs = socs.copy()
        results = {}
        for policy in ("C0", "C1", "C2"):
            result = run_q3_day(
                date, policy, socs[policy], ACTUAL, OOS, FORECAST_LONG, PRICES[date],
                BATTERY, Q3, selected_delta, CONFIG["random_seed"],
            )
            results[policy] = result
            socs[policy] = float(result.execution.soc_end_kwh.iloc[-1])
        if selected_delta == 0:
            base = results["C2"]
            execution = base.execution.copy(); execution["policy"] = "C3"
            revisions = base.revisions.copy(); revisions["policy"] = "C3"
            snapshots = base.snapshots.copy(); snapshots["policy"] = "C3"
            sources = base.scenario_sources.copy(); sources["policy"] = "C3"
            result = type(base)(execution, revisions, snapshots, sources)
        else:
            result = run_q3_day(
                date, "C3", socs["C3"], ACTUAL, OOS, FORECAST_LONG, PRICES[date],
                BATTERY, Q3, selected_delta, CONFIG["random_seed"],
            )
        results["C3"] = result
        socs["C3"] = float(result.execution.soc_end_kwh.iloc[-1])
        pd.concat([r.execution for r in results.values()], ignore_index=True).to_csv(paths["execution"], index=False)
        pd.concat([r.revisions for r in results.values()], ignore_index=True).to_csv(paths["revisions"], index=False)
        pd.concat([r.snapshots for r in results.values()], ignore_index=True).to_csv(paths["snapshots"], index=False)
        pd.concat([r.scenario_sources for r in results.values()], ignore_index=True).to_csv(paths["sources"], index=False)
        state_path.write_text(json.dumps({
            "signature": signature, "selected_delta": selected_delta, "date": stem,
            "initial_socs": initial_socs, "terminal_socs": socs,
        }, indent=2), encoding="utf-8")
    if day_number % 5 == 0 or day_number == len(FORMAL_DATES):
        print(f"q4-3 {day_number}/{len(FORMAL_DATES)} elapsed={time.time()-started:.1f}s", flush=True)

execution = pd.concat([pd.read_csv(checkpoint / f"{d:%Y-%m-%d}_execution.csv", parse_dates=["date"]) for d in FORMAL_DATES], ignore_index=True)
revisions = pd.concat([pd.read_csv(checkpoint / f"{d:%Y-%m-%d}_revisions.csv", parse_dates=["date", "decision_time"]) for d in FORMAL_DATES], ignore_index=True)
snapshots = pd.concat([pd.read_csv(checkpoint / f"{d:%Y-%m-%d}_snapshots.csv", parse_dates=["date", "decision_time"]) for d in FORMAL_DATES], ignore_index=True)
sources = pd.concat([pd.read_csv(checkpoint / f"{d:%Y-%m-%d}_sources.csv", parse_dates=["source_date", "target_date", "training_cutoff", "decision_time"]) for d in FORMAL_DATES], ignore_index=True)
execution.to_csv(OUT / "q4_3_execution_detail.csv", index=False)
revisions.to_csv(OUT / "q4_3_revision_log.csv", index=False)
snapshots.to_csv(OUT / "q4_3_plan_snapshots.csv", index=False)
sources.to_csv(OUT / "q4_3_scenario_sources.csv", index=False)
daily, comparison = summarize_q4_3(execution, revisions)
daily.to_csv(OUT / "q4_3_daily_summary.csv", index=False)
comparison.to_csv(OUT / "q4_3_strategy_comparison.csv", index=False)
export_q4_3(ROOT, execution, Q4["main_policy_q4_3"])
manifest = {
    "signature": signature, "runtime_seconds": time.time() - started,
    "price_source": "attachment4", "price_information_assumption": Q4["price_information_assumption"],
    "prediction_signature": FORECAST_MANIFEST["prediction_signature"],
    "warmup_signature": WARMUP_MANIFEST["warmup_signature"],
    "common_feb1_soc_kwh": WARMUP_MANIFEST["feb1_initial_soc_kwh"],
    "scenario_count": Q4["scenario_count_q4_3"], "cvar_alpha": Q4["cvar_alpha"],
    "cvar_lambda": Q4["b4_lambda"], "selected_delta_yuan": selected_delta,
    "main_policy": Q4["main_policy_q4_3"], "rows": len(execution),
    "checkpoint_directory": str(checkpoint.relative_to(ROOT)),
}
(OUT / "q4_3_run_manifest.json").write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")
print(comparison.to_string(index=False))
print(json.dumps(manifest, ensure_ascii=False, indent=2))
