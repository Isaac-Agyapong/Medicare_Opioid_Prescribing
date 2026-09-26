"""
Rebuild the whole project from public sources:

    python run_all.py

Prerequisites: PostgreSQL 16+ running locally, the opioid_analytics database created once with
SQL/00_create_database.sql, and the password in pgpass.conf (see README).

1. download the source files          -> Data/raw/ (~4.4 GB, skipped if present)
2. load PostgreSQL, clean, build views -> raw / core / analytics schemas (~15 min)
3. data quality + business SQL         -> SQL/query_results.md
4. analysis notebook                   -> Image/*.png
5. export analytics views              -> Data/analytics/*.csv
The Power BI project is generated separately by Python/05_build_powerbi_project.py.
"""
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent
PY = ROOT / "Python"
STEPS = [
    [sys.executable, PY / "01_download_data.py"],
    [sys.executable, PY / "02_load_postgres.py"],
    [sys.executable, PY / "03_run_sql_queries.py"],
    [sys.executable, "-m", "jupyter", "nbconvert", "--to", "notebook", "--execute", "--inplace",
     PY / "04_analysis.ipynb"],
    [sys.executable, PY / "06_export_analytics.py"],
]

for step in STEPS:
    print(f"\n>>> {' '.join(Path(str(s)).name for s in step[1:])}", flush=True)
    subprocess.run([str(s) for s in step], check=True, cwd=PY)
print("\nDone.")
