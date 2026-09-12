from pathlib import Path
import csv,hashlib,json,os,subprocess,sys,tempfile,zipfile
ROOT=Path(__file__).parents[1].resolve(); archive=ROOT.parent/'cumcm2026_c_microgrid_q1_q2_verified_20260912.zip'
before={'scripts/03_solve_q1.py':'C77C1093D7219C51CA9D410BD309F4B19B61DF6231157655C57671D3FD1EBE5B','scripts/04_run_q2.py':'875CFA536D1428EC6FF0A2221796AD42C2E9DA9E5CE6CB29E693E10731C1DA28','src/microgrid/io.py':'7D826106A57CE9B60812A631AC14746913275D8E66BABB71B891EF038DDF5AF0','src/microgrid/models/deterministic_dispatch.py':'AEDCB18F63C5628B9F85A87690EB85C2AE71655B2F3BF1E832896857773C5BBD','src/microgrid/result_template.py':'9E5ADEDE7F55ACE589A2D235C2D7E1B66E72BC48429D1F95C3B5EDAE8E7E034B','src/microgrid/time_utils.py':'7AC89CFE6C68B5216682B8319FC38880D0C230A2F6AD97DAA7F8E6E657AA1F44'}
def digest(p): return hashlib.sha256(Path(p).read_bytes()).hexdigest().upper()
tracked=sorted(set(before)|{'src/microgrid/execution.py','src/microgrid/prediction.py','src/microgrid/scenarios.py','src/microgrid/models/stochastic_dispatch.py','scripts/05_validate_q1_q2.py','scripts/06_build_reports.py','scripts/07_package_verified.py','scripts/08_q2_sensitivity.py','outputs/q1/result1.xlsx','outputs/q2/result2.xlsx','outputs/q2/q2_strategy_comparison.csv','outputs/q2/prediction_metrics_main_overall.csv','outputs/q2/prediction_metrics_main_monthly.csv','outputs/q2/scenario_sensitivity_january.csv','reports/q2_analysis.md','reports/acceptance_evidence.json'})
with (ROOT/'reports/file_hashes_before_after.csv').open('w',newline='',encoding='utf-8-sig') as f:
    w=csv.writer(f);w.writerow(['path','sha256_before','sha256_after']);[w.writerow([x,before.get(x,'NEW'),digest(ROOT/x)]) for x in tracked]
skip={'__pycache__','.pytest_cache','cache'}
with zipfile.ZipFile(archive,'w',zipfile.ZIP_DEFLATED,compresslevel=6) as z:
    for p in ROOT.rglob('*'):
        rel=p.relative_to(ROOT)
        if p.is_file() and not any(part in skip for part in rel.parts): z.write(p,Path(ROOT.name)/rel)
with tempfile.TemporaryDirectory(prefix='cumcm_verify_') as td:
    with zipfile.ZipFile(archive) as z:z.extractall(td)
    extracted=Path(td)/ROOT.name
    checks={x:digest(ROOT/x)==digest(extracted/x) for x in tracked}
    env=os.environ.copy();env['PYTHONPATH']=str(extracted/'src')
    validation=subprocess.run([sys.executable,'scripts/05_validate_q1_q2.py'],cwd=extracted,env=env,capture_output=True,text=True)
    tests=subprocess.run([sys.executable,'-m','pytest','-q'],cwd=extracted,env=env,capture_output=True,text=True)
evidence={'archive':str(archive),'archive_sha256':digest(archive),'archive_bytes':archive.stat().st_size,'tracked_hashes_match':all(checks.values()),'hash_checks':checks,'extracted_validation_exit_code':validation.returncode,'extracted_pytest_exit_code':tests.returncode,'extracted_pytest_output':tests.stdout.strip()[-500:]}
(archive.with_suffix('.verification.json')).write_text(json.dumps(evidence,ensure_ascii=False,indent=2),encoding='utf-8');print(json.dumps(evidence,ensure_ascii=False,indent=2))
if not all(checks.values()) or validation.returncode or tests.returncode: raise SystemExit(1)
