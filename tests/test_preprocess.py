import sys
from pathlib import Path
sys.path.insert(0,str(Path(__file__).parents[1]/'src'))
from microgrid.io import read_pv_forecast,build_10min_pv_forecast
def test_attachment3_date_fill_forward(): assert read_pv_forecast(Path(__file__).parents[1]/'data/raw/附件3.xlsx').date.nunique()==365
def test_attachment3_4_issues_per_day():
    df=read_pv_forecast(Path(__file__).parents[1]/'data/raw/附件3.xlsx'); assert df.groupby('date').issue_time.nunique().eq(4).all()
def test_attachment3_24_horizons(): assert len(read_pv_forecast(Path(__file__).parents[1]/'data/raw/附件3.xlsx'))==35040
def test_attachment3_interpolation_has_no_leading_nan():
    df=read_pv_forecast(Path(__file__).parents[1]/'data/raw/附件3.xlsx');x=build_10min_pv_forecast(df,'2025-01-01','6:00');assert len(x)==144 and not x.pv_forecast_kw.isna().any()
