from pathlib import Path
import json
import pandas as pd,numpy as np
ROOT=Path(__file__).parents[1];out=ROOT/'outputs/q2';reports=ROOT/'reports'
ex=pd.read_csv(out/'q2_execution_detail.csv',parse_dates=['date'])
plans=pd.read_csv(out/'q2_day_ahead_plans.csv',parse_dates=['date'])
comp=pd.read_csv(out/'q2_strategy_comparison.csv')
metrics=pd.read_csv(out/'prediction_metrics.csv')
sel=pd.read_csv(out/'cvar_parameter_selection.csv')
manifest=json.loads((out/'run_manifest.json').read_text(encoding='utf-8'))
main=manifest.get('main_policy','B4');x=ex[ex.policy==main]
def empirical_tail(values,alpha=.95):
    v=np.sort(np.asarray(values,float))[::-1];mass=(1-alpha)*len(v);whole=int(np.floor(mass));frac=mass-whole
    return float((v[:whole].sum()+(v[whole]*frac if frac>1e-12 else 0))/mass)
emergency_cvar={p:empirical_tail(g.groupby('date').emergency_cost_yuan.sum()) for p,g in ex.groupby('policy')}
comp['daily_emergency_cost_cvar95_yuan']=comp.policy.map(emergency_cvar)
comp.to_csv(out/'q2_strategy_comparison.csv',index=False)

# Recompute out-of-sample metrics from the final executed forecast columns for
# the complete February-December evaluation window.  This is independent of
# the January model-selection table above.
metric_rows=[]
for variable,actual_col,forecast_col in [('load','load_actual_kwh','load_forecast_kwh'),('pv','pv_actual_kwh','pv_forecast_kwh')]:
    z=x[['date',actual_col,forecast_col]].copy()
    z['error_kw']=(z[actual_col]-z[forecast_col])*6.0
    z['abs_error_kw']=z.error_kw.abs(); z['sq_error_kw2']=z.error_kw**2
    metric_rows.append({'variable':variable,'observations':len(z),
                        'mae_kw_all':z.abs_error_kw.mean(),
                        'rmse_kw_all':np.sqrt(z.sq_error_kw2.mean()),
                        'daily_rmse_mean_kw':z.groupby('date').sq_error_kw2.mean().pow(0.5).mean()})
overall=pd.DataFrame(metric_rows)
overall.to_csv(out/'prediction_metrics_main_overall.csv',index=False)
monthly_rows=[]
for (variable,month),z in [(key,g) for key,g in pd.concat([
        x[['date','load_actual_kwh','load_forecast_kwh']].assign(variable='load',actual=lambda d:d.load_actual_kwh,forecast=lambda d:d.load_forecast_kwh),
        x[['date','pv_actual_kwh','pv_forecast_kwh']].assign(variable='pv',actual=lambda d:d.pv_actual_kwh,forecast=lambda d:d.pv_forecast_kwh)
    ]).assign(month=lambda d:d.date.dt.month).groupby(['variable','month'])]:
    e=(z.actual-z.forecast)*6.0
    monthly_rows.append({'variable':variable,'month':int(month),'observations':len(e),
                         'mae_kw':float(e.abs().mean()),'rmse_kw':float(np.sqrt(np.mean(e**2))),
                         'daily_rmse_mean_kw':float(e.groupby(z.date).apply(lambda v:np.sqrt(np.mean(v**2))).mean())})
monthly=pd.DataFrame(monthly_rows).sort_values(['variable','month'])
monthly.to_csv(out/'prediction_metrics_main_monthly.csv',index=False)
keydates=pd.to_datetime(['2025-03-20','2025-06-21','2025-09-23','2025-12-21']);table1=[];table2=[];table3=[]
for d in keydates:
    day=x[x.date==d].sort_values('slot'); plan=plans[(plans.policy==main)&(plans.date==d)].sort_values('slot')
    for hour in [10,12,14,16,18,20]: table1.append({'date':d,'interval':f'{hour}:00-{hour}:10','slot':hour*6+1,'grid_plan_kwh':float(plan.loc[plan.slot==hour*6+1,'grid_plan_kwh'].iloc[0]),'daily_grid_plan_kwh':plan.grid_plan_kwh.sum(),'daily_plan_cost_yuan':day.plan_cost_yuan.sum()})
    for i in range(6): table2.append({'date':d,'interval':f'{i*4}:00-{(i+1)*4}:00','charge_kwh':day.iloc[i*24:(i+1)*24].charge_kwh.sum(),'discharge_kwh':day.iloc[i*24:(i+1)*24].discharge_kwh.sum(),'soc_0000_kwh':day.soc_start_kwh.iloc[0] if i==0 else np.nan,'soc_2400_kwh':day.soc_end_kwh.iloc[-1] if i==1 else np.nan})
    ids=np.flatnonzero(day.emergency_purchase_kwh.to_numpy()>1e-8);groups=np.split(ids,np.where(np.diff(ids)>1)[0]+1) if len(ids) else []
    for g in groups:
        sm=int(g[0])*10;em=(int(g[-1])+1)*10;table3.append({'date':d,'interval':f'{sm//60}:{sm%60:02d}-{(em//60)%24}:{em%60:02d}'+('+1' if em>=1440 else ''),'emergency_purchase_kwh':day.iloc[g].emergency_purchase_kwh.sum()})
