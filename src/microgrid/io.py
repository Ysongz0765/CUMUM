from pathlib import Path
import pandas as pd
import numpy as np
from .time_utils import parse_excel_time
import re

def resolve_raw_file(raw_dir: Path, key: str) -> Path:
    mapping={'attachment1':'附件1.xlsx','attachment2':'附件2.xlsx','attachment3':'附件3.xlsx','attachment4':'附件4.xlsx'}
    expected=mapping[key]; exact=raw_dir/expected
    if exact.exists(): return exact
    candidates=[]
    for p in raw_dir.glob('*.xlsx'):
        xls=pd.ExcelFile(p); shapes=[pd.read_excel(p,sheet_name=s,nrows=2).shape for s in xls.sheet_names]
        if key=='attachment1' and any(s[1]==4 for s in shapes): candidates.append(p)
        elif key in {'attachment2','attachment4'} and any(s[1]==145 for s in shapes): candidates.append(p)
        elif key=='attachment3' and any(s[1]==26 for s in shapes): candidates.append(p)
    if len(candidates)!=1: raise FileNotFoundError(f'{key}: expected one identifiable workbook, got {candidates}')
    return candidates[0]

def read_q1(path: Path) -> pd.DataFrame:
    df = pd.read_excel(path); df.columns = ["time","price_yuan_per_kwh","load_kw","pv_forecast_kw"]
    parsed = [parse_excel_time(x) for x in df.time]
    df["slot"] = range(1, len(df)+1); df["load_kwh"] = df.load_kw/6; df["pv_forecast_kwh"] = df.pv_forecast_kw/6
    anchor = pd.Timestamp("2025-01-01")
    ends = [anchor + pd.Timedelta(days=plus, hours=h, minutes=m) for h,m,plus in parsed]
    starts = [end - pd.Timedelta(minutes=10) for end in ends]
    df["source_row"] = range(2, len(df)+2)
    df["source_time_label"] = ["0:00+1" if plus else f"{h}:{m:02d}" for h,m,plus in parsed]
    df["interval_start"] = starts; df["interval_end"] = ends
    return df[["slot","source_row","source_time_label","interval_start","interval_end","price_yuan_per_kwh","load_kw","load_kwh","pv_forecast_kw","pv_forecast_kwh"]]

def read_wide(path: Path, value_name: str) -> pd.DataFrame:
    raw = pd.read_excel(path); raw = raw.rename(columns={raw.columns[0]:"date"})
    out = raw.melt(id_vars="date", var_name="time", value_name=value_name)
    out["date"] = pd.to_datetime(out.date, errors="raise").dt.normalize()
    out["slot"] = out.groupby("date", sort=False).cumcount()+1
    return out[["date","slot",value_name]]

def read_actual(raw_dir: Path) -> pd.DataFrame:
    load = read_wide(raw_dir/"附件2.xlsx", "load_kw")
    # second sheet is PV
    raw = pd.read_excel(raw_dir/"附件2.xlsx", sheet_name="光伏发电实际功率")
    pv = raw.rename(columns={raw.columns[0]:"date"}).melt(id_vars="date",var_name="time",value_name="pv_actual_kw")
    pv.date = pd.to_datetime(pv.date, errors="raise").dt.normalize(); pv["slot"] = pv.groupby("date",sort=False).cumcount()+1
    return load.merge(pv[["date","slot","pv_actual_kw"]],on=["date","slot"],validate="one_to_one")

def read_price(path: Path) -> pd.DataFrame: return read_wide(path,"price_yuan_per_kwh")

def read_attachment4_prices(raw_dir: Path) -> pd.DataFrame:
    """Read and validate Attachment 4's date-specific 10-minute prices."""
    path = resolve_raw_file(Path(raw_dir), "attachment4")
    prices = read_price(path).sort_values(["date", "slot"]).reset_index(drop=True)
    expected_dates = pd.date_range("2025-01-01", "2025-12-31")
    if len(prices) != 365 * 144:
        raise ValueError(f"Attachment 4 must contain 52560 prices, got {len(prices)}")
    if prices.duplicated(["date", "slot"]).any():
        raise ValueError("Attachment 4 contains duplicate (date, slot) keys")
    dates = pd.DatetimeIndex(prices["date"].drop_duplicates())
    if not dates.equals(expected_dates):
        raise ValueError("Attachment 4 dates are incomplete or out of order")
    complete = prices.groupby("date")["slot"].apply(
        lambda values: np.array_equal(values.to_numpy(), np.arange(1, 145))
    )
    if not complete.all():
        raise ValueError("Attachment 4 contains an incomplete 144-slot day")
    values = pd.to_numeric(prices["price_yuan_per_kwh"], errors="raise").to_numpy(float)
    if not np.isfinite(values).all() or np.any(values <= 0):
        raise ValueError("Attachment 4 prices must be finite and strictly positive")
    prices["price_yuan_per_kwh"] = values
    return prices

