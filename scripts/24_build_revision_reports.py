from hashlib import sha256
from io import StringIO
from pathlib import Path
import json
import subprocess

import matplotlib.pyplot as plt
import pandas as pd


ROOT = Path(__file__).parents[1]
REPORTS = ROOT / "reports"
DIAG = ROOT / "outputs/diagnostics"
FIGURES = REPORTS / "figures/diagnostics"
FIGURES.mkdir(parents=True, exist_ok=True)
BASE = "67467ab313198c57c554b23f83698bc547e3ba7b"


def baseline_csv(path):
    value = subprocess.run(["git", "show", f"{BASE}:{path}"], cwd=ROOT, check=True, capture_output=True).stdout.decode("utf-8-sig")
    return pd.read_csv(StringIO(value))


def table(frame):
    return "```text\n" + frame.to_string(index=False, float_format=lambda x:f"{x:.3f}") + "\n```"


old_q3 = baseline_csv("outputs/q3/q3_strategy_comparison.csv")
new_q3 = pd.read_csv(ROOT / "outputs/q3/q3_strategy_comparison.csv")
old_q43 = baseline_csv("outputs/q4/q4_3_strategy_comparison.csv")
new_q43 = pd.read_csv(ROOT / "outputs/q4/q4_3_strategy_comparison.csv")
fields = ["total_cost_yuan", "emergency_cost_yuan", "emergency_purchase_kwh", "daily_emergency_cvar95_yuan", "daily_total_cvar95_yuan", "remaining_energy_kwh", "revision_count"]
comparisons = []
for branch, old, new in (("Q3", old_q3, new_q3), ("Q4-3", old_q43, new_q43)):
    joined = old[["policy"]+fields].merge(new[["policy"]+fields], on="policy", suffixes=("_before", "_after"))
    for row in joined.itertuples():
        item = {"branch":branch, "policy":row.policy}
        for field in fields:
            item[f"{field}_before"] = getattr(row, f"{field}_before")
            item[f"{field}_after"] = getattr(row, f"{field}_after")
            item[f"{field}_change"] = getattr(row, f"{field}_after") - getattr(row, f"{field}_before")
        comparisons.append(item)
revision = pd.DataFrame(comparisons)
revision.to_csv(DIAG / "q3_q4_3_before_after.csv", index=False)

accuracy = pd.read_csv(DIAG / "forecast_boundary_accuracy_summary.csv")
accuracy_main = accuracy[accuracy.region.eq("all_available_targets")].copy()
gaps = pd.read_csv(DIAG / "planning_execution_gap.csv")
ablation = pd.read_csv(ROOT / "outputs/q3/q3_18h_ablation_comparison.csv")
q3_cal = pd.read_csv(ROOT / "outputs/q3/q3_delta_selection.csv")
q4_cal = pd.read_csv(ROOT / "outputs/q4/q4_delta_selection.csv")

hash_paths = [
    "data/raw/附件1.xlsx", "data/raw/附件2.xlsx", "data/raw/附件3.xlsx", "data/raw/附件4.xlsx",
    "outputs/q1/result1.xlsx", "outputs/q2/result2.xlsx", "outputs/q3/result3.xlsx",
    "outputs/q4/result4-2.xlsx", "outputs/q4/result4-3.xlsx",
]
hashes = pd.DataFrame([{"path":path,"sha256":sha256((ROOT/path).read_bytes()).hexdigest().upper()} for path in hash_paths])
hashes.to_csv(DIAG / "formal_artifact_hashes.csv", index=False)

formal_accuracy = accuracy_main[accuracy_main.period.eq("formal_2025-02-01_2025-12-31")]
pivot = formal_accuracy[formal_accuracy.forecast_type.isin(["legacy_10min_bfill","observed_anchor_10min"])].pivot(index="issue_hour", columns="forecast_type", values="rmse_kw")
pivot.plot.bar(figsize=(9,5)); plt.ylabel("Global RMSE (kW)"); plt.xlabel("Issue hour"); plt.tight_layout(); plt.savefig(FIGURES/"forecast_boundary_rmse.png",dpi=300); plt.close()
abl_daily = pd.read_csv(ROOT/"outputs/q3/q3_18h_ablation_daily_summary.csv",parse_dates=["date"])
official_daily = pd.read_csv(ROOT/"outputs/q3/q3_daily_summary.csv",parse_dates=["date"]).query("policy == 'C3'")
plot = pd.DataFrame({"date":abl_daily.date,"06/12":abl_daily.total_cost_yuan.cumsum(),"06/12/18":official_daily.total_cost_yuan.cumsum()}).set_index("date")
plot.plot(figsize=(10,5)); plt.ylabel("Cumulative cost (yuan)"); plt.tight_layout(); plt.savefig(FIGURES/"q3_18h_ablation_cumulative_cost.png",dpi=300); plt.close()

