from pathlib import Path
import sys, pandas as pd
sys.path.insert(0, str(Path(__file__).parents[1] / "src"))
from microgrid.io import read_q1, read_actual, read_price, read_pv_forecast
from microgrid.validation import validate_actual, validate_forecast
from microgrid.features import add_calendar_features
ROOT = Path(__file__).parents[1]; raw = ROOT / "data/raw"; out = ROOT / "data/processed"; out.mkdir(exist_ok=True)
def save(df, name):
    try: df.to_parquet(out / name, index=False)
    except Exception: df.to_csv(out / name.replace('.parquet', '.csv'), index=False)
q1 = read_q1(raw / '附件1.xlsx'); save(q1, 'q1_day.parquet')
actual = read_actual(raw); price = read_price(raw / '附件4.xlsx'); actual = actual.merge(price, on=['date','slot'], validate='one_to_one'); actual = add_calendar_features(actual)
actual['time_label'] = actual.slot.map(lambda s: f"{(s-1)//6}:{((s-1)%6)*10:02d}"); actual['interval_start'] = actual.date + pd.to_timedelta((actual.slot-1)*10, unit='min'); actual['interval_end'] = actual.interval_start + pd.Timedelta(minutes=10); actual['timestamp_end'] = actual.interval_end; actual['load_kwh'] = actual.load_kw/6; actual['pv_actual_kwh'] = actual.pv_actual_kw/6
actual['pv_positive'] = actual.pv_actual_kw > 0; actual['is_daylight'] = actual.pv_positive
daylight = actual[actual.pv_positive].groupby(actual.date.dt.month).agg(first_slot=('slot','min'), last_slot=('slot','max'), positive_intervals=('slot','count'), daily_energy_kwh=('pv_actual_kwh','sum')).reset_index().rename(columns={'date':'month'}); daylight.to_csv(ROOT/'reports/daylight_summary.csv', index=False)
validate_actual(actual); save(actual, 'actual_10min.parquet')
fc = read_pv_forecast(raw / '附件3.xlsx'); validate_forecast(fc); save(fc, 'pv_forecast_hourly.parquet')
warm = actual[actual.date.dt.month == 1]; main = actual[actual.date >= pd.Timestamp('2025-02-01')]; save(warm, 'warmup_january.parquet'); save(main, 'main_2025_02_12.parquet')
preview = out / 'preview'; preview.mkdir(exist_ok=True); actual.head(20).to_csv(preview/'actual_10min.csv', index=False); fc.head(50).to_csv(preview/'pv_forecast_hourly.csv', index=False)
(ROOT/'reports/preprocessing_summary.md').write_text(f"# 预处理摘要\n\n- q1_day: {len(q1)}\n- actual_10min: {len(actual)}\n- pv_forecast_hourly: {len(fc)}\n- warmup_january: {len(warm)}\n- main_2025_02_12: {len(main)}\n", encoding='utf-8')
print('processed', len(q1), len(actual), len(fc), len(warm), len(main))