def get_daily_price(raw_dir: Path, date=None, source: str = "attachment1") -> pd.DataFrame:
    """Return an explicit tariff, preventing accidental Q2/Q3/Q4 source mixing."""
    if source == "attachment1":
        if date is not None:
            pd.Timestamp(date)  # validate date-like input while retaining the repeated tariff
        return get_q2_daily_price(raw_dir)
    if source == "attachment4":
        if date is None:
            raise ValueError("date is required for Attachment 4 prices")
        target = pd.Timestamp(date).normalize()
        day = read_attachment4_prices(raw_dir)
        day = day[day["date"] == target][["date", "slot", "price_yuan_per_kwh"]]
        if len(day) != 144:
            raise KeyError(f"Attachment 4 has no complete tariff for {target.date()}")
        return day.reset_index(drop=True)
    raise ValueError(f"unsupported price source: {source}")

def read_pv_forecast(path: Path) -> pd.DataFrame:
    raw = pd.read_excel(path); raw.columns = [str(c) for c in raw.columns]
    date_col, issue_col = raw.columns[:2]; current = None; rows=[]
    for _, r in raw.iterrows():
        v = r[date_col]
        if pd.notna(v) and str(v).strip() not in {"", "28"}:
            parsed = pd.to_datetime(v, errors="coerce")
            if pd.notna(parsed): current = pd.Timestamp(parsed).normalize()
        if current is None: raise ValueError("附件3首个日期无效")
        issue = str(r[issue_col]).strip(); h,m,_ = parse_excel_time(issue)
        issue_dt = current + pd.Timedelta(hours=h, minutes=m)
        for horizon in range(1,25):
            col = raw.columns[horizon+1]
            rows.append((current, h, f'{h:02d}:00', issue_dt, horizon, issue_dt+pd.Timedelta(hours=horizon), r[col]))
    out=pd.DataFrame(rows,columns=["date","issue_hour","issue_time","issue_datetime","horizon_hour","target_datetime","pv_forecast_kw"])
    out['pv_forecast_kw']=pd.to_numeric(out.pv_forecast_kw,errors='raise')
    if not np.isfinite(out.pv_forecast_kw).all(): raise ValueError('附件3包含非有限预测值')
    if not (out.groupby(['date','issue_hour']).size()==24).all(): raise ValueError('附件3每次发布必须有24个小时预测')
    return out

