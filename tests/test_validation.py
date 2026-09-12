import sys
from pathlib import Path
sys.path.insert(0,str(Path(__file__).parents[1]/'src'))
from microgrid.features import add_lag_features
import pandas as pd
def test_no_future_leakage_in_lag_features():
    d=pd.DataFrame({'date':pd.to_datetime(['2025-01-01','2025-01-02']),'slot':[1,1],'load_kw':[1,2]}); x=add_lag_features(d); assert pd.isna(x.iloc[0].load_d1_same_slot) and x.iloc[1].load_d1_same_slot==1
