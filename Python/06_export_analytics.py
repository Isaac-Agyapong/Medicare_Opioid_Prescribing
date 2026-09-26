"""Export the analytics views to Data/analytics/*.csv so the results can be inspected without PostgreSQL."""
import importlib
from pathlib import Path

import pandas as pd
import psycopg

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "Data" / "analytics"
OUT.mkdir(parents=True, exist_ok=True)
CONNINFO = importlib.import_module("02_load_postgres").CONNINFO
VIEWS = ["national_trend", "state_year", "state_prescribing_vs_deaths", "specialty_year",
         "rural_urban_trend", "outlier_summary"]


def main():
    with psycopg.connect(CONNINFO) as conn:
        for view in VIEWS:
            with conn.cursor() as cur:
                cur.execute(f"SELECT * FROM analytics.{view}")
                df = pd.DataFrame(cur.fetchall(), columns=[c.name for c in cur.description])
            df.to_csv(OUT / f"{view}.csv", index=False)
            print(f"  {view:<30} {len(df):>5} rows")


if __name__ == "__main__":
    main()
