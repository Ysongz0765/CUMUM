from pathlib import Path
import json
import sys

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).parents[1] / "src"))
from microgrid.config import load_config
from microgrid.io import get_q2_daily_price, read_actual, read_attachment4_prices, read_pv_forecast
from microgrid.prediction import ForecastChoice, build_oos_forecasts
from microgrid.q3 import run_q3_day


ROOT = Path(__file__).parents[1]
DATE = pd.Timestamp("2025-02-01")
TOL = 1e-6
config = load_config(); battery = config["battery"]

# Rebuild the required history, day-ahead forecasts, issue trajectories, and
# scenarios directly from raw attachments.  No dispatch checkpoint is read.
actual = read_actual(ROOT / "data/raw")
actual["load_kwh"] = actual.load_kw / 6
actual["pv_actual_kwh"] = actual.pv_actual_kw / 6
oos = build_oos_forecasts(actual, pd.date_range("2025-01-08", DATE), ForecastChoice("ridge", "ridge"))
forecast = read_pv_forecast(ROOT / "data/raw/附件3.xlsx")
checks = {}
columns = ["original_grid_plan_kwh", "final_grid_plan_kwh", "emergency_purchase_kwh", "charge_kwh", "discharge_kwh", "remaining_energy_kwh", "soc_start_kwh", "soc_end_kwh", "total_cost_yuan"]

q3_formal = pd.read_csv(ROOT / "outputs/q3/q3_execution_detail.csv", parse_dates=["date"])
q3_expected = q3_formal[(q3_formal.date == DATE) & (q3_formal.policy == "C3")].sort_values("slot")
q3_delta = float(pd.read_csv(ROOT / "outputs/q3/q3_delta_selection.csv").query("selected").delta_yuan.iloc[0])
q3_result = run_q3_day(DATE, "C3", float(q3_expected.soc_start_kwh.iloc[0]), actual, oos, forecast, get_q2_daily_price(ROOT / "data/raw").price_yuan_per_kwh.to_numpy(float), battery, config["q3"], q3_delta, config["random_seed"])
checks["q3_max_execution_difference"] = float(np.max(np.abs(q3_result.execution[columns].to_numpy()-q3_expected[columns].to_numpy())))
checks["q3_revision_rows_match"] = len(q3_result.revisions) == len(pd.read_csv(ROOT / "outputs/q3/q3_revision_log.csv").query("date == '2025-02-01' and policy == 'C3'"))

q4_formal = pd.read_csv(ROOT / "outputs/q4/q4_3_execution_detail.csv", parse_dates=["date"])
q4_expected = q4_formal[(q4_formal.date == DATE) & (q4_formal.policy == "C3")].sort_values("slot")
q4_delta = float(pd.read_csv(ROOT / "outputs/q4/q4_delta_selection.csv").query("selected").delta_yuan.iloc[0])
q4_settings = dict(config["q3"])
q4_settings.update({"scenario_count":config["q4"]["scenario_count_q4_3"],"cvar_alpha":config["q4"]["cvar_alpha"],"cvar_lambda":config["q4"]["b4_lambda"]})
q4_price = read_attachment4_prices(ROOT / "data/raw").query("date == @DATE").sort_values("slot").price_yuan_per_kwh.to_numpy(float)
q4_result = run_q3_day(DATE, "C3", float(q4_expected.soc_start_kwh.iloc[0]), actual, oos, forecast, q4_price, battery, q4_settings, q4_delta, config["random_seed"])
checks["q4_3_max_execution_difference"] = float(np.max(np.abs(q4_result.execution[columns].to_numpy()-q4_expected[columns].to_numpy())))
checks["q4_3_revision_rows_match"] = len(q4_result.revisions) == len(pd.read_csv(ROOT / "outputs/q4/q4_3_revision_log.csv").query("date == '2025-02-01' and policy == 'C3'"))
checks["date"] = str(DATE.date())
checks["inputs_rebuilt_from_raw_attachments"] = True
checks["dispatch_cache_used"] = False
checks["validated_initial_soc_reused"] = True
checks["passed"] = checks["q3_max_execution_difference"] <= TOL and checks["q4_3_max_execution_difference"] <= TOL and checks["q3_revision_rows_match"] and checks["q4_3_revision_rows_match"]
path = ROOT / "reports/q3_q4_3_repro_evidence.json"
path.write_text(json.dumps(checks, ensure_ascii=False, indent=2), encoding="utf-8")
print(json.dumps(checks, ensure_ascii=False, indent=2))
raise SystemExit(0 if checks["passed"] else 1)
