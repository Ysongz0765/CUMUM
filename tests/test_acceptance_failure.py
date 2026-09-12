from pathlib import Path
import os,subprocess,sys
import pandas as pd

ROOT=Path(__file__).parents[1]

def run_validator(path):
    env=os.environ.copy();env['Q2_DETAIL_PATH']=str(path);env['PYTHONPATH']=str(ROOT/'src')
    return subprocess.run([sys.executable,'scripts/05_validate_q1_q2.py'],cwd=ROOT,env=env,capture_output=True,text=True)

def test_validator_rejects_stale_balance_and_fee_columns(tmp_path):
    x=pd.read_csv(ROOT/'outputs/q2/q2_execution_detail.csv')
    x.loc[0,'charge_kwh']+=1.0  # keep the saved balance_error_kwh unchanged
    x.loc[1,'plan_cost_yuan']+=10.0
    bad=tmp_path/'bad_detail.csv';x.to_csv(bad,index=False)
    result=run_validator(bad)
    assert result.returncode!=0
    assert 'independent_balance_within_1e-6' in result.stderr or 'FAILED CHECKS' in result.stderr
