from pathlib import Path
from hashlib import sha256
from copy import copy
import sys,json,time,shutil
import numpy as np,pandas as pd
sys.path.insert(0,str(Path(__file__).parents[1]/'src'))
from microgrid.config import load_config
from microgrid.io import read_processed,get_q2_daily_price
from microgrid.prediction import rolling_prediction_evaluation,build_oos_forecasts,forecast_day
from microgrid.scenarios import generate_joint_scenarios
from microgrid.models.deterministic_dispatch import solve_deterministic_dispatch
from microgrid.models.stochastic_dispatch import solve_two_stage_dispatch,empirical_cvar
from microgrid.execution import execute_fixed_grid_plan

ROOT=Path(__file__).parents[1]; raw=ROOT/'data/raw'; out=ROOT/'outputs/q2'; reports=ROOT/'reports'; figs=reports/'figures/q2';out.mkdir(parents=True,exist_ok=True);figs.mkdir(parents=True,exist_ok=True)
cfg=load_config(); b=cfg['battery']; q2=cfg['q2']; price=get_q2_daily_price(raw).price_yuan_per_kwh.to_numpy(); actual=read_processed(ROOT/'data/processed/actual_10min.parquet')
signature=sha256(b''.join(p.read_bytes() for p in [Path(__file__),ROOT/'src/microgrid/models/stochastic_dispatch.py',ROOT/'src/microgrid/execution.py',ROOT/'src/microgrid/prediction.py',ROOT/'configs/config.yaml',raw/'附件1.xlsx',raw/'附件2.xlsx'])).hexdigest(); cache=out/'cache'/signature[:16];cache.mkdir(parents=True,exist_ok=True)
started=time.time(); detail_eval,metrics,choice=rolling_prediction_evaluation(actual,q2['prediction_validation_start'],q2['prediction_validation_end']);detail_eval.to_csv(out/'prediction_validation_detail.csv',index=False);metrics.to_csv(out/'prediction_metrics.csv',index=False)
forecast_path=cache/f'oos_forecasts_{choice.load_method}_{choice.pv_method}.csv'
if forecast_path.exists(): oos=pd.read_csv(forecast_path,parse_dates=['date'])
else:
    oos=build_oos_forecasts(actual,pd.date_range('2025-01-08','2025-12-31'),choice);oos.to_csv(forecast_path,index=False)

def day_actual(d):
    x=actual[actual.date==pd.Timestamp(d)].sort_values('slot');return x.load_kwh.to_numpy(),x.pv_actual_kwh.to_numpy()
def point_for(d): return oos[oos.date==pd.Timestamp(d)].sort_values('slot').reset_index(drop=True)

# Offline January initialization, excluded from Q2 evaluation.
warm=[];soc=b['initial_soc_kwh']
for d in pd.date_range('2025-01-01','2025-01-31'):
    la,pa=day_actual(d)
    if d==pd.Timestamp('2025-01-01'): lp,pp=la,pa
    else:
        p=forecast_day(actual,d,'d1','d1');lp,pp=p.load_pred_kwh.to_numpy(),p.pv_pred_kwh.to_numpy()
    plan=solve_deterministic_dispatch(lp,pp,price,soc,None,b)
    ex=execute_fixed_grid_plan(d,plan.grid_purchase_kwh,la,pa,lp,pp,price,soc,b,'warmup');warm.append(ex);soc=float(ex.soc_end_kwh.iloc[-1])
warm=pd.concat(warm,ignore_index=True);warm.to_csv(out/'january_initialization.csv',index=False);common_initial_soc=soc

# Choose lambda using January 22-31 only; all scenario sources precede each target day.
selection=[]
for lam in (0.0,0.05,0.1,0.2,0.5):
    s=float(warm[warm.date==pd.Timestamp('2025-01-21')].soc_end_kwh.iloc[-1]); daily=[]
    for d in pd.date_range('2025-01-22','2025-01-31'):
        p=point_for(d);sc=generate_joint_scenarios(actual,oos,p,d,q2['scenario_count'],cfg['random_seed']);arr=sc.pivot(index='scenario',columns='slot',values='load_kwh').to_numpy();pv=sc.pivot(index='scenario',columns='slot',values='pv_kwh').to_numpy();weights=sc.groupby('scenario').weight.first().to_numpy();plan=solve_two_stage_dispatch(arr,pv,price,weights,s,b,q2['cvar_alpha'],lam);la,pa=day_actual(d);ex=execute_fixed_grid_plan(d,plan.grid_purchase_kwh,la,pa,p.load_pred_kwh,p.pv_pred_kwh,price,s,b,f'lambda_{lam}');s=float(ex.soc_end_kwh.iloc[-1]);daily.append(float((ex.plan_cost_yuan+ex.emergency_cost_yuan).sum()))
    selection.append({'lambda':lam,'january_total_cost_yuan':sum(daily),'january_daily_cvar95_yuan':empirical_cvar(daily,np.ones(len(daily))/len(daily),.95)})
