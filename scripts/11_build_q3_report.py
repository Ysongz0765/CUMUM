from pathlib import Path
import json
import numpy as np
import pandas as pd
import matplotlib.pyplot as plt

ROOT=Path(__file__).parents[1];out=ROOT/'outputs/q3';reports=ROOT/'reports';figs=reports/'figures/q3';figs.mkdir(parents=True,exist_ok=True)
x=pd.read_csv(out/'q3_execution_detail.csv',parse_dates=['date']);daily=pd.read_csv(out/'q3_daily_summary.csv',parse_dates=['date']);comp=pd.read_csv(out/'q3_strategy_comparison.csv');rv=pd.read_csv(out/'q3_revision_log.csv',parse_dates=['date']);snap=pd.read_csv(out/'q3_plan_snapshots.csv',parse_dates=['date']);cal=pd.read_csv(out/'q3_delta_selection.csv');acc=pd.read_csv(out/'q3_forecast_update_accuracy.csv',parse_dates=['date']);manifest=json.loads((out/'run_manifest.json').read_text(encoding='utf-8'));main=manifest['main_policy'];m=x[x.policy==main]
monthly=daily.assign(month=daily.date.dt.month).groupby(['policy','month']).agg(total_cost_yuan=('total_cost_yuan','sum'),emergency_cost_yuan=('emergency_cost_yuan','sum'),emergency_purchase_kwh=('emergency_purchase_kwh','sum'),remaining_energy_kwh=('remaining_energy_kwh','sum')).reset_index();monthly.to_csv(out/'q3_monthly_summary.csv',index=False)
revision_summary=rv.groupby(['policy','issue_hour']).agg(
    decisions=('triggered','size'),
    revisions=('triggered','sum'),
    mean_nv_yuan=('nv_yuan','mean'),
    candidate_vs_g0_increase_kwh=('candidate_increase_kwh','sum'),
    candidate_vs_g0_decrease_kwh=('candidate_decrease_kwh','sum'),
).reset_index()
triggered=rv[['policy','date','issue_hour','triggered']]
adopted=snap.merge(triggered,on=['policy','date','issue_hour'],validate='many_to_one')
adopted_delta=np.where(adopted.triggered,adopted.effective_plan_kwh-adopted.plan_before_kwh,0.)
adopted=adopted.assign(
    adopted_increase_kwh=np.maximum(adopted_delta,0),
    adopted_decrease_kwh=np.maximum(-adopted_delta,0),
)
adopted_summary=adopted.groupby(['policy','issue_hour']).agg(
    adopted_change_increase_kwh=('adopted_increase_kwh','sum'),
    adopted_change_decrease_kwh=('adopted_decrease_kwh','sum'),
).reset_index()
revision_summary=revision_summary.merge(adopted_summary,on=['policy','issue_hour'],how='left',validate='one_to_one')
revision_summary.to_csv(out/'q3_revision_by_issue.csv',index=False)
final_delta=x.final_grid_plan_kwh-x.original_grid_plan_kwh
final_deviation=x.assign(
    final_vs_g0_increase_kwh=np.maximum(final_delta,0),
    final_vs_g0_decrease_kwh=np.maximum(-final_delta,0),
).groupby('policy').agg(
    final_vs_g0_increase_kwh=('final_vs_g0_increase_kwh','sum'),
    final_vs_g0_decrease_kwh=('final_vs_g0_decrease_kwh','sum'),
).reset_index()
final_deviation.to_csv(out/'q3_final_plan_deviation.csv',index=False)

accuracy_rows=[]
for issue_hour,g in acc.groupby('issue_hour'):
    n=g.observations.to_numpy(float);total=n.sum()
    accuracy_rows.append({
        'issue_hour':issue_hour,
        'observations':int(total),
        'original_mae_kw_all':float(np.average(g.original_mae_kw,weights=n)),
        'latest_mae_kw_all':float(np.average(g.latest_mae_kw,weights=n)),
        'original_rmse_kw_all':float(np.sqrt(np.sum(n*g.original_rmse_kw.to_numpy()**2)/total)),
        'latest_rmse_kw_all':float(np.sqrt(np.sum(n*g.latest_rmse_kw.to_numpy()**2)/total)),
        'original_daily_rmse_mean_kw':float(g.original_rmse_kw.mean()),
        'latest_daily_rmse_mean_kw':float(g.latest_rmse_kw.mean()),
    })
