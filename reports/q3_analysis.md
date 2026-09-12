# 问题三：分时预报驱动的滚动购电调整

## 信息顺序与结算

每天0:00使用附件3的00:00光伏预报、附件2历史训练的负荷Ridge预测和附件1电价生成不可覆盖的原始计划G0。06:00、12:00和18:00只修改尚未执行时段；决策使用当次及更早发布的预报、当前真实SOC和截至该时点已实现的数据。当前10分钟区间开始前观测负荷与光伏，再执行储能反馈；未来真实轨迹不进入规划。

附件3的整点功率在同一次发布内线性插值到10分钟网格，再除以6转为电量。发布时点的左端功率只取截至该时点已经结束的最后一个10分钟实际时段：06/12/18时分别取当日slot36/72/108，00:00取前一日slot144；2025-01-01没有前一日数据时显式回退到首个整点预报。左锚点与下一整点预报线性衔接，发布后的未来实际光伏不参与。PV场景误差使用各历史场景日当时可得的对应锚点；负荷与PV使用同一历史日的完整联合残差轨迹，所有源日期严格早于目标日。

本轮采用相对00:00原计划的最终交付方案结算：非紧急费用为 `sum(p*F + 0.5*p*abs(F-G0))`，紧急费用为 `sum(5*p*R)`。因此p=1时，100调整到80、120和100的非紧急费用分别为90、130和100；100->140->100最终仍为100。逐次相邻计划收费会得到140，只作为另一种解释的局限，不与主结果混用。

## 策略与1月校准

C0全天固定G且储能保持00:00预报；C1固定G但储能反馈使用后续预报；C2在三个发布点定期重优化G；C3仅在 `NV=J_keep-J_adjust > delta` 时采用候选。J_keep和J_adjust使用同一最新场景集、SOC、剩余时域和风险损失，且J_keep仍可优化储能。两阶段场景追索可见整条假设场景，实际执行器只能逐时获得真实观测，两者不能混称。

阈值只用1月22-31日校准：

```text
 delta_yuan  january_total_cost_yuan  january_daily_total_cvar95_yuan  january_daily_emergency_cvar95_yuan  revision_count  terminal_soc_kwh  selected
          0               658181.129                        84584.543                             3605.109              30          1459.797     False
         50               658160.882                        84584.543                             3605.109              29          1459.797     False
        200               657382.041                        84584.543                             3605.109              27          1459.797     False
        500               655987.061                        84584.543                             3844.564              22          1227.566      True
```

最终delta=500元。10个校准日的经验CVaR95等于最大日值，不视为稳定尾部估计。

## 334天结果

```text
policy  original_plan_cost_yuan  final_non_emergency_cost_yuan  adjustment_net_cost_yuan  emergency_cost_yuan  total_cost_yuan  emergency_purchase_kwh  daily_emergency_cvar95_yuan  daily_total_cvar95_yuan  remaining_energy_kwh  revision_count  min_soc_kwh  max_soc_kwh  year_end_soc_kwh
    C0             13439480.616                   13439480.616                     0.000          2830551.738     16270032.354              770344.497                    36220.290                81566.116           3351837.898               0     1200.000    10800.000          1200.000
    C1             13439828.546                   13439828.546                     0.000          2674812.906     16114641.452              753898.375                    35699.031                82683.341           3333605.925               0     1200.000    10800.000          1200.000
    C2             13419792.858                   14307293.194                887500.336          1525877.713     15833170.907              422826.691                    27107.231                78065.558           3525188.074             993     1200.000    10800.000          1200.000
    C3             13422459.003                   14242412.103                819953.100          1632762.468     15875174.571              444607.507                    27258.027                78215.042           3526877.825             579     1200.000    10800.000          1200.000
```

C1相对C0减少 `155390.902` 元（`0.955%`），表示仅把新预报用于储能反馈已有价值；C2相对C1再减少 `281470.545` 元（`1.747%`），说明允许调整购电计划在本结算解释下有必要。C3相对C2增加 `42003.664` 元，但将修订次数从993次降至579次；C3相对C0仍降低 `394857.782` 元（`2.427%`）。因此若只追求本样本总费用选C2，若重视操作频率和稳健门槛选1月校准的C3。四组均从问题二离线初始化得到的 `4910.116222` kWh进入2月，之后分别传递实际SOC。`remaining_energy_kwh`为未消纳总能量，不全部称为弃光。

按发布时间的调整统计：

```text
policy  issue_hour  decisions  revisions  mean_nv_yuan  candidate_vs_g0_increase_kwh  candidate_vs_g0_decrease_kwh  adopted_change_increase_kwh  adopted_change_decrease_kwh
    C2           6        334        330      2173.810                    597468.793                    457192.477                   597468.793                   457110.960
    C2          12        334        334      1487.591                    447009.227                    213018.870                   505040.130                   221601.278
    C2          18        334        329       584.371                    165129.353                     28079.652                   173231.158                    58941.607
    C3           6        334        233      2173.812                    597468.793                    457195.035                   559645.088                   418651.111
    C3          12        334        198      1457.826                    442892.981                    211601.393                   425341.696                   149142.447
    C3          18        334        148       570.962                    166576.760                     28982.787                   125026.158                    26591.662
```

