from pathlib import Path
import json
import sys

import matplotlib.pyplot as plt
import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).parents[1] / "src"))
from microgrid.q4 import KEY_DATES


ROOT = Path(__file__).parents[1]
OUT = ROOT / "outputs/q4"
REPORTS = ROOT / "reports"
FIGURES = REPORTS / "figures/q4"
FIGURES.mkdir(parents=True, exist_ok=True)

q42 = pd.read_csv(OUT / "q4_2_execution_detail.csv", parse_dates=["date"])
q43 = pd.read_csv(OUT / "q4_3_execution_detail.csv", parse_dates=["date"])
d42 = pd.read_csv(OUT / "q4_2_daily_summary.csv", parse_dates=["date"])
d43 = pd.read_csv(OUT / "q4_3_daily_summary.csv", parse_dates=["date"])
c42 = pd.read_csv(OUT / "q4_2_strategy_comparison.csv")
c43 = pd.read_csv(OUT / "q4_3_strategy_comparison.csv")
calibration = pd.read_csv(OUT / "q4_delta_selection.csv")
m42 = json.loads((OUT / "q4_2_run_manifest.json").read_text(encoding="utf-8"))
m43 = json.loads((OUT / "q4_3_run_manifest.json").read_text(encoding="utf-8"))
comparison = pd.concat([c42, c43], ignore_index=True)
comparison.to_csv(OUT / "q4_strategy_comparison.csv", index=False)
q43[["date", "slot", "policy", "original_grid_plan_kwh"]].rename(
    columns={"original_grid_plan_kwh": "grid_plan_kwh"}
).to_csv(OUT / "q4_3_day_ahead_plans.csv", index=False)


def monthly_table(daily, branch):
    return daily.assign(month=daily.date.dt.month).groupby(["policy", "month"]).agg(
        total_cost_yuan=("total_cost_yuan", "sum"),
        emergency_cost_yuan=("emergency_cost_yuan", "sum"),
        emergency_purchase_kwh=("emergency_purchase_kwh", "sum"),
        remaining_energy_kwh=("remaining_energy_kwh", "sum"),
    ).reset_index().assign(branch=branch)


monthly42 = monthly_table(d42, "Q4-2")
monthly43 = monthly_table(d43, "Q4-3")
monthly42.to_csv(OUT / "q4_2_monthly_summary.csv", index=False)
monthly43.to_csv(OUT / "q4_3_monthly_summary.csv", index=False)


def build_key_tables(execution, branch, main, plan_fields):
    selected = execution[execution.policy == main]
    table1, table2, table3 = [], [], []
    for date in KEY_DATES:
        day = selected[selected.date == date].sort_values("slot")
        for hour in (10, 12, 14, 16, 18, 20):
            row = day[day.slot == hour * 6 + 1].iloc[0]
            item = {"date": date, "interval": f"{hour}:00-{hour}:10", "slot": hour * 6 + 1}
            item.update({field: row[field] for field in plan_fields})
            item["daily_total_cost_yuan"] = day.total_cost_yuan.sum()
            table1.append(item)
        for block in range(6):
            table2.append({
                "date": date, "interval": f"{block*4}:00-{(block+1)*4}:00",
                "charge_kwh": day.iloc[block*24:(block+1)*24].charge_kwh.sum(),
                "discharge_kwh": day.iloc[block*24:(block+1)*24].discharge_kwh.sum(),
                "soc_0000_kwh": day.soc_start_kwh.iloc[0] if block == 0 else np.nan,
                "soc_2400_kwh": day.soc_end_kwh.iloc[-1] if block == 1 else np.nan,
            })
        indices = np.flatnonzero(day.emergency_purchase_kwh.to_numpy() > 1e-8)
        groups = np.split(indices, np.where(np.diff(indices) > 1)[0] + 1) if len(indices) else []
        for group in groups:
            start, end = int(group[0]) * 10, (int(group[-1]) + 1) * 10
            label = f"{start//60}:{start%60:02d}-{(end//60)%24}:{end%60:02d}" + ("+1" if end >= 1440 else "")
            table3.append({"date": date, "interval": label, "emergency_purchase_kwh": day.iloc[group].emergency_purchase_kwh.sum()})
    pd.DataFrame(table1).to_csv(OUT / f"q4_{branch}_key_dates_table1.csv", index=False)
    pd.DataFrame(table2).to_csv(OUT / f"q4_{branch}_key_dates_table2.csv", index=False)
    pd.DataFrame(table3).to_csv(OUT / f"q4_{branch}_key_dates_table3.csv", index=False)


build_key_tables(q42, "2", m42["main_policy"], ["grid_purchase_kwh"])
build_key_tables(q43, "3", m43["main_policy"], ["original_grid_plan_kwh", "final_grid_plan_kwh"])

combined_daily = pd.concat([
    d42.assign(series="Q4-2/" + d42.policy),
    d43.assign(series="Q4-3/" + d43.policy),
])
combined_daily.pivot(index="date", columns="series", values="total_cost_yuan").cumsum().plot(figsize=(13, 6))
plt.ylabel("Cumulative cost (yuan)"); plt.xlabel("Date"); plt.tight_layout()
plt.savefig(FIGURES / "q4_cumulative_cost.png", dpi=300); plt.close()

