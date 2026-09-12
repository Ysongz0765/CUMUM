from hashlib import sha256
from pathlib import Path
import json
import sys
import time

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).parents[1] / "src"))
from microgrid.config import load_config
from microgrid.io import get_q2_daily_price, read_processed, read_pv_forecast
from microgrid.models.stochastic_dispatch import empirical_cvar
from microgrid.q3 import run_q3_day


ROOT = Path(__file__).parents[1]
OUT = ROOT / "outputs/q3"
CONFIG = load_config(); BATTERY = CONFIG["battery"]; Q3 = CONFIG["q3"]
ACTUAL = read_processed(ROOT / "data/processed/actual_10min.parquet")
OOS = pd.read_csv(OUT / "q3_oos_forecasts.csv", parse_dates=["date"])
FORECAST = read_pv_forecast(ROOT / "data/raw/附件3.xlsx")
PRICE = get_q2_daily_price(ROOT / "data/raw").price_yuan_per_kwh.to_numpy(float)
FORMAL_DATES = pd.date_range("2025-02-01", "2025-12-31")
DELTA = float(pd.read_csv(OUT / "q3_delta_selection.csv").query("selected").delta_yuan.iloc[0])
MANIFEST = json.loads((OUT / "run_manifest.json").read_text(encoding="utf-8"))
dependencies = [Path(__file__), ROOT / "src/microgrid/q3.py", ROOT / "src/microgrid/io.py", ROOT / "src/microgrid/execution.py", ROOT / "src/microgrid/models/adjustment_dispatch.py", ROOT / "src/microgrid/models/stochastic_dispatch.py", ROOT / "configs/config.yaml", ROOT / "data/raw/附件1.xlsx", ROOT / "data/raw/附件2.xlsx", ROOT / "data/raw/附件3.xlsx"]
signature = sha256(b"".join(path.read_bytes() for path in dependencies) + json.dumps({"delta": DELTA, "allowed_update_hours": [6, 12], "formal_signature": MANIFEST["signature"]}, sort_keys=True).encode()).hexdigest()
checkpoint = OUT / "cache/q3_18h_ablation" / signature[:16]
checkpoint.mkdir(parents=True, exist_ok=True)
started = time.time(); soc = float(MANIFEST["common_feb1_soc_kwh"])

for number, date in enumerate(FORMAL_DATES, start=1):
    stem = date.strftime("%Y-%m-%d"); state_path = checkpoint / f"{stem}_state.json"
    paths = {name: checkpoint / f"{stem}_{name}.csv" for name in ("execution", "revisions", "snapshots", "sources")}
    reusable = state_path.exists() and all(path.exists() for path in paths.values())
    if reusable:
        state = json.loads(state_path.read_text(encoding="utf-8"))
        reusable = state.get("signature") == signature and abs(float(state.get("initial_soc_kwh", np.inf)) - soc) <= 1e-7
    if reusable:
        soc = float(state["terminal_soc_kwh"])
    else:
        initial_soc = soc
        result = run_q3_day(
            date, "C3", soc, ACTUAL, OOS, FORECAST, PRICE, BATTERY, Q3,
            DELTA, CONFIG["random_seed"], allowed_update_hours=[6, 12],
        )
        soc = float(result.execution.soc_end_kwh.iloc[-1])
        result.execution.to_csv(paths["execution"], index=False)
        result.revisions.to_csv(paths["revisions"], index=False)
        result.snapshots.to_csv(paths["snapshots"], index=False)
        result.scenario_sources.to_csv(paths["sources"], index=False)
        state_path.write_text(json.dumps({"signature": signature, "date": stem, "initial_soc_kwh": initial_soc, "terminal_soc_kwh": soc}, indent=2), encoding="utf-8")
    if number % 10 == 0 or number == len(FORMAL_DATES):
        print(f"q3 18h ablation {number}/{len(FORMAL_DATES)} elapsed={time.time()-started:.1f}s", flush=True)