候选偏差按候选计划相对G0统计；已采纳变更按触发时 `effective_plan_kwh-plan_before_kwh` 统计，未触发候选贡献0。全年最终生效计划相对G0的偏差另列如下：

```text
policy  final_vs_g0_increase_kwh  final_vs_g0_decrease_kwh
    C0                     0.000                     0.000
    C1                     0.000                     0.000
    C2                878698.464                340612.228
    C3                827622.503                311994.781
```

相同目标时段的附件3更新前后预测误差：

```text
 issue_hour  observations  original_mae_kw_all  latest_mae_kw_all  original_rmse_kw_all  latest_rmse_kw_all  original_daily_rmse_mean_kw  latest_daily_rmse_mean_kw
          0         48096              197.491            197.491               383.027             383.027                      351.915                    351.915
          6         36072              259.802            158.516               441.562             271.371                      405.535                    253.484
         12         24048              218.448             75.253               418.346             139.728                      371.480                    132.859
         18         12024               10.623             10.015                46.242              42.923                       30.302                     28.455
```

原始整点预报、旧bfill轨迹和新观测锚点轨迹必须分开解释。正式期分层诊断如下；`supplier_raw_hourly`只在原始整点目标上评价，不与10分钟融合轨迹混称：

```text
                      period  issue_hour         forecast_type                region  observations  mae_kw  rmse_kw
formal_2025-02-01_2025-12-31           0    legacy_10min_bfill all_available_targets         48096 197.491  383.027
formal_2025-02-01_2025-12-31           0 observed_anchor_10min all_available_targets         48096 197.491  383.027
formal_2025-02-01_2025-12-31           0   supplier_raw_hourly all_available_targets          8016 186.735  378.684
formal_2025-02-01_2025-12-31           6    legacy_10min_bfill all_available_targets         36072 185.772  322.930
formal_2025-02-01_2025-12-31           6 observed_anchor_10min all_available_targets         36072 158.516  271.371
formal_2025-02-01_2025-12-31           6   supplier_raw_hourly all_available_targets          6012 129.090  240.922
formal_2025-02-01_2025-12-31          12    legacy_10min_bfill all_available_targets         24048  85.625  170.344
formal_2025-02-01_2025-12-31          12 observed_anchor_10min all_available_targets         24048  75.253  139.728
formal_2025-02-01_2025-12-31          12   supplier_raw_hourly all_available_targets          4008  35.199   71.084
formal_2025-02-01_2025-12-31          18    legacy_10min_bfill all_available_targets         12024  19.425  105.949
formal_2025-02-01_2025-12-31          18 observed_anchor_10min all_available_targets         12024  10.015   42.923
formal_2025-02-01_2025-12-31          18   supplier_raw_hourly all_available_targets          2004   0.000    0.005
```

## 18:00发布消融

固定C3、delta、场景数、随机种子、初始SOC和结算规则后，全年连续比较允许06/12/18更新与仅允许06/12更新：

```text
allowed_updates  total_cost_yuan  emergency_cost_yuan  emergency_purchase_kwh  daily_emergency_cvar95_yuan  daily_total_cvar95_yuan  remaining_energy_kwh  revision_count  year_end_soc_kwh
       06/12/18     15875174.571          1632762.468              444607.507                    27258.027                78215.042           3526877.825             579          1200.000
          06/12     15921554.103          1831415.228              480851.044                    30304.719                80130.565           3492951.458             431          1200.000
```

仅允许06/12时，18:00预报既不进入购电修订，也不进入储能反馈。结果显示保留18:00发布降低了真实总费用、紧急费用及两类实际日CVaR，但增加了修订次数，因此其他发布时间预报具有可量化价值，同时存在运行复杂度代价。

逐次相邻计划收费解释的敏感性另存于 `outputs/q3/q3_settlement_interpretation_sensitivity.csv`。该表只是“固定既有政策轨迹的重新计价”，没有在另一结算规则下重新优化，因此不能用于宣称另一规则下策略仍最优。固定轨迹重计价总费用为 C1=16114641.452 元、C2=16131051.155 元、C3=16087017.325 元。

## 局限

场景库仅覆盖一个自然年，早期历史样本少并允许有放回抽样。10个等权场景且alpha=0.95时，规划紧急费用CVaR等于最坏场景费用，不能解释成稳定尾部估计。调整收费按最终计划相对原始计划结算；若权威补充说明要求逐次修订收费，频繁调整策略的费用会更高。NV是预测的风险调整目标改善值，不等于事后实际节费或严格EVSI。受限价格信息、另一结算机制下重新优化与跨日终端价值属于后续扩展。
