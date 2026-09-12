# 附件3首小时边界修订证据

旧方法在发布后首个原始整点之前使用下一整点值bfill。新方法保持所有原始整点值不变，并以截至发布时点已经结束的最后一个10分钟观测作为左端点：06/12/18对应当日slot36/72/108，00:00对应前一日slot144；2025-01-01无前日数据时明确回退到首个整点预报。发布后真实值不会进入锚点。

`supplier_raw_hourly`只在附件3原始整点上评价；`legacy_10min_bfill`和`observed_anchor_10min`才是10分钟决策输入，三者不能混称。总体结果：

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
january_calibration_2025-01-22_2025-01-31           0    legacy_10min_bfill all_available_targets          1440 140.608  272.998
january_calibration_2025-01-22_2025-01-31           0 observed_anchor_10min all_available_targets          1440 140.608  272.998
january_calibration_2025-01-22_2025-01-31           0   supplier_raw_hourly all_available_targets           240 132.186  276.608
january_calibration_2025-01-22_2025-01-31           6    legacy_10min_bfill all_available_targets          1080 127.779  212.501
january_calibration_2025-01-22_2025-01-31           6 observed_anchor_10min all_available_targets          1080 122.009  207.664
january_calibration_2025-01-22_2025-01-31           6   supplier_raw_hourly all_available_targets           180  99.114  182.646
january_calibration_2025-01-22_2025-01-31          12    legacy_10min_bfill all_available_targets           720  65.732  132.005
january_calibration_2025-01-22_2025-01-31          12 observed_anchor_10min all_available_targets           720  56.433  105.695
january_calibration_2025-01-22_2025-01-31          12   supplier_raw_hourly all_available_targets           120  25.910   58.671
january_calibration_2025-01-22_2025-01-31          18    legacy_10min_bfill all_available_targets           360   0.007    0.043
january_calibration_2025-01-22_2025-01-31          18 observed_anchor_10min all_available_targets           360   0.007    0.043
january_calibration_2025-01-22_2025-01-31          18   supplier_raw_hourly all_available_targets            60   0.000    0.000
```

策略前后变化直接以基线提交CSV和本轮正式CSV计算：

```text
branch policy  total_cost_yuan_before  total_cost_yuan_after  total_cost_yuan_change  emergency_cost_yuan_before  emergency_cost_yuan_after  emergency_cost_yuan_change  emergency_purchase_kwh_before  emergency_purchase_kwh_after  emergency_purchase_kwh_change  daily_emergency_cvar95_yuan_before  daily_emergency_cvar95_yuan_after  daily_emergency_cvar95_yuan_change  daily_total_cvar95_yuan_before  daily_total_cvar95_yuan_after  daily_total_cvar95_yuan_change  remaining_energy_kwh_before  remaining_energy_kwh_after  remaining_energy_kwh_change  revision_count_before  revision_count_after  revision_count_change
    Q3     C0            16270032.354           16270032.354                   0.000                 2830551.738                2830551.738                       0.000                     770344.497                    770344.497                          0.000                           36220.290                          36220.290                               0.000                       81566.116                      81566.116                           0.000                  3351837.898                 3351837.898                        0.000                      0                     0                      0
    Q3     C1            16112364.753           16114641.452                2276.699                 2673112.702                2674812.906                    1700.204                     753087.935                    753898.375                        810.440                           35695.690                          35699.031                               3.342                       82683.136                      82683.341                           0.205                  3331382.504                 3333605.925                     2223.421                      0                     0                      0
    Q3     C2            15840890.554           15833170.907               -7719.647                 1513963.161                1525877.713                   11914.551                     419502.978                    422826.691                       3323.713                           26607.723                          27107.231                             499.508                       77780.147                      78065.558                         285.411                  3527038.269                 3525188.074                    -1850.195                    989                   993                      4
    Q3     C3            15858487.856           15875174.571               16686.715                 1584725.944                1632762.468                   48036.524                     435380.777                    444607.507                       9226.730                           26704.499                          27258.027                             553.527                       77824.740                      78215.042                         390.302                  3525918.223                 3526877.825                      959.602                    608                   579                    -29
  Q4-3     C0            16992916.319           16992916.319                   0.000                 2938383.181                2938383.181                       0.000                     778537.428                    778537.428                          0.000                           39556.866                          39556.866                               0.000                       95409.436                      95409.436                           0.000                  3377539.047                 3377539.047                       -0.000                      0                     0                      0
  Q4-3     C1            16870245.217           16864891.718               -5353.499                 2815886.699                2810168.117                   -5718.583                     765081.266                    764117.113                       -964.153                           38773.637                          38778.144                               4.507                       95488.403                      95488.475                           0.072                  3359858.773                 3359920.294                       61.522                      0                     0                      0
  Q4-3     C2            16567348.530           16562714.087               -4634.443                 1541340.387                1554419.825                   13079.438                     420287.091                    423049.962                       2762.871                           29584.859                          30191.736                             606.876                       90993.139                      91174.720                         181.582                  3592501.538                 3588000.237                    -4501.300                    989                   991                      2
  Q4-3     C3            16579981.623           16595939.974               15958.351                 1592049.924                1633939.559                   41889.634                     432562.178                    440955.772                       8393.594                           29716.269                          30367.510                             651.241                       91099.282                      91322.685                         223.403                  3587845.194                 3588979.417                     1134.223                    631                   597                    -34
```
