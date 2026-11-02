"""Inspect NX CAE API availability and the embedded solver's command usage."""
import json
import os
from pathlib import Path
import subprocess
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from nxdrp.adapters.nx_batch import NxBatchAdapter

folder = Path(sys.argv[1]).resolve()
folder.mkdir(parents=True, exist_ok=True)
adapter = NxBatchAdapter()
report = {"nx": adapter.run_journal("probe_cae", {}, work_dir=str(folder / "nx"), timeout_s=90)}
exe = Path(adapter.config.ugii_base_dir) / "NXNASTRAN/scnas/em64tntL/analysis.exe"
report["embedded_nastran_found"] = exe.is_file()
if exe.is_file():
    env = os.environ.copy()
    env.update(TEMP=str(folder), TMP=str(folder))
    env['UGII_BASE_DIR'] = adapter.config.ugii_base_dir
    env['PATH'] = str(Path(adapter.config.ugii_base_dir) / 'NXBIN') + os.pathsep + str(exe.parent) + os.pathsep + env.get('PATH', '')
    try:
        process = subprocess.run([str(exe)], cwd=folder, env=env, capture_output=True, timeout=20,
                                 creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
        report["solver_usage"] = {"returncode": process.returncode,
                                  "stdout": process.stdout.decode("utf-8", "replace")[-6000:],
                                  "stderr": process.stderr.decode("utf-8", "replace")[-6000:]}
    except subprocess.TimeoutExpired:
        report["solver_usage"] = {"error": "Solver usage probe timed out"}
(folder / "capabilities.json").write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
print(json.dumps(report, ensure_ascii=False))
