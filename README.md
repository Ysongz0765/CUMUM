# CUMCM 2026 C 题微网调度工程

本工程完成 Excel 审计、时间对齐、问题一确定性 LP、问题二两阶段随机规划与因果回测、问题三基于附件3四次发布预报的滚动购电调整，以及问题四在附件4逐日波动电价下对问题二、三的完整重算。原始文件在 `data/raw`，处理数据在 `data/processed`，正式结果在 `outputs/q1` 至 `outputs/q4`。

PowerShell:
```powershell
$py = "C:\Users\dell\.cache\codex-runtimes\codex-primary-runtime\dependencies\python\python.exe"
& $py scripts/00_audit_raw_data.py
& $py scripts/01_build_processed_data.py
& $py scripts/02_run_eda.py
& $py scripts/03_solve_q1.py
& $py scripts/04_run_q2.py
& $py scripts/06_build_reports.py
& $py scripts/05_validate_q1_q2.py
& $py -m pytest -q
& $py scripts/07_package_verified.py
& $py scripts/09_run_q3.py
& $py scripts/12_export_q3.py
& $py scripts/11_build_q3_report.py
& $py scripts/10_validate_q3.py
& $py -m pytest -q
& $py scripts/15_run_q4_2.py
& $py scripts/16_run_q4_3.py
& $py scripts/17_build_q4_report.py
& $py scripts/18_validate_q4.py
& $py scripts/19_q4_repro_check.py
& $py scripts/20_forecast_boundary_diagnostics.py
& $py scripts/21_run_q3_18h_ablation.py
& $py scripts/22_planning_execution_diagnostics.py
& $py scripts/23_q3_q4_3_repro_check.py
& $py scripts/24_build_revision_reports.py
& $py -m pytest -q
```

如需单独复核问题二场景数与随机种子敏感性，可运行：

```powershell
& $py scripts/08_q2_sensitivity.py
```

`07_package_verified.py` 会重新生成项目压缩包，将其解压到临时目录，核对关键文件 SHA256，并在解压副本中运行验收脚本和测试。问题二正式执行明细为 `outputs/q2/q2_execution_detail.csv`（3 策略共 144288 行），官方表为 `outputs/q2/result2.xlsx`；问题一官方表为 `outputs/q1/result1.xlsx`。

问题三主结算按最终生效计划相对 00:00 原计划计费：`p*F + 0.5*p*abs(F-G0)`，另加 `5*p*R` 紧急购电费。C0/C1 固定购电计划，C2 定期调整，C3 按 1 月选出的 NV 阈值触发调整。问题三只使用附件1电价、附件2实际与附件3光伏预报；所有场景源日期早于目标日。附件3的首小时边界使用发布时点前刚结束的实际光伏时段作为左锚点，与下一整点预报线性衔接；00:00使用前一日slot144，缺少前日数据时显式回退。旧bfill仅保留用于诊断对照。

Q3的18:00发布消融由 `21_run_q3_18h_ablation.py` 单独运行，不覆盖官方结果；`22_planning_execution_diagnostics.py` 计算固定G、真实整日轨迹下的完美信息追索下界，仅用于区分规划场景偏差和因果执行信息损失，不进入正式策略。Q3/Q4-3的单日无调度缓存复算由 `23_q3_q4_3_repro_check.py` 完成。

问题二固定使用附件1电价，附件4只供问题四使用。问题二预测只读附件2历史，不使用附件3。所有日前特征和残差源必须满足 `date < target_date`；执行器固定0:00制定的G，只在本时段观测到来后因果调整储能和紧急购电。长运行缓存按代码、配置和输入签名隔离。

问题四显式读取附件4的365天×144时段电价。主流程采用“当天144点价格在00:00已知”的建模假设；题面没有明确其公布时序。Q4-2运行B1/B3/B4，Q4-3运行C0/C1/C2/C3，各自从附件4价格下重新计算的同一2月1日SOC出发，并逐策略连续传递实际SOC。两张官方表为 `outputs/q4/result4-2.xlsx` 和 `outputs/q4/result4-3.xlsx`；独立验收直接重读原始附件2、附件4并复算物理、费用与全部工作簿映射。