pd.DataFrame(table1).to_csv(out/'q2_key_dates_table1.csv',index=False);pd.DataFrame(table2).to_csv(out/'q2_key_dates_table2.csv',index=False);pd.DataFrame(table3).to_csv(out/'q2_key_dates_table3.csv',index=False)
ct='```text\n'+comp.to_string(index=False,float_format=lambda x:f'{x:.3f}')+'\n```';mt='```text\n'+metrics.to_string(index=False,float_format=lambda x:f'{x:.3f}')+'\n```';st='```text\n'+sel.to_string(index=False,float_format=lambda x:f'{x:.3f}')+'\n```';ot='```text\n'+overall.to_string(index=False,float_format=lambda x:f'{x:.3f}')+'\n```';sens=pd.read_csv(out/'scenario_sensitivity_january.csv');snt='```text\n'+sens.to_string(index=False,float_format=lambda x:f'{x:.3f}')+'\n```'
(reports/'q2_analysis.md').write_text(f'''# 问题二：风险感知日前购电与因果执行

## 信息边界

问题二每天使用附件1的固定144点电价，未使用附件4；负荷和光伏预测仅来自附件2中 `date < target_date` 的历史观测，未使用附件3和当日真实光伏生成的 `is_daylight`。同一历史日的负荷-PV完整样本外残差轨迹作为一个场景，保留日内与源荷联合相关性。

## 初始化与算法

1月作为离线SOC初始化：2025-01-01 00:00从6000 kWh开始，不设每日首尾相等；1月费用不计入问题二。三种策略共同以 `{manifest['common_feb1_soc_kwh']:.3f}` kWh进入2月1日，之后分别连续传递实际SOC。B1用验证胜出的点预测做确定性计划；B3为20场景、共享日前G且lambda=0的两阶段随机LP；1月随机模型比较推荐lambda=0的B3。B4是事前另行配置lambda=`{manifest['chosen_lambda']}`的风险偏好策略，并非1月比较选出的lambda。

当前时段假设负荷和PV先被观测，随后控制器在固定G下根据当前SOC、当前偏差和仍合法的日前预测执行充放电；未来真实轨迹不会进入控制。计划费始终按全部G结算，缺口R按5倍电价结算，未消纳总能量记为remaining energy，不冒充纯弃光。

## 预测验证（1月15-31日）

{mt}

最终选用负荷`{manifest['forecast_choice']['load_method']}`、光伏`{manifest['forecast_choice']['pv_method']}`，选择依据为1月全验证集RMSE（MAE为辅助指标）。2-12月最终模型的独立样本外评价如下：

{ot}

## CVaR选参（仅1月22-31日）

{st}

允许lambda=0参与1月比较后，lambda=0同时取得更低的总费用与日总费用CVaR，因此推荐B3作为基线策略。lambda=`{manifest['chosen_lambda']}`的B4仅作为承担额外计划成本、换取较低紧急购电量和日紧急费用CVaR的风险偏好方案。20个等权场景时规划CVaR95为最坏场景费用；10个验证日的经验日费用CVaR95同样等于最大日费用，不能视为稳定尾部分布估计。场景敏感性如下：

{snt}

## 全年真实回测结果

{ct}

B3相较B1提高日前计划支出并降低5倍紧急购电，但本次全年总费用更高；B4进一步降低紧急购电量，却有更高计划费和全年总费用，且回测日总费用CVaR略高于B3。独立复算的真实执行日紧急费用CVaR95为B1={emergency_cvar['B1']:.3f}元、B3={emergency_cvar['B3']:.3f}元、B4={emergency_cvar['B4']:.3f}元，风险对象与规划场景紧急费用CVaR一致，但规划追索可看到完整假设场景，不能当作真实执行费用。lambda=0的B3是1月总费用与日总费用CVaR更低的推荐基线；B4保留为lambda={manifest['chosen_lambda']}的风险偏好方案，不称为综合最优，也不依据2-12月结果事后挑选。

## 局限

只有2025年数据，1月早期可用残差较少，场景生成需要历史回退并允许Bootstrap有放回抽样。反馈控制是可解释的固定G储能策略，而非问题三的滚动购电调整。问题二不对未消纳能量进一步区分光伏弃电与计划购电浪费，因为混合母线能量不可辨识；统一报告为剩余电量。
''',encoding='utf-8')
