import pandas as pd

def validate_actual(df):
    assert len(df)==52560 and df[["date","slot"]].duplicated().sum()==0
    assert df.load_kw.ge(0).all() and df.pv_actual_kw.ge(0).all() and df.price_yuan_per_kwh.gt(0).all()
    assert not df.isna().any().any()

def validate_forecast(df):
    assert len(df)==35040 and df.date.nunique()==365
    assert df.groupby("date").issue_time.nunique().eq(4).all() and df.groupby(["date","issue_time"]).size().eq(24).all()