selection=pd.DataFrame(selection);recommended_lambda=float(selection.sort_values(['january_total_cost_yuan','january_daily_cvar95_yuan']).iloc[0]['lambda']);chosen_lambda=float(q2['cvar_lambda']);selection['recommended']=selection['lambda'].eq(recommended_lambda);selection['risk_preference']=selection['lambda'].eq(chosen_lambda);selection.to_csv(out/'cvar_parameter_selection.csv',index=False)

all_exec=[];plans=[];scenario_log=[];planning_log=[];socs={p:common_initial_soc for p in ('B1','B3','B4')}
for day_no,d in enumerate(pd.date_range('2025-02-01','2025-12-31'),start=1):
    point=point_for(d);la,pa=day_actual(d);sc=generate_joint_scenarios(actual,oos,point,d,q2['scenario_count'],cfg['random_seed']);scenario_log.append(sc[['scenario','source_date','weight','training_cutoff']].drop_duplicates().assign(target_date=d));load_sc=sc.pivot(index='scenario',columns='slot',values='load_kwh').to_numpy();pv_sc=sc.pivot(index='scenario',columns='slot',values='pv_kwh').to_numpy();weights=sc.groupby('scenario').weight.first().to_numpy()
    dplans={}; det=solve_deterministic_dispatch(point.load_pred_kwh,point.pv_pred_kwh,price,socs['B1'],None,b);dplans['B1']=(det.grid_purchase_kwh,np.nan,np.nan,0)
    for policy,lam in [('B3',0.),('B4',chosen_lambda)]:
        st=solve_two_stage_dispatch(load_sc,pv_sc,price,weights,socs[policy],b,q2['cvar_alpha'],lam);dplans[policy]=(st.grid_purchase_kwh,st.expected_emergency_cost_yuan,st.cvar_yuan,st.max_equality_residual)
    for policy,(g,expected,cvar,resid) in dplans.items():
        ex=execute_fixed_grid_plan(d,g,la,pa,point.load_pred_kwh.to_numpy(),point.pv_pred_kwh.to_numpy(),price,socs[policy],b,policy);all_exec.append(ex);socs[policy]=float(ex.soc_end_kwh.iloc[-1]);plans.append(pd.DataFrame({'date':d,'slot':np.arange(1,145),'policy':policy,'grid_plan_kwh':g}));planning_log.append({'date':d,'policy':policy,'initial_soc_kwh':float(ex.soc_start_kwh.iloc[0]),'terminal_soc_kwh':socs[policy],'expected_scenario_emergency_cost_yuan':expected,'scenario_cvar_yuan':cvar,'max_planning_residual':resid})
    if day_no%10==0 or day_no==334: print(f'{day_no}/334 elapsed={time.time()-started:.1f}s',flush=True)

