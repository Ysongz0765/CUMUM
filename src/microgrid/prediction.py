"""Strictly causal day-ahead load and PV prediction."""
from dataclasses import dataclass
import numpy as np
import pandas as pd
from sklearn.linear_model import Ridge

@dataclass(frozen=True)
class ForecastChoice:
    load_method: str
    pv_method: str

def _pivots(actual: pd.DataFrame) -> tuple[pd.DataFrame, pd.DataFrame]:
    load = actual.pivot(index="date", columns="slot", values="load_kw").sort_index()
    pv = actual.pivot(index="date", columns="slot", values="pv_actual_kw").sort_index()
    return load, pv

def _simple_forecast(pivot: pd.DataFrame, target_date: pd.Timestamp, method: str) -> np.ndarray:
    history = pivot.loc[pivot.index < target_date]
    if history.empty: raise ValueError(f"no history before {target_date.date()}")
    if method == "d1": return history.iloc[-1].to_numpy(float)
    if method == "mean7": return history.tail(7).mean().to_numpy(float)
    raise ValueError(method)

def _day_features(pivot: pd.DataFrame, target_date: pd.Timestamp) -> np.ndarray:
    hist = pivot.loc[pivot.index < target_date]
    if hist.empty: raise ValueError("no historical observations")
    d1 = hist.iloc[-1].to_numpy(float)
    d2 = hist.iloc[-2].to_numpy(float) if len(hist) >= 2 else d1
    d7 = hist.iloc[-7].to_numpy(float) if len(hist) >= 7 else d1
    mean7 = hist.tail(7).mean().to_numpy(float)
    slots = np.arange(144)
    dow = target_date.dayofweek
    return np.column_stack([d1,d2,d7,mean7,np.sin(2*np.pi*slots/144),np.cos(2*np.pi*slots/144),np.full(144,np.sin(2*np.pi*dow/7)),np.full(144,np.cos(2*np.pi*dow/7))])

def _ridge_forecast(pivot: pd.DataFrame, target_date: pd.Timestamp) -> np.ndarray:
    training_dates = pivot.index[(pivot.index < target_date)][7:][-60:]
    if len(training_dates) < 7: return _simple_forecast(pivot,target_date,"mean7")
    xs=[]; ys=[]
    for d in training_dates:
        xs.append(_day_features(pivot,d)); ys.append(pivot.loc[d].to_numpy(float))
    model=Ridge(alpha=10.0).fit(np.vstack(xs),np.concatenate(ys))
    return model.predict(_day_features(pivot,target_date))

def forecast_day(actual: pd.DataFrame, target_date, load_method: str, pv_method: str) -> pd.DataFrame:
    """Predict all 144 slots using only rows with date strictly before target_date."""
    target=pd.Timestamp(target_date).normalize(); history=actual[actual.date < target]
    if not (history.date < target).all(): raise AssertionError("future leakage")
    load,pv=_pivots(actual)
    def run(pivot,method): return _ridge_forecast(pivot,target) if method=="ridge" else _simple_forecast(pivot,target,method)
    load_kw=np.maximum(run(load,load_method),0); pv_kw=np.maximum(run(pv,pv_method),0)
    # A day-ahead night rule based only on historical positive frequency.
    hist_pv=pv.loc[pv.index < target]
    night=(hist_pv.gt(1e-9).mean(axis=0).to_numpy() < .02)
    pv_kw[night]=0
    return pd.DataFrame({"date":target,"slot":np.arange(1,145),"load_pred_kw":load_kw,"pv_pred_kw":pv_kw,"load_pred_kwh":load_kw/6,"pv_pred_kwh":pv_kw/6})

def rolling_prediction_evaluation(actual: pd.DataFrame, start="2025-01-15", end="2025-01-31") -> tuple[pd.DataFrame, pd.DataFrame, ForecastChoice]:
    records=[]
    for d in pd.date_range(start,end):
        truth=actual[actual.date==d].sort_values("slot")
        for method in ("d1","mean7","ridge"):
            pred=forecast_day(actual,d,method,method)
            for variable,pcol,tcol in (("load","load_pred_kw","load_kw"),("pv","pv_pred_kw","pv_actual_kw")):
                err=pred[pcol].to_numpy()-truth[tcol].to_numpy()
                daily_rmse=float(np.sqrt(np.mean(err**2)))
                records.extend({"date":d,"slot":slot+1,"method":method,"variable":variable,"error_kw":float(e),"absolute_error_kw":float(abs(e)),"squared_error_kw2":float(e*e),"daily_rmse_kw":daily_rmse} for slot,e in enumerate(err))
    detail=pd.DataFrame(records)
    rows=[]
    for (variable,method),g in detail.groupby(["variable","method"]):
        rows.append({"variable":variable,"method":method,"mae_kw_all":g.absolute_error_kw.mean(),"rmse_kw_all":float(np.sqrt(g.squared_error_kw2.mean())),"daily_rmse_mean_kw":g.groupby('date').daily_rmse_kw.first().mean(),"observations":len(g)})
    metrics=pd.DataFrame(rows)
    chosen={v:metrics[metrics.variable==v].sort_values(["rmse_kw_all","mae_kw_all"]).iloc[0].method for v in ("load","pv")}
    return detail,metrics,ForecastChoice(chosen["load"],chosen["pv"])

def build_oos_forecasts(actual: pd.DataFrame, dates, choice: ForecastChoice) -> pd.DataFrame:
    return pd.concat([forecast_day(actual,d,choice.load_method,choice.pv_method) for d in dates],ignore_index=True)
