from pathlib import Path
import sys, pandas as pd
sys.path.insert(0, str(Path(__file__).parents[1] / 'src'))
try: import matplotlib.pyplot as plt
except ImportError: print('matplotlib unavailable; EDA skipped'); raise SystemExit(0)
ROOT=Path(__file__).parents[1]; p=ROOT/'data/processed/actual_10min.parquet'; df=pd.read_parquet(p) if p.exists() else pd.read_csv(ROOT/'data/processed/actual_10min.csv'); figdir=ROOT/'reports/figures/eda'; figdir.mkdir(parents=True,exist_ok=True)
for col,title,unit in [('load_kw','全年负荷热图','kW'),('pv_actual_kw','全年光伏热图','kW'),('price_yuan_per_kwh','全年电价热图','元/kWh')]:
    pivot=df.pivot(index='date',columns='slot',values=col); plt.figure(figsize=(14,8)); plt.imshow(pivot.values,aspect='auto'); plt.colorbar(label=unit); plt.title(title); plt.xlabel('slot'); plt.ylabel('date'); plt.tight_layout(); plt.savefig(figdir/(col+'_heatmap.png'),dpi=300); plt.close()
for col in ['load_kw','pv_actual_kw','price_yuan_per_kwh']:
    g=df.groupby(['month','slot'])[col].mean().unstack(0); ax=g.plot(figsize=(12,6)); ax.set_title(f'每月平均{col}日曲线'); ax.set_xlabel('slot'); ax.set_ylabel(col); plt.tight_layout(); plt.savefig(figdir/(col+'_monthly_profile.png'),dpi=300); plt.close()
daily=df.groupby('date').agg(load_kwh=('load_kwh','sum'),pv_kwh=('pv_actual_kwh','sum'))
for col in daily:
    ax=daily[col].plot(figsize=(12,4)); ax.set_ylabel(col); ax.set_title('每日总量'); plt.tight_layout(); plt.savefig(figdir/(col+'_daily.png'),dpi=300); plt.close()
ax=df.plot.scatter('load_kw','price_yuan_per_kwh',s=2,alpha=.2,figsize=(7,5)); ax.set_title('负荷-电价'); plt.tight_layout(); plt.savefig(figdir/'load_price_scatter.png',dpi=300); plt.close()
season=df.assign(season=df.date.dt.month.map({12:'冬',1:'冬',2:'冬',3:'春',4:'春',5:'春',6:'夏',7:'夏',8:'夏',9:'秋',10:'秋',11:'秋'})).groupby(['season','slot'])[['load_kw','pv_actual_kw']].mean()
for col in ['load_kw','pv_actual_kw']:
    season[col].unstack(0).plot(figsize=(12,5)); plt.title('四季典型日 '+col); plt.tight_layout(); plt.savefig(figdir/(col+'_seasonal.png'),dpi=300); plt.close()
print('EDA figures written to',figdir)
