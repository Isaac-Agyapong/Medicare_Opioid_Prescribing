"""
Load Data/raw/ into PostgreSQL (database opioid_analytics) and build the star schema.

    1. SQL/01a_schema_raw.sql       raw schema                     (skipped with --skip-raw)
    2. raw.*                        bulk-load source files with COPY (skipped with --skip-raw)
    3. SQL/01b_schema_core.sql      core + analytics schemas
    4. SQL/02_transform.sql         raw -> core: type, clean, conform, build dimensions
    5. SQL/04_analytics_views.sql   views used by the notebook and Power BI

    python Python/02_load_postgres.py              full rebuild (~5 min)
    python Python/02_load_postgres.py --skip-raw   rebuild core/analytics from the loaded raw layer

Connection settings come from the standard PG* environment variables, defaulting to
postgres@localhost:5432. The password is read by libpq from pgpass.conf (never stored here).
"""
import io
import os
import sys
import time
from pathlib import Path

import pandas as pd
import psycopg

ROOT = Path(__file__).resolve().parents[1]
RAW = ROOT / "Data" / "raw"
SQL = ROOT / "SQL"
YEARS = range(2019, 2025)

CONNINFO = " ".join([
    f"host={os.getenv('PGHOST', 'localhost')}",
    f"port={os.getenv('PGPORT', '5432')}",
    f"user={os.getenv('PGUSER', 'postgres')}",
    f"dbname={os.getenv('PGDATABASE', 'opioid_analytics')}",
])

# Only the columns the analysis needs. Prescriber names and street addresses are deliberately
# not loaded: the project analyses patterns, it does not single out named individuals.
PRESCRIBER_COLS = [
    "Prscrbr_NPI", "Prscrbr_Ent_Cd", "Prscrbr_City", "Prscrbr_State_Abrvtn", "Prscrbr_State_FIPS",
    "Prscrbr_Zip5", "Prscrbr_RUCA", "Prscrbr_Type", "Tot_Clms", "Tot_30day_Fills", "Tot_Drug_Cst",
    "Tot_Day_Suply", "Tot_Benes", "Opioid_Tot_Clms", "Opioid_Tot_Drug_Cst", "Opioid_Tot_Suply",
    "Opioid_Tot_Benes", "Opioid_Prscrbr_Rate", "Opioid_LA_Tot_Clms", "Opioid_LA_Tot_Suply",
    "Opioid_LA_Prscrbr_Rate", "Bene_Avg_Age", "Bene_Avg_Risk_Scre",
]


def copy_frame(cur, table, df):
    """COPY a DataFrame of strings into a table (columns matched by name)."""
    buf = io.StringIO()
    df.to_csv(buf, index=False, header=False)
    buf.seek(0)
    cols = ", ".join(df.columns)
    with cur.copy(f"COPY {table} ({cols}) FROM STDIN WITH (FORMAT csv)") as cp:
        while data := buf.read(1 << 20):
            cp.write(data)


def run_sql_file(conn, name):
    t = time.time()
    conn.execute((SQL / name).read_text(encoding="utf-8-sig"))
    conn.commit()
    print(f"  ran {name} ({time.time() - t:.0f}s)")


def limit_wal(conn):
    """Keep the write-ahead log small. It lives with the server install (often on C:), and a
    bulk load can otherwise grow it past 1 GB. Needs superuser; skipped silently otherwise."""
    try:
        with psycopg.connect(CONNINFO, autocommit=True) as admin:
            admin.execute("ALTER SYSTEM SET max_wal_size = '256MB'")
            admin.execute("SELECT pg_reload_conf()")
    except psycopg.errors.InsufficientPrivilege:
        pass


