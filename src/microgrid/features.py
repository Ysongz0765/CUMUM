import numpy as np
import pandas as pd

def add_calendar_features(df):
    out=df.copy(); out["day_of_year"]=out.date.dt.dayofyear; out["month"]=out.date.dt.month; out["weekday"]=out.date.dt.weekday; out["is_weekend"]=out.weekday>=5
    out["sin_time"]=np.sin(2*np.pi*(out.slot-1)/144); out["cos_time"]=np.cos(2*np.pi*(out.slot-1)/144)
    out["sin_doy"]=np.sin(2*np.pi*(out.day_of_year-1)/365); out["cos_doy"]=np.cos(2*np.pi*(out.day_of_year-1)/365)
    return out

def add_lag_features(df):
    out=df.sort_values(["date","slot"]).copy(); g=out.groupby("slot")["load_kw"]
    for days,name in [(1,"load_d1_same_slot"),(2,"load_d2_same_slot"),(7,"load_d7_same_slot")]: out[name]=g.shift(days)
    daily=out.groupby("date").load_kw.agg(['mean','last']); out["load_d1_mean"]=out.date.map(daily['mean'].shift(1)); out["load_d1_last"]=out.date.map(daily['last'].shift(1))
    return out