execution=pd.concat(all_exec,ignore_index=True);plans=pd.concat(plans,ignore_index=True);scenario_log=pd.concat(scenario_log,ignore_index=True);planning_log=pd.DataFrame(planning_log)
execution['total_cost_yuan']=execution.plan_cost_yuan+execution.emergency_cost_yuan;execution.to_csv(out/'q2_execution_detail.csv',index=False);plans.to_csv(out/'q2_day_ahead_plans.csv',index=False);scenario_log.to_csv(out/'scenario_sources.csv',index=False);planning_log.to_csv(out/'planning_diagnostics.csv',index=False)
daily=execution.groupby(['policy','date']).agg(plan_cost_yuan=('plan_cost_yuan','sum'),emergency_cost_yuan=('emergency_cost_yuan','sum'),total_cost_yuan=('total_cost_yuan','sum'),emergency_purchase_kwh=('emergency_purchase_kwh','sum'),remaining_energy_kwh=('remaining_energy_kwh','sum'),charge_kwh=('charge_kwh','sum'),discharge_kwh=('discharge_kwh','sum'),soc_min_kwh=('soc_end_kwh','min'),soc_max_kwh=('soc_end_kwh','max'),terminal_soc_kwh=('soc_end_kwh','last'),max_balance_error=('balance_error_kwh',lambda x:abs(x).max())).reset_index();daily.to_csv(out/'q2_daily_summary.csv',index=False)
comparisons=[]
for policy,g in daily.groupby('policy'):
    comparisons.append({'policy':policy,'plan_cost_yuan':g.plan_cost_yuan.sum(),'emergency_cost_yuan':g.emergency_cost_yuan.sum(),'total_cost_yuan':g.total_cost_yuan.sum(),'emergency_purchase_kwh':g.emergency_purchase_kwh.sum(),'emergency_days':int((g.emergency_purchase_kwh>1e-8).sum()),'daily_cost_std_yuan':g.total_cost_yuan.std(),'daily_cost_cvar95_yuan':empirical_cvar(g.total_cost_yuan,np.ones(len(g))/len(g),.95),'remaining_energy_kwh':g.remaining_energy_kwh.sum(),'charge_kwh':g.charge_kwh.sum(),'discharge_kwh':g.discharge_kwh.sum(),'min_soc_kwh':g.soc_min_kwh.min(),'max_soc_kwh':g.soc_max_kwh.max(),'year_end_soc_kwh':g.terminal_soc_kwh.iloc[-1]})
comparison=pd.DataFrame(comparisons);comparison.to_csv(out/'q2_strategy_comparison.csv',index=False)