def load_prescribers(conn):
    with conn.cursor() as cur:
        for year in YEARS:
            path = RAW / f"cms_partd_prescribers_{year}.csv"
            header = pd.read_csv(path, nrows=0).columns
            missing = set(PRESCRIBER_COLS) - set(header)
            if missing:
                raise ValueError(f"{path.name} is missing columns {sorted(missing)}")
            t, rows = time.time(), 0
            for chunk in pd.read_csv(path, usecols=PRESCRIBER_COLS, dtype=str, keep_default_na=False,
                                     chunksize=250_000, encoding="utf-8", encoding_errors="replace"):
                chunk.columns = [c.lower() for c in chunk.columns]
                chunk.insert(0, "data_year", str(year))
                copy_frame(cur, "raw.partd_prescriber", chunk)
                rows += len(chunk)
            conn.commit()
            print(f"  raw.partd_prescriber  {year}: {rows:>9,} rows ({time.time() - t:.0f}s)")


def load_small_files(conn):
    with conn.cursor() as cur:
        geo = pd.read_csv(RAW / "cms_opioid_rates_by_geography.csv", dtype=str, keep_default_na=False)
        geo.columns = [c.lower() for c in geo.columns]
        copy_frame(cur, "raw.opioid_geo", geo)
        print(f"  raw.opioid_geo:        {len(geo):>9,} rows")

        cdc = pd.read_csv(RAW / "cdc_vsrr_overdose_deaths.csv", dtype=str, keep_default_na=False)
        cdc.columns = [c.strip().lower().replace(" ", "_") for c in cdc.columns]
        cdc = cdc[["state", "year", "month", "period", "indicator", "data_value", "percent_complete",
                   "percent_pending_investigation", "state_name", "footnote", "footnote_symbol",
                   "predicted_value"]]
        copy_frame(cur, "raw.cdc_overdose", cdc)
        print(f"  raw.cdc_overdose:      {len(cdc):>9,} rows")

        # Census: keep state-level rows (SUMLEV 40) and reshape POPESTIMATEyyyy columns to long form.
        # The 2010-2020 vintage supplies 2015-2019; the newest vintage supplies 2020 onward.
        frames = []
        for name, years in [("census_state_pop_2010_2020.csv", range(2015, 2020)),
                            ("census_state_pop_2020_latest.csv", range(2020, 2030))]:
            c = pd.read_csv(RAW / name, dtype=str, encoding="latin-1")
            c = c[c["SUMLEV"] == "040"]
            for y in years:
                if f"POPESTIMATE{y}" in c:
                    frames.append(pd.DataFrame({"state_fips": c["STATE"].str.zfill(2), "state_name": c["NAME"],
                                                "year": str(y), "population": c[f"POPESTIMATE{y}"]}))
        pop = pd.concat(frames)
        copy_frame(cur, "raw.census_population", pop)
        # region code is needed for dim_state; stash it in a small helper table
        regions = pd.read_csv(RAW / "census_state_pop_2020_latest.csv", dtype=str, encoding="latin-1")
        regions = regions[regions["SUMLEV"] == "040"][["STATE", "REGION"]]
        cur.execute("CREATE TABLE raw.census_region (state_fips text, region_code text)")
        copy_frame(cur, "raw.census_region",
                   regions.rename(columns={"STATE": "state_fips", "REGION": "region_code"})
                   .assign(state_fips=lambda d: d["state_fips"].str.zfill(2)))
        conn.commit()
        print(f"  raw.census_population: {len(pop):>9,} rows ({pop['year'].min()}-{pop['year'].max()})")


def main():
    start = time.time()
    skip_raw = "--skip-raw" in sys.argv
    with psycopg.connect(CONNINFO) as conn:
        limit_wal(conn)
        if not skip_raw:
            print("raw layer")
            run_sql_file(conn, "01a_schema_raw.sql")
            load_prescribers(conn)
            load_small_files(conn)
        print("core layer")
        run_sql_file(conn, "01b_schema_core.sql")
        run_sql_file(conn, "02_transform.sql")
        print("analytics layer")
        run_sql_file(conn, "04_analytics_views.sql")
        for table in ["core.fact_prescriber_year", "core.dim_specialty", "core.dim_state",
                      "core.fact_state_overdose_year", "core.state_population"]:
            n = conn.execute(f"SELECT count(*) FROM {table}").fetchone()[0]
            print(f"  {table:<32} {n:>10,} rows")
    print(f"done in {(time.time() - start) / 60:.1f} min")


if __name__ == "__main__":
    main()