(REPORTS / "problem_code_audit.md").write_text(f"""# 题目、假设、代码与结果对应核查

基线提交：`{BASE}`。本轮原始附件未修改；正式期为2025-02-01至2025-12-31，共334天、每天144个10分钟时段。

| 题目要求或数据说明 | 本项目解释/附加假设 | 主要代码 | 正式结果 |
|---|---|---|---|
| Q1要求0:00与24:00储能量相等 | 仅Q1施加日首尾相等 | `deterministic_dispatch.py`、`03_solve_q1.py` | `outputs/q1/result1.xlsx` |
| Q2利用附件2历史预测，附件1电价每日重复 | Q2不用附件3/4，SOC跨日连续 | `prediction.py`、`04_run_q2.py` | `outputs/q2/result2.xlsx` |
| Q3在00/06/12/18发布附件3未来24小时整点PV预报 | 发布时点左端用刚结束的合法观测；Q3采用final_vs_original结算 | `io.py::build_10min_pv_forecast`、`q3.py` | `outputs/q3/result3.xlsx` |
| Q3减少/增加购电分别按50%违约成本/1.5倍价格处理 | 当前解释为最终F相对原始G0：`pF+0.5p|F-G0|`，不是逐次修订收费 | `q3.py::settlement_components` | `q3_execution_detail.csv` |
| Q4电价随时间变化 | 题面未说明公布时刻；额外假设当天144点价格00:00已知 | `q4.py`、`16_run_q4_3.py` | `outputs/q4/result4-3.xlsx` |

所有Q2-Q4策略均从共同的分支初态出发，之后独立传递实际SOC，不施加每日首尾相等。哈希记录：

{table(hashes)}
""", encoding="utf-8")

(REPORTS / "forecast_boundary_revision.md").write_text(f"""# 附件3首小时边界修订证据

旧方法在发布后首个原始整点之前使用下一整点值bfill。新方法保持所有原始整点值不变，并以截至发布时点已经结束的最后一个10分钟观测作为左端点：06/12/18对应当日slot36/72/108，00:00对应前一日slot144；2025-01-01无前日数据时明确回退到首个整点预报。发布后真实值不会进入锚点。

`supplier_raw_hourly`只在附件3原始整点上评价；`legacy_10min_bfill`和`observed_anchor_10min`才是10分钟决策输入，三者不能混称。总体结果：

{table(accuracy_main)}

策略前后变化直接以基线提交CSV和本轮正式CSV计算：

{table(revision)}
""",encoding="utf-8")

(REPORTS / "planning_execution_gap.md").write_text(f"""# 规划场景与实际执行差异

两阶段模型的所有场景共享日前G，但每个场景的追索变量可见该场景完整轨迹。正式执行每天固定G，仅观察当前时段真实负荷/PV，未来仍用合法预测。下表的完美信息追索在同一G、同一日初SOC、同一价格和物理约束下使用整日真实轨迹，是固定G诊断下界，不是正式策略、不是EVPI，也没有参与参数选择。

{table(gaps)}

实际与规划期望的差距可能同时来自历史场景覆盖、预测/残差重构偏差以及因果执行的信息限制。实际与完美信息下界之差量化了在固定G条件下可由全日信息消除的部分，但不能据此将剩余差异唯一归因。规划CVaR的风险对象是场景紧急购电费用；实际日紧急费用CVaR与实际日总费用CVaR是两个独立统计量。Q2的20个、Q3/Q4-3的10个等权场景在alpha=0.95时，规划CVaR均等于最坏场景费用，不是稳定的全年尾部估计。
""",encoding="utf-8")

(REPORTS / "paper_evidence.md").write_text(f"""# 论文可用证据汇总

## 模型与信息集

10分钟能量平衡为 `G_t+R_t+PV_t+D_t=L_t+C_t+W_t`，SOC递推为 `S_t=S_(t-1)+0.9C_t-D_t/0.9`，并满足1200至10800 kWh及充放电各不超过5000/6 kWh。Q3原计划G0在00:00形成，后续只调整未执行段；实际控制仅用当前观测与当时合法预测。

Q3非紧急结算采用 `sum[p_t F_t+0.5 p_t |F_t-G0_t|]`，紧急费用为 `sum[5p_tR_t]`。事件触发值为 `NV=J_keep-J_adjust`，C2阈值0，C3阈值delta只由1月22-31日冻结。

## 校准与正式结果

Q3校准：

{table(q3_cal)}

Q4-3校准：

{table(q4_cal)}

Q3正式结果：

{table(new_q3)}

Q4-3正式结果：

{table(new_q43)}

## 其他发布时间是否必要

固定新C3、delta、场景设置、共同初态和结算，18:00发布消融结果如下：

{table(ablation)}

保留18:00更新降低了真实总费用、紧急购电费用、紧急电量和两类实际日CVaR，但增加修订次数。故06/12之外的18:00预报具有真实经济与风险价值，是否采用仍取决于对操作频率的管理偏好。

## 局限与后续

只有一个自然年的历史，早期场景池需有放回抽样；左锚点把刚结束区间平均功率作为发布时点功率估计；Q4全天价格00:00已知是附加假设；final_vs_original结算尚无权威补充说明。受限价格信息、另一结算机制下重新优化和跨日终端价值应作为后续扩展，不混入本轮正式结果。
""",encoding="utf-8")

print(revision[["branch","policy","total_cost_yuan_before","total_cost_yuan_after","total_cost_yuan_change","revision_count_before","revision_count_after"]].to_string(index=False))
print(hashes.to_string(index=False))