accuracy=pd.DataFrame(accuracy_rows);accuracy.to_csv(out/'q3_forecast_update_accuracy_summary.csv',index=False)
tariff=m.drop_duplicates('slot').set_index('slot').price_yuan_per_kwh
sequential=[]
for (policy,date),base in daily.set_index(['policy','date']).iterrows():
    adopted=rv[(rv.policy==policy)&(rv.date==date)&rv.triggered]
    change=0.
    for issue in adopted.issue_hour:
        z=snap[(snap.policy==policy)&(snap.date==date)&(snap.issue_hour==issue)];p=z.slot.map(tariff).to_numpy();delta=z.effective_plan_kwh-z.plan_before_kwh;change+=float(np.sum(1.5*p*np.maximum(delta,0)-.5*p*np.maximum(-delta,0)))
    sequential.append({'analysis_type':'fixed existing policy trajectory repricing','policy':policy,'date':date,'final_vs_original_non_emergency_yuan':base.final_non_emergency_cost_yuan,'sequential_revision_non_emergency_yuan':base.original_plan_cost_yuan+change,'difference_yuan':base.original_plan_cost_yuan+change-base.final_non_emergency_cost_yuan})
settlement_sensitivity=pd.DataFrame(sequential);settlement_sensitivity.to_csv(out/'q3_settlement_interpretation_sensitivity.csv',index=False)

keydates=pd.to_datetime(['2025-03-20','2025-06-21','2025-09-23','2025-12-21']);t1=[];t2=[];t3=[]
for d in keydates:
    z=m[m.date==d].sort_values('slot')
    for h in [10,12,14,16,18,20]:
        row=z[z.slot==h*6+1].iloc[0];t1.append({'date':d,'interval':f'{h}:00-{h}:10','slot':h*6+1,'original_plan_kwh':row.original_grid_plan_kwh,'final_plan_kwh':row.final_grid_plan_kwh,'daily_original_plan_kwh':z.original_grid_plan_kwh.sum(),'daily_final_plan_kwh':z.final_grid_plan_kwh.sum(),'daily_total_cost_yuan':z.total_cost_yuan.sum()})
    for k in range(6):t2.append({'date':d,'interval':f'{4*k}:00-{4*(k+1)}:00','charge_kwh':z.iloc[k*24:(k+1)*24].charge_kwh.sum(),'discharge_kwh':z.iloc[k*24:(k+1)*24].discharge_kwh.sum(),'soc_0000_kwh':z.soc_start_kwh.iloc[0] if k==0 else np.nan,'soc_2400_kwh':z.soc_end_kwh.iloc[-1] if k==1 else np.nan})
    ids=np.flatnonzero(z.emergency_purchase_kwh.to_numpy()>1e-8);groups=np.split(ids,np.where(np.diff(ids)>1)[0]+1) if len(ids) else []
    for g in groups:
        sm=int(g[0])*10;em=(int(g[-1])+1)*10;t3.append({'date':d,'interval':f'{sm//60}:{sm%60:02d}-{(em//60)%24}:{em%60:02d}'+('+1' if em>=1440 else ''),'emergency_purchase_kwh':z.iloc[g].emergency_purchase_kwh.sum()})
pd.DataFrame(t1).to_csv(out/'q3_key_dates_table1.csv',index=False);pd.DataFrame(t2).to_csv(out/'q3_key_dates_table2.csv',index=False);pd.DataFrame(t3).to_csv(out/'q3_key_dates_table3.csv',index=False)

daily.pivot(index='date',columns='policy',values='total_cost_yuan').cumsum().plot(figsize=(12,5));plt.ylabel('Cumulative cost (yuan)');plt.tight_layout();plt.savefig(figs/'q3_cumulative_cost.png',dpi=300);plt.close()
monthly.pivot(index='month',columns='policy',values='emergency_purchase_kwh').plot.bar(figsize=(11,5));plt.ylabel('Emergency purchase (kWh)');plt.tight_layout();plt.savefig(figs/'q3_monthly_emergency.png',dpi=300);plt.close()
revision_summary.pivot(index='issue_hour',columns='policy',values='revisions').plot.bar(figsize=(9,4));plt.ylabel('Adopted revisions');plt.tight_layout();plt.savefig(figs/'q3_revisions_by_issue.png',dpi=300);plt.close()
for d in keydates:
    z=m[m.date==d].sort_values('slot');plt.figure(figsize=(12,5));plt.plot(z.slot,z.load_actual_kwh,label='Load');plt.plot(z.slot,z.pv_actual_kwh,label='PV');plt.plot(z.slot,z.original_grid_plan_kwh,label='G0');plt.plot(z.slot,z.final_grid_plan_kwh,label='F');plt.plot(z.slot,z.emergency_purchase_kwh,label='Emergency');plt.legend(ncol=5);plt.ylabel('kWh / 10 min');plt.tight_layout();plt.savefig(figs/f'q3_typical_{d.date()}.png',dpi=300);plt.close()