def build_10min_pv_forecast(
    forecast_long: pd.DataFrame,
    date,
    issue_time: str,
    *,
    left_anchor_kw=None,
    anchor_source=None,
    boundary_method: str = "observed_anchor",
) -> pd.DataFrame:
    """Build a causal 10-minute trajectory while preserving supplied hourly points.

    ``observed_anchor`` linearly joins an explicitly supplied, issue-time left
    endpoint to the first hourly forecast.  If no earlier observation exists,
    the deterministic fallback uses the first hourly forecast itself.  The old
    ``legacy_bfill`` behavior remains available for diagnostics only.
    """
    issue_hour = int(str(issue_time).split(":")[0])
    day = pd.Timestamp(date).normalize()
    x = forecast_long[
        (forecast_long.date == day) & (forecast_long.issue_hour == issue_hour)
    ].sort_values("target_datetime")
    if x.empty:
        raise KeyError((date, issue_time))
    if boundary_method not in {"observed_anchor", "legacy_bfill"}:
        raise ValueError(f"unsupported forecast boundary method: {boundary_method}")

    issue_datetime = pd.Timestamp(x.issue_datetime.iloc[0])
    times = pd.date_range(
        issue_datetime + pd.Timedelta(minutes=10),
        x.target_datetime.max(),
        freq="10min",
    )
    hourly = pd.Series(
        x.pv_forecast_kw.to_numpy(float),
        index=pd.DatetimeIndex(x.target_datetime),
    )
    if boundary_method == "legacy_bfill":
        values = hourly.reindex(times).interpolate(method="time").bfill().ffill()
        used_anchor = np.nan
        used_source = "legacy_next_hour_bfill"
        observation_cutoff = pd.NaT
    else:
        if left_anchor_kw is None:
            used_anchor = float(hourly.iloc[0])
            used_source = anchor_source or "first_hour_forecast_fallback:no_prior_observation"
            observation_cutoff = pd.NaT
        else:
            used_anchor = float(left_anchor_kw)
            if not np.isfinite(used_anchor) or used_anchor < 0:
                raise ValueError("left_anchor_kw must be finite and nonnegative")
            used_source = anchor_source or "observed_completed_interval"
            observation_cutoff = issue_datetime
        anchors = pd.concat([pd.Series([used_anchor], index=[issue_datetime]), hourly])
        if anchors.index.duplicated().any():
            raise ValueError("forecast anchors contain duplicate target datetimes")
        values = anchors.reindex(pd.DatetimeIndex([issue_datetime]).append(times)).interpolate(
            method="time"
        ).ffill().iloc[1:]

    result = pd.DataFrame({
        "issue_datetime": issue_datetime,
        "target_datetime": times,
        "pv_forecast_kw": values.to_numpy(float),
        "observation_cutoff": observation_cutoff,
        "anchor_kw": used_anchor,
        "anchor_source": used_source,
        "boundary_method": boundary_method,
        "interpolation_method": "linear_time",
    })
    # Supplied hourly values are immutable inputs, not interpolation targets.
    at_hourly = result.set_index("target_datetime").loc[hourly.index, "pv_forecast_kw"].to_numpy()
    if not np.allclose(at_hourly, hourly.to_numpy(), atol=1e-12, rtol=0):
        raise AssertionError("hourly Attachment 3 forecast values changed during interpolation")
    return result

def get_day_actual(processed_path: Path, date) -> dict:
    df = pd.read_parquet(processed_path) if str(processed_path).lower().endswith('.parquet') and Path(processed_path).exists() else pd.read_csv(processed_path, parse_dates=['date']); x = df[df.date == pd.Timestamp(date).normalize()].sort_values("slot")
    if len(x) != 144: raise KeyError(date)
    return {"load_kwh": x.load_kwh.to_numpy(), "pv_kwh": x.pv_actual_kwh.to_numpy(), "price": x.price_yuan_per_kwh.to_numpy()}

def get_history_before(processed_path: Path, date) -> pd.DataFrame:
    df = pd.read_parquet(processed_path) if str(processed_path).lower().endswith('.parquet') and Path(processed_path).exists() else pd.read_csv(processed_path, parse_dates=['date']); return df[df.date < pd.Timestamp(date).normalize()].sort_values(["date", "slot"])

def get_q2_daily_price(raw_dir: Path) -> pd.DataFrame:
    """Return Attachment 1's fixed 144-slot tariff for Questions 2 and 3."""
    q1 = read_q1(resolve_raw_file(raw_dir, "attachment1"))
    return q1[["slot", "price_yuan_per_kwh"]].sort_values("slot").reset_index(drop=True)

def read_processed(path: Path) -> pd.DataFrame:
    """Read CSV or Parquet explicitly and enforce chronological 144-slot days."""
    path = Path(path)
    if not path.exists():
        alternate = path.with_suffix(".csv" if path.suffix == ".parquet" else ".parquet")
        if not alternate.exists(): raise FileNotFoundError(path)
        path = alternate
    df = pd.read_parquet(path) if path.suffix == ".parquet" else pd.read_csv(path, parse_dates=["date"])
    df["date"] = pd.to_datetime(df["date"]).dt.normalize()
    df = df.sort_values(["date", "slot"]).reset_index(drop=True)
    counts = df.groupby("date")["slot"].apply(lambda x: np.array_equal(x.to_numpy(), np.arange(1,145)))
    if not counts.all(): raise ValueError(f"non-canonical day(s): {counts[~counts].index.tolist()[:5]}")
    return df
