from pathlib import Path
import hashlib,json,os,subprocess,sys,tempfile,zipfile

ROOT=Path(__file__).parents[1].resolve();archive=ROOT.parent/'cumcm2026_c_microgrid_q1_q2_q3_verified_20260912.zip'
tracked=['configs/config.yaml','README.md','src/microgrid/io.py','src/microgrid/q3.py','src/microgrid/execution.py','src/microgrid/models/adjustment_dispatch.py','scripts/04_run_q2.py','scripts/05_validate_q1_q2.py','scripts/08_q2_sensitivity.py','scripts/09_run_q3.py','scripts/10_validate_q3.py','scripts/11_build_q3_report.py','scripts/12_export_q3.py','outputs/q1/result1.xlsx','outputs/q2/result2.xlsx','outputs/q2/q2_strategy_comparison.csv','outputs/q3/result3.xlsx','outputs/q3/q3_execution_detail.csv','outputs/q3/q3_strategy_comparison.csv','outputs/q3/q3_delta_selection.csv','reports/q2_analysis.md','reports/q3_analysis.md','reports/acceptance_evidence.json','reports/q3_acceptance_evidence.json']
def digest(path):return hashlib.sha256(Path(path).read_bytes()).hexdigest().upper()
skip={'__pycache__','.pytest_cache','cache','node_modules'}
with zipfile.ZipFile(archive,'w',zipfile.ZIP_DEFLATED,compresslevel=6) as z:
    for path in ROOT.rglob('*'):
        rel=path.relative_to(ROOT)
        if path.is_file() and not any(part in skip for part in rel.parts):z.write(path,Path(ROOT.name)/rel)
with tempfile.TemporaryDirectory(prefix='cumcm_q3_verify_') as td:
    with zipfile.ZipFile(archive) as z:z.extractall(td)
    extracted=Path(td)/ROOT.name;hashes={p:digest(ROOT/p)==digest(extracted/p) for p in tracked}
    env=os.environ.copy();env['PYTHONPATH']=str(extracted/'src');env['PYTHONUTF8']='1'
    commands=[('q1_q2_validation',[sys.executable,'scripts/05_validate_q1_q2.py']),('q3_validation',[sys.executable,'scripts/10_validate_q3.py']),('pytest',[sys.executable,'-m','pytest','-q']),('q2_sensitivity_no_cache',[sys.executable,'scripts/08_q2_sensitivity.py'])]
    runs={}
    for name,cmd in commands:
        r=subprocess.run(cmd,cwd=extracted,env=env,capture_output=True,text=True);runs[name]={'exit_code':r.returncode,'stdout_tail':r.stdout[-1000:],'stderr_tail':r.stderr[-1000:]}
e={'archive':str(archive),'archive_sha256':digest(archive),'archive_bytes':archive.stat().st_size,'tracked_hashes_match':all(hashes.values()),'hash_checks':hashes,'extracted_runs':runs}
archive.with_suffix('.verification.json').write_text(json.dumps(e,ensure_ascii=False,indent=2),encoding='utf-8');print(json.dumps(e,ensure_ascii=False,indent=2))
if not all(hashes.values()) or any(v['exit_code'] for v in runs.values()):raise SystemExit(1)