# Official result2: only the configured main policy, with all 334 days.
main=q2['main_policy'];mexec=execution[execution.policy==main];mplan=plans[plans.policy==main];from openpyxl import load_workbook
shutil.copy2(raw/'templates/result2.xlsx',out/'result2.xlsx');wb=load_workbook(out/'result2.xlsx');ws=wb['计划购电量'];headers=[ws.cell(1,c).value for c in range(2,146)];slotcols={((int(str(v).split(':')[0])*60+int(str(v).split(':')[1].split('-')[0]))//10+1):c for c,v in enumerate(headers,start=2)}
for row,d in enumerate(pd.date_range('2025-02-01','2025-12-31'),start=2):
    x=mplan[mplan.date==d].set_index('slot').grid_plan_kwh
    for slot,col in slotcols.items(): ws.cell(row,col,float(x.loc[slot]))
    ws.cell(row,146,float(x.sum()));ws.cell(row,147,float(np.dot(x.sort_index(),price)))
ws2=wb['充放电量'];template_styles=[[copy(ws2.cell(r,c)._style) for c in range(1,7)] for r in range(2,8)];ws2.delete_rows(2,ws2.max_row-1)
for di,d in enumerate(pd.date_range('2025-02-01','2025-12-31')):
    x=mexec[mexec.date==d].sort_values('slot');start=2+di*6
    for j in range(6):
        rr=start+j
        for c in range(1,7): ws2.cell(rr,c)._style=copy(template_styles[j][c-1])
        ws2.cell(rr,1,d.to_pydatetime() if j==0 else None);ws2.cell(rr,2,f'{j*4}:00-{(j+1)*4}:00');ws2.cell(rr,3,float(x.iloc[j*24:(j+1)*24].charge_kwh.sum()));ws2.cell(rr,4,float(x.iloc[j*24:(j+1)*24].discharge_kwh.sum()))
    ws2.cell(start,5,'0:00');ws2.cell(start,6,float(x.soc_start_kwh.iloc[0]));ws2.cell(start+1,5,'24:00');ws2.cell(start+1,6,float(x.soc_end_kwh.iloc[-1]))
ws3=wb['紧急购电量'];styles=[copy(ws3.cell(2,c)._style) for c in range(1,4)];ws3.delete_rows(2,ws3.max_row-1);erow=2
for d,x in mexec.groupby('date'):
    active=x.emergency_purchase_kwh.to_numpy()>1e-8;idx=np.flatnonzero(active);groups=np.split(idx,np.where(np.diff(idx)>1)[0]+1) if len(idx) else []
    for gi,ids in enumerate(groups):
        for c in range(1,4): ws3.cell(erow,c)._style=copy(styles[c-1])
        start_slot=int(ids[0])+1;end_slot=int(ids[-1])+1;sm=(start_slot-1)*10;em=end_slot*10;label=f'{sm//60}:{sm%60:02d}-{(em//60)%24}:{em%60:02d}'+('+1' if em>=1440 else '');ws3.cell(erow,1,pd.Timestamp(d).to_pydatetime() if gi==0 else None);ws3.cell(erow,2,label);ws3.cell(erow,3,float(x.iloc[ids].emergency_purchase_kwh.sum()));erow+=1
wb.save(out/'result2.xlsx')

keydates=pd.to_datetime(['2025-03-20','2025-06-21','2025-09-23','2025-12-21']);mexec[mexec.date.isin(keydates)].to_csv(out/'q2_key_dates_tables.csv',index=False)
import matplotlib.pyplot as plt
daily.pivot(index='date',columns='policy',values='total_cost_yuan').cumsum().plot(figsize=(12,5));plt.ylabel('Cumulative cost (yuan)');plt.tight_layout();plt.savefig(figs/'q2_cumulative_cost.png',dpi=300);plt.close()
monthly=mexec.assign(month=mexec.date.dt.month).groupby('month').emergency_purchase_kwh.sum();monthly.plot.bar(figsize=(10,4));plt.ylabel('Emergency purchase (kWh)');plt.tight_layout();plt.savefig(figs/'q2_monthly_emergency.png',dpi=300);plt.close()
for d in keydates:
    x=mexec[mexec.date==d];plt.figure(figsize=(12,5));plt.plot(x.slot,x.load_actual_kwh,label='Load');plt.plot(x.slot,x.pv_actual_kwh,label='PV');plt.plot(x.slot,x.grid_purchase_kwh,label='Plan G');plt.plot(x.slot,x.emergency_purchase_kwh,label='Emergency R');plt.legend();plt.ylabel('kWh / 10 min');plt.tight_layout();plt.savefig(figs/f'q2_typical_{d.date()}.png',dpi=300);plt.close()
report=f'''# 问题二分析\n\n问题二严格使用附件1的固定144点电价；附件4未接入。负荷和光伏预测仅使用附件2中目标日前观测。1月为离线SOC初始化，2025-01-01从6000 kWh开始连续执行，费用不计入问题二；三种策略共同以{common_initial_soc:.6f} kWh进入2月1日。预测验证选择负荷`{choice.load_method}`、光伏`{choice.pv_method}`。B3为20条联合历史残差轨迹、lambda=0的两阶段随机LP；1月随机模型lambda比较推荐lambda={recommended_lambda:g}。B4是在相同模型上另行配置alpha={q2['cvar_alpha']}、lambda={chosen_lambda:g}的风险偏好政策，该lambda表不能用于证明B3优于B1。\n\n执行时假设本时段负荷和PV在储能控制前已观测；日前G固定，反馈控制只使用当前SOC、当前观测和日前预测的未来部分，先做物理可行充放电，再结算不足为5倍电价紧急购电，剩余统一记为`remaining_energy_kwh`而非全称弃光。每日无终端SOC约束，实际SOC跨日连续传递。\n\n正式比较见`outputs/q2/q2_strategy_comparison.csv`。场景规划CVaR与回测日总费用CVaR分列记录，不混用。局限：仅有2025年数据，1月早期预测历史短；残差Bootstrap在早期使用全历史回退并允许有放回抽样。\n''';(reports/'q2_analysis.md').write_text(report,encoding='utf-8')
manifest={'signature':signature,'runtime_seconds':time.time()-started,'python':sys.executable,'root':str(ROOT.resolve()),'forecast_choice':choice.__dict__,'recommended_lambda':recommended_lambda,'chosen_lambda':chosen_lambda,'main_policy':main,'recommended_policy':q2['recommended_policy'],'risk_preference_policy':q2['risk_preference_policy'],'common_feb1_soc_kwh':common_initial_soc,'rows':len(execution)};(out/'run_manifest.json').write_text(json.dumps(manifest,ensure_ascii=False,indent=2),encoding='utf-8');print(comparison.to_string(index=False));print(json.dumps(manifest,ensure_ascii=False,indent=2))
