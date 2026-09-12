# 题目、假设、代码与结果对应核查

基线提交：`67467ab313198c57c554b23f83698bc547e3ba7b`。本轮原始附件未修改；正式期为2025-02-01至2025-12-31，共334天、每天144个10分钟时段。

| 题目要求或数据说明 | 本项目解释/附加假设 | 主要代码 | 正式结果 |
|---|---|---|---|
| Q1要求0:00与24:00储能量相等 | 仅Q1施加日首尾相等 | `deterministic_dispatch.py`、`03_solve_q1.py` | `outputs/q1/result1.xlsx` |
| Q2利用附件2历史预测，附件1电价每日重复 | Q2不用附件3/4，SOC跨日连续 | `prediction.py`、`04_run_q2.py` | `outputs/q2/result2.xlsx` |
| Q3在00/06/12/18发布附件3未来24小时整点PV预报 | 发布时点左端用刚结束的合法观测；Q3采用final_vs_original结算 | `io.py::build_10min_pv_forecast`、`q3.py` | `outputs/q3/result3.xlsx` |
| Q3减少/增加购电分别按50%违约成本/1.5倍价格处理 | 当前解释为最终F相对原始G0：`pF+0.5p|F-G0|`，不是逐次修订收费 | `q3.py::settlement_components` | `q3_execution_detail.csv` |
| Q4电价随时间变化 | 题面未说明公布时刻；额外假设当天144点价格00:00已知 | `q4.py`、`16_run_q4_3.py` | `outputs/q4/result4-3.xlsx` |

所有Q2-Q4策略均从共同的分支初态出发，之后独立传递实际SOC，不施加每日首尾相等。哈希记录：

```text
                     path                                                           sha256
        data/raw/附件1.xlsx 66B87134F5ECCCD68184D3539BB1293EF039F9E0FDD955A589B9BFA7F227C377
        data/raw/附件2.xlsx 2E95FD446BFAFA0D8C59577B5C2E2EA8B3F1DEF20DDE54A3062556F4DA9B4C72
        data/raw/附件3.xlsx 8A61B06C52BD0D639A1CC37C61A7D9F5B75EDCBCA718F64C1BD3498EC9F9D843
        data/raw/附件4.xlsx 20E9C93AEAB5E8E21AE4DD15587F9E190F7408692504C1319598461CD654FE71
  outputs/q1/result1.xlsx 60BCB1F31131EB51977F1A4D0C9230180439A90646CFE19BF28A9E12ECCC3FD3
  outputs/q2/result2.xlsx 44CD3BFF98B9F442932C1154B65DFC898EB0A5827CE0A40A6C6E903B917642CE
  outputs/q3/result3.xlsx 987E612DC8973325824687F516C7C5143C507CE03EA4B03B2DE57AE82445A5F9
outputs/q4/result4-2.xlsx A833E82D86B6CA4E88112A2F1A076E5C7134C3EB49DA7DAF79AAAFAEFBAAF08F
outputs/q4/result4-3.xlsx 502D636C2F91B87813880A29B94D6115935B6FB0315570EE5ED26764F2972E49
```