tables=lambda d:'```text\n'+d.to_string(index=False,float_format=lambda v:f'{v:.3f}')+'\n```'
c0=float(comp.loc[comp.policy=='C0','total_cost_yuan'].iloc[0]);c1=float(comp.loc[comp.policy=='C1','total_cost_yuan'].iloc[0]);c2=float(comp.loc[comp.policy=='C2','total_cost_yuan'].iloc[0]);c3=float(comp.loc[comp.policy=='C3','total_cost_yuan'].iloc[0])
c2_revisions=int(comp.loc[comp.policy=='C2','revision_count'].iloc[0]);c3_revisions=int(comp.loc[comp.policy=='C3','revision_count'].iloc[0])
repricing_totals=settlement_sensitivity.groupby('policy').sequential_revision_non_emergency_yuan.sum()+daily.groupby('policy').emergency_cost_yuan.sum()
report=f'''# 问题三：分时预报驱动的滚动购电调整

## 信息顺序与结算

每天0:00使用附件3的00:00光伏预报、附件2历史训练的负荷Ridge预测和附件1电价生成不可覆盖的原始计划G0。06:00、12:00和18:00只修改尚未执行时段；决策使用当次及更早发布的预报、当前真实SOC和截至该时点已实现的数据。当前10分钟区间开始前观测负荷与光伏，再执行储能反馈；未来真实轨迹不进入规划。

附件3的整点功率在同一次发布内线性插值到10分钟网格，再除以6转为电量。发布后首小时缺失左锚点沿用该次发布的第1小时预测值，不使用未来实际光伏。PV场景误差取同发布时刻、同提前量的历史预报误差；负荷与PV使用同一历史日的完整联合残差轨迹，所有源日期严格早于目标日。

本轮采用相对00:00原计划的最终交付方案结算：非紧急费用为 `sum(p*F + 0.5*p*abs(F-G0))`，紧急费用为 `sum(5*p*R)`。因此p=1时，100调整到80、120和100的非紧急费用分别为90、130和100；100->140->100最终仍为100。逐次相邻计划收费会得到140，只作为另一种解释的局限，不与主结果混用。

## 策略与1月校准

C0全天固定G且储能保持00:00预报；C1固定G但储能反馈使用后续预报；C2在三个发布点定期重优化G；C3仅在 `NV=J_keep-J_adjust > delta` 时采用候选。J_keep和J_adjust使用同一最新场景集、SOC、剩余时域和风险损失，且J_keep仍可优化储能。两阶段场景追索可见整条假设场景，实际执行器只能逐时获得真实观测，两者不能混称。

阈值只用1月22-31日校准：

{tables(cal)}

最终delta={manifest['selected_delta_yuan']:.0f}元。10个校准日的经验CVaR95等于最大日值，不视为稳定尾部估计。

## 334天结果

{tables(comp)}

C1相对C0减少 `{c0-c1:.3f}` 元（`{(1-c1/c0)*100:.3f}%`），表示仅把新预报用于储能反馈已有价值；C2相对C1再减少 `{c1-c2:.3f}` 元（`{(1-c2/c1)*100:.3f}%`），说明允许调整购电计划在本结算解释下有必要。C3相对C2增加 `{c3-c2:.3f}` 元，但将修订次数从{c2_revisions}次降至{c3_revisions}次；C3相对C0仍降低 `{c0-c3:.3f}` 元（`{(1-c3/c0)*100:.3f}%`）。因此若只追求本样本总费用选C2，若重视操作频率和稳健门槛选1月校准的C3。四组均从问题二离线初始化得到的 `{manifest['common_feb1_soc_kwh']:.6f}` kWh进入2月，之后分别传递实际SOC。`remaining_energy_kwh`为未消纳总能量，不全部称为弃光。

按发布时间的调整统计：

{tables(revision_summary)}

候选偏差按候选计划相对G0统计；已采纳变更按触发时 `effective_plan_kwh-plan_before_kwh` 统计，未触发候选贡献0。全年最终生效计划相对G0的偏差另列如下：

{tables(final_deviation)}

相同目标时段的附件3更新前后预测误差：

{tables(accuracy)}

逐次相邻计划收费解释的敏感性另存于 `outputs/q3/q3_settlement_interpretation_sensitivity.csv`。该表只是“固定既有政策轨迹的重新计价”，没有在另一结算规则下重新优化，因此不能用于宣称另一规则下策略仍最优。固定轨迹重计价总费用为 C1={repricing_totals.get('C1',np.nan):.3f} 元、C2={repricing_totals.get('C2',np.nan):.3f} 元、C3={repricing_totals.get('C3',np.nan):.3f} 元。

## 局限

场景库仅覆盖一个自然年，早期历史样本少并允许有放回抽样。调整收费按最终计划相对原始计划结算；若权威补充说明要求逐次修订收费，频繁调整策略的费用会更高。NV是预测的风险调整目标改善值，不等于事后实际节费或严格EVSI。问题四尚未实现。
'''
(reports/'q3_analysis.md').write_text(report,encoding='utf-8')