monthly = pd.concat([monthly42, monthly43])
monthly.assign(series=monthly.branch + "/" + monthly.policy).pivot(
    index="month", columns="series", values="emergency_purchase_kwh"
).plot.bar(figsize=(13, 6))
plt.ylabel("Emergency purchase (kWh)"); plt.xlabel("Month"); plt.tight_layout()
plt.savefig(FIGURES / "q4_monthly_emergency.png", dpi=300); plt.close()

for date in KEY_DATES:
    day = q43[(q43.policy == m43["main_policy"]) & (q43.date == date)].sort_values("slot")
    fig, left = plt.subplots(figsize=(13, 6)); right = left.twinx()
    left.plot(day.slot, day.load_actual_kwh, label="Load", color="black")
    left.plot(day.slot, day.pv_actual_kwh, label="PV", color="green")
    left.plot(day.slot, day.charge_kwh, label="Charge", color="royalblue")
    left.plot(day.slot, day.discharge_kwh, label="Discharge", color="firebrick")
    right.plot(day.slot, day.price_yuan_per_kwh, label="Price", color="darkorange")
    right.plot(day.slot, day.soc_end_kwh / 1000, label="SOC / 1000", color="purple")
    left.set_xlabel("10-minute slot"); left.set_ylabel("Energy (kWh)"); right.set_ylabel("Price (yuan/kWh), SOC/1000")
    lines = left.lines + right.lines; left.legend(lines, [line.get_label() for line in lines], ncol=6, loc="upper center")
    fig.tight_layout(); fig.savefig(FIGURES / f"q4_typical_{date.date()}.png", dpi=300); plt.close(fig)

c43.plot.scatter(x="revision_count", y="total_cost_yuan", figsize=(8, 5))
for _, row in c43.iterrows(): plt.annotate(row.policy, (row.revision_count, row.total_cost_yuan))
plt.xlabel("Adopted revisions"); plt.ylabel("Total cost (yuan)"); plt.tight_layout()
plt.savefig(FIGURES / "q4_cost_vs_revisions.png", dpi=300); plt.close()


def text_table(frame):
    return "```text\n" + frame.to_string(index=False, float_format=lambda value: f"{value:.3f}") + "\n```"


report = f"""# 问题四：波动电价下的问题二与问题三重算

## 信息与价格边界

问题四使用附件4逐日、逐10分钟时段电价，附件2提供历史及实际负荷/光伏，4-3另外使用附件3按00:00、06:00、12:00、18:00发布的光伏预报。主模型假设一天144个附件4价格在当天00:00已知；这是沿用v3.1的建模假设，题面只提供全年价格数据，并未明确承诺日前公布。本轮没有增加价格预测模型。价格单位直接为元/kWh，不除以6；只有kW功率转10分钟电量时除以6。

4-2结算为 `sum(p*G)+sum(5*p*R)`。4-3采用最终计划相对00:00原计划结算：`sum(p*F+0.5*p*abs(F-G0))+sum(5*p*R)`。`remaining_energy_kwh`表示未消纳总能量，不能全部解释为弃光。

## 初始化和事前参数

附件4版离线初始化从2025-01-01 00:00的6000 kWh开始连续运行4464个时段，1月费用不进入正式比较；三组4-2策略和四组4-3策略共同以 `{m42['common_feb1_soc_kwh']:.6f}` kWh进入2月，之后分别传递各自真实SOC。初始化首日使用已知实际轨迹属于离线状态构造假设，1月2-31日使用昨日同槽预测和因果执行。

4-2中B1为点预测确定性计划，B3为{m42['scenario_count']}场景且lambda=0的随机规划，B4为lambda={m42['b4_lambda']:.3f}的风险偏好配置；B4作为官方表策略是事前配置，不是根据2-12月结果挑选。4-3中C0/C1不调整G，C2在发布点按NV>0调整，C3使用仅由1月22-31日冻结的delta。校准如下：

{text_table(calibration)}

10个校准日的经验日CVaR95等于最大日值，不是稳定的尾部风险估计；小场景规划CVaR同样需谨慎解释。

## 334天正式结果

{text_table(comparison)}

`daily_emergency_cvar95_yuan`与`daily_total_cvar95_yuan`来自实际334天日费用；规划模型内的场景紧急费用CVaR另存于规划诊断，二者不混用。成本最低、紧急购电最少、修订最少通常不是同一策略，本报告不预设B4或C3全面占优。C3阈值是风险调整目标改善的触发门槛，不是题目规定的每次管理成本，NV也不是严格EVSI。

## 因果执行与局限

每天00:00的G0及4-2的G在日内固定或按4-3规则仅修改未执行段。每个时段开始前观察当前负荷和光伏，储能执行器只把当前点替换为观测，未来仍使用当时合法的预测；实际SOC先按可行充放电递推，再结算紧急购电与剩余能量。所有策略不设每日终端SOC相等，也不每日重置。

主要局限是仅有一个自然年的历史，早期残差场景池较小且可能有放回抽样；当天电价全部已知是建模假设；日末SOC虽跨日传递，但日内优化未显式计入次日电价价值。另一结算规则下仅做固定轨迹重计价并不等于重优化，本轮主交付不扩展该可选增强项。
"""
(REPORTS / "q4_analysis.md").write_text(report, encoding="utf-8")
print(comparison.to_string(index=False))