execution = pd.concat([pd.read_csv(checkpoint / f"{date:%Y-%m-%d}_execution.csv", parse_dates=["date"]) for date in FORMAL_DATES], ignore_index=True)
revisions = pd.concat([pd.read_csv(checkpoint / f"{date:%Y-%m-%d}_revisions.csv", parse_dates=["date", "decision_time", "observation_cutoff"]) for date in FORMAL_DATES], ignore_index=True)
snapshots = pd.concat([pd.read_csv(checkpoint / f"{date:%Y-%m-%d}_snapshots.csv", parse_dates=["date", "decision_time"]) for date in FORMAL_DATES], ignore_index=True)
sources = pd.concat([pd.read_csv(checkpoint / f"{date:%Y-%m-%d}_sources.csv", parse_dates=["source_date", "target_date", "training_cutoff", "decision_time", "source_observation_cutoff", "target_observation_cutoff"]) for date in FORMAL_DATES], ignore_index=True)
execution.to_csv(OUT / "q3_18h_ablation_execution_detail.csv", index=False)
revisions.to_csv(OUT / "q3_18h_ablation_revision_log.csv", index=False)
snapshots.to_csv(OUT / "q3_18h_ablation_plan_snapshots.csv", index=False)
sources.to_csv(OUT / "q3_18h_ablation_scenario_sources.csv", index=False)
daily = execution.groupby("date").agg(
    original_plan_cost_yuan=("original_plan_cost_yuan", "sum"), final_non_emergency_cost_yuan=("final_non_emergency_cost_yuan", "sum"),
    emergency_cost_yuan=("emergency_cost_yuan", "sum"), total_cost_yuan=("total_cost_yuan", "sum"),
    emergency_purchase_kwh=("emergency_purchase_kwh", "sum"), remaining_energy_kwh=("remaining_energy_kwh", "sum"),
    terminal_soc_kwh=("soc_end_kwh", "last"),
).reset_index()
daily.to_csv(OUT / "q3_18h_ablation_daily_summary.csv", index=False)

official = pd.read_csv(OUT / "q3_execution_detail.csv", parse_dates=["date"]).query("policy == 'C3'")
official_daily = official.groupby("date").agg(total_cost_yuan=("total_cost_yuan", "sum"), emergency_cost_yuan=("emergency_cost_yuan", "sum"), emergency_purchase_kwh=("emergency_purchase_kwh", "sum"), remaining_energy_kwh=("remaining_energy_kwh", "sum"), terminal_soc_kwh=("soc_end_kwh", "last")).reset_index()
def summarize(label, frame, revision_count):
    weights = np.ones(len(frame)) / len(frame)
    return {"allowed_updates": label, "total_cost_yuan": frame.total_cost_yuan.sum(), "emergency_cost_yuan": frame.emergency_cost_yuan.sum(), "emergency_purchase_kwh": frame.emergency_purchase_kwh.sum(), "daily_emergency_cvar95_yuan": empirical_cvar(frame.emergency_cost_yuan, weights, .95), "daily_total_cvar95_yuan": empirical_cvar(frame.total_cost_yuan, weights, .95), "remaining_energy_kwh": frame.remaining_energy_kwh.sum(), "revision_count": revision_count, "year_end_soc_kwh": frame.terminal_soc_kwh.iloc[-1]}
official_revisions = pd.read_csv(OUT / "q3_revision_log.csv").query("policy == 'C3'").triggered.sum()
comparison = pd.DataFrame([summarize("06/12/18", official_daily, int(official_revisions)), summarize("06/12", daily, int(revisions.triggered.sum()))])
comparison.to_csv(OUT / "q3_18h_ablation_comparison.csv", index=False)
(OUT / "q3_18h_ablation_manifest.json").write_text(json.dumps({"signature": signature, "formal_q3_signature": MANIFEST["signature"], "selected_delta_yuan": DELTA, "allowed_update_hours": [6, 12], "common_feb1_soc_kwh": MANIFEST["common_feb1_soc_kwh"], "rows": len(execution), "runtime_seconds": time.time()-started, "checkpoint_directory": str(checkpoint.relative_to(ROOT))}, ensure_ascii=False, indent=2), encoding="utf-8")
print(comparison.to_string(index=False))
