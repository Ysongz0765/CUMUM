from pathlib import Path
import pandas as pd
import re

def inspect_template(path: Path) -> dict:
    xls = pd.ExcelFile(path)
    return {"file": path.name, "sheets": {s: {"shape": list(pd.read_excel(path, sheet_name=s, header=None).shape), "header": pd.read_excel(path, sheet_name=s, header=None, nrows=1).iloc[0].astype(str).tolist()} for s in xls.sheet_names}}

def build_time_mapping(labels):
    return {str(label): i + 1 for i, label in enumerate(labels) if str(label).strip() not in {"", "nan", "...", "⋮"}}

def build_q1_time_mapping(q1: pd.DataFrame, template_path: Path) -> pd.DataFrame:
    labels=pd.read_excel(template_path,sheet_name="计划购电量",header=None).iloc[1:,0].dropna().astype(str)
    targets={}
    for row,label in enumerate(labels,start=2):
        m=re.match(r"^(\d{1,2}):(\d{2})(?:\+1)?-",label)
        if not m: raise ValueError(f"invalid result1 interval {label!r}")
        slot=(int(m.group(1))*60+int(m.group(2)))//10+1
        targets[slot]=(row,label,f"B{row}")
    if set(targets)!=set(range(1,145)): raise ValueError("result1 mapping is not one-to-one")
    rows=[]
    for r in q1.sort_values("slot").itertuples():
        row,label,cell=targets[r.slot]
        rows.append({'source_row':r.source_row,'source_time_label':r.source_time_label,'interval_date':r.interval_start.date(),'interval_start':r.interval_start,'interval_end':r.interval_end,'slot':r.slot,'target_cell':cell,'result1_row':row,'result1_time_label':label})
    return pd.DataFrame(rows)
