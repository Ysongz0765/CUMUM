from pathlib import Path
import sys

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).parents[1] / "src"))
from microgrid.io import read_processed, read_pv_forecast
from microgrid.q3 import issue_pv_day


ROOT = Path(__file__).parents[1]
OUT = ROOT / "outputs/diagnostics"
OUT.mkdir(parents=True, exist_ok=True)
ACTUAL = read_processed(ROOT / "data/processed/actual_10min.parquet")
FORECAST = read_pv_forecast(ROOT / "data/raw/附件3.xlsx")
PERIODS = {
    "january_calibration_2025-01-22_2025-01-31": pd.date_range("2025-01-22", "2025-01-31"),
    "formal_2025-02-01_2025-12-31": pd.date_range("2025-02-01", "2025-12-31"),
}


records = []
for period, dates in PERIODS.items():
    for date in dates:
        truth = ACTUAL[ACTUAL.date == date].sort_values("slot").pv_actual_kw.to_numpy(float)
        for issue_hour in (0, 6, 12, 18):
            start = issue_hour * 6
            for method, label in (("legacy_bfill", "legacy_10min_bfill"), ("observed_anchor", "observed_anchor_10min")):
                trajectory, metadata = issue_pv_day(
                    FORECAST, date, issue_hour, ACTUAL,
                    boundary_method=method, return_metadata=True,
                )
                for index in range(start, 144):
                    offset = index - start
                    records.append({
                        "period": period, "date": date, "issue_hour": issue_hour,
                        "forecast_type": label, "slot": index + 1,
                        "region": "first_50_minutes" if offset < 5 else "after_first_50_minutes",
                        "forecast_kw": trajectory[index] * 6,
                        "actual_kw": truth[index],
                        "anchor_kw": metadata["anchor_kw"],
                        "anchor_source": metadata["anchor_source"],
                        "observation_cutoff": metadata["observation_cutoff"],
                    })
            raw = FORECAST[(FORECAST.date == date) & (FORECAST.issue_hour == issue_hour)].copy()
            raw = raw[(raw.target_datetime > date) & (raw.target_datetime <= date + pd.Timedelta(days=1))]
            for row in raw.itertuples():
                slot = int((row.target_datetime - date).total_seconds() // 600)
                records.append({
                    "period": period, "date": date, "issue_hour": issue_hour,
                    "forecast_type": "supplier_raw_hourly", "slot": slot,
                    "region": "original_hourly_targets", "forecast_kw": row.pv_forecast_kw,
                    "actual_kw": truth[slot - 1], "anchor_kw": np.nan,
                    "anchor_source": "not_applicable", "observation_cutoff": pd.NaT,
                })

detail = pd.DataFrame(records)
detail["error_kw"] = detail.forecast_kw - detail.actual_kw
detail["absolute_error_kw"] = detail.error_kw.abs()
detail["squared_error_kw2"] = detail.error_kw ** 2
detail.to_csv(OUT / "forecast_boundary_accuracy.csv", index=False)

summary = detail.groupby(["period", "issue_hour", "forecast_type", "region"], dropna=False).agg(
    observations=("error_kw", "size"),
    mae_kw=("absolute_error_kw", "mean"),
    mse_kw2=("squared_error_kw2", "mean"),
).reset_index()
summary["rmse_kw"] = np.sqrt(summary.pop("mse_kw2"))
all_regions = detail.groupby(["period", "issue_hour", "forecast_type"], dropna=False).agg(
    observations=("error_kw", "size"), mae_kw=("absolute_error_kw", "mean"),
    mse_kw2=("squared_error_kw2", "mean"),
).reset_index().assign(region="all_available_targets")
all_regions["rmse_kw"] = np.sqrt(all_regions.pop("mse_kw2"))
summary = pd.concat([summary, all_regions], ignore_index=True).sort_values(
    ["period", "issue_hour", "forecast_type", "region"]
)
summary.to_csv(OUT / "forecast_boundary_accuracy_summary.csv", index=False)
print(summary.to_string(index=False))
