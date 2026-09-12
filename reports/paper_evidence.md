# 论文可用证据汇总

## 模型与信息集

10分钟能量平衡为 `G_t+R_t+PV_t+D_t=L_t+C_t+W_t`，SOC递推为 `S_t=S_(t-1)+0.9C_t-D_t/0.9`，并满足1200至10800 kWh及充放电各不超过5000/6 kWh。Q3原计划G0在00:00形成，后续只调整未执行段；实际控制仅用当前观测与当时合法预测。

Q3非紧急结算采用 `sum[p_t F_t+0.5 p_t |F_t-G0_t|]`，紧急费用为 `sum[5p_tR_t]`。事件触发值为 `NV=J_keep-J_adjust`，C2阈值0，C3阈值delta只由1月22-31日冻结。

## 校准与正式结果

Q3校准：

```text
 delta_yuan  january_total_cost_yuan  january_daily_total_cvar95_yuan  january_daily_emergency_cvar95_yuan  revision_count  terminal_soc_kwh  selected
          0               658181.129                        84584.543                             3605.109              30          1459.797     False
         50               658160.882                        84584.543                             3605.109              29          1459.797     False
        200               657382.041                        84584.543                             3605.109              27          1459.797     False
        500               655987.061                        84584.543                             3844.564              22          1227.566      True
```

Q4-3校准：

```text
 delta_yuan  january_total_cost_yuan  january_daily_total_cvar95_yuan  january_daily_emergency_cvar95_yuan  revision_count  terminal_soc_kwh  selected
          0               740948.242                       101352.145                             4839.056              30          1337.079     False
         50               740948.242                       101352.145                             4839.056              30          1337.079     False
        200               740361.443                       101352.145                             4839.056              27          1337.079     False
        500               738885.095                       101352.145                             5320.967              21          1337.079      True
```

Q3正式结果：

```text
policy  original_plan_cost_yuan  final_non_emergency_cost_yuan  adjustment_net_cost_yuan  emergency_cost_yuan  total_cost_yuan  emergency_purchase_kwh  daily_emergency_cvar95_yuan  daily_total_cvar95_yuan  remaining_energy_kwh  revision_count  min_soc_kwh  max_soc_kwh  year_end_soc_kwh
    C0             13439480.616                   13439480.616                     0.000          2830551.738     16270032.354              770344.497                    36220.290                81566.116           3351837.898               0     1200.000    10800.000          1200.000
    C1             13439828.546                   13439828.546                     0.000          2674812.906     16114641.452              753898.375                    35699.031                82683.341           3333605.925               0     1200.000    10800.000          1200.000
    C2             13419792.858                   14307293.194                887500.336          1525877.713     15833170.907              422826.691                    27107.231                78065.558           3525188.074             993     1200.000    10800.000          1200.000
    C3             13422459.003                   14242412.103                819953.100          1632762.468     15875174.571              444607.507                    27258.027                78215.042           3526877.825             579     1200.000    10800.000          1200.000
```

Q4-3正式结果：

```text
branch policy  plan_cost_yuan  non_emergency_cost_yuan  emergency_cost_yuan  total_cost_yuan  emergency_purchase_kwh  emergency_days  daily_cost_std_yuan  daily_emergency_cvar95_yuan  daily_total_cvar95_yuan  remaining_energy_kwh  charge_kwh  discharge_kwh  revision_count  min_soc_kwh  max_soc_kwh  year_end_soc_kwh
  Q4-3     C0    14054533.139             14054533.139          2938383.181     16992916.319              778537.428             332            22207.927                    39556.866                95409.436           3377539.047 6172539.461    5002196.952               0     1200.000    10800.000          1200.000
  Q4-3     C1    14054723.601             14054723.601          2810168.117     16864891.718              764117.113             333            22354.807                    38778.144                95488.475           3359920.294 6192304.368    5018206.526               0     1200.000    10800.000          1200.000
  Q4-3     C2    14045410.799             15008294.262          1554419.825     16562714.087              423049.962             332            21742.454                    30191.736                91174.720           3588000.237 6035722.227    4891374.992             991     1200.000    10800.000          1200.000
  Q4-3     C3    14045669.958             14962000.415          1633939.559     16595939.974              440955.772             332            21709.260                    30367.510                91322.685           3588979.417 6049737.699    4902727.525             597     1200.000    10800.000          1200.000
```

## 其他发布时间是否必要

固定新C3、delta、场景设置、共同初态和结算，18:00发布消融结果如下：

```text
allowed_updates  total_cost_yuan  emergency_cost_yuan  emergency_purchase_kwh  daily_emergency_cvar95_yuan  daily_total_cvar95_yuan  remaining_energy_kwh  revision_count  year_end_soc_kwh
       06/12/18     15875174.571          1632762.468              444607.507                    27258.027                78215.042           3526877.825             579          1200.000
          06/12     15921554.103          1831415.228              480851.044                    30304.719                80130.565           3492951.458             431          1200.000
```

保留18:00更新降低了真实总费用、紧急购电费用、紧急电量和两类实际日CVaR，但增加修订次数。故06/12之外的18:00预报具有真实经济与风险价值，是否采用仍取决于对操作频率的管理偏好。

## 局限与后续

只有一个自然年的历史，早期场景池需有放回抽样；左锚点把刚结束区间平均功率作为发布时点功率估计；Q4全天价格00:00已知是附加假设；final_vs_original结算尚无权威补充说明。受限价格信息、另一结算机制下重新优化和跨日终端价值应作为后续扩展，不混入本轮正式结果。
