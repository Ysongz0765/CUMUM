from pathlib import Path
import json, sys
import pandas as pd
sys.path.insert(0, str(Path(__file__).parents[1] / "src"))
from microgrid.result_template import inspect_template

ROOT = Path(__file__).parents[1]; raw = ROOT / "data/raw"; reports = ROOT / "reports"; reports.mkdir(exist_ok=True)
def sheet_audit(path, sheet):
    df = pd.read_excel(path, sheet_name=sheet)
    nums = df.select_dtypes("number")
    dates = pd.to_datetime(df.iloc[:, 0], errors='coerce', utc=True) if len(df.columns) else pd.Series(dtype='datetime64[ns]')
    return {"shape": list(df.shape), "columns": [str(c) for c in df.columns], "missing": int(df.isna().sum().sum()), "duplicates": int(df.duplicated().sum()), "dtypes": {str(k): str(v) for k, v in df.dtypes.items()}, "date_range": [str(dates.min()), str(dates.max())] if dates.notna().any() else None, "invalid_date_count": int(dates.isna().sum()), "numeric_ranges": {str(c): {"min": float(nums[c].min()), "max": float(nums[c].max()), "negative": int((nums[c] < 0).sum())} for c in nums}}
audit = {}
for p in sorted(raw.glob("附件*.xlsx")): audit[p.name] = {s: sheet_audit(p, s) for s in pd.ExcelFile(p).sheet_names}
audit["templates"] = {p.name: inspect_template(p) for p in sorted((raw / "templates").glob("*.xlsx"))}
(reports / "data_audit.json").write_text(json.dumps(audit, ensure_ascii=False, indent=2), encoding="utf-8")
lines = ["# 数据审计报告", "", "审计只读原始副本，未修改任何 Excel。", ""]
for name, sheets in audit.items():
    lines.append(f"## {name}")
    for s, i in sheets.items(): lines.append(f"- `{s}` shape={i.get('shape', i.get('sheets'))}, missing={i.get('missing', 'n/a')}, duplicates={i.get('duplicates', 'n/a')}")
(reports / "data_audit.md").write_text("\n".join(lines), encoding="utf-8")
print("audit written")
