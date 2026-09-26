"""
Download every source file for the project into Data/raw/ and write Data/raw/manifest.json.

Sources (all public, no login required):
  1. CMS  Medicare Part D Prescribers - by Provider      one file per data year (~790 MB each)
  2. CMS  Medicare Part D Opioid Prescribing Rates - by Geography
  3. CDC  VSRR Provisional Drug Overdose Death Counts    (data.cdc.gov, dataset xkb8-kh2a)
  4. US Census Bureau state population estimates         (2010-2020 and 2020-2025 vintages)

CMS file URLs are looked up in the official catalog (data.cms.gov/data.json) by title and year,
so the script keeps working when CMS republishes files. The manifest records the exact URL,
size and SHA-256 of every file that was used. Files that already exist are skipped.
"""
import hashlib
import json
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

import requests

YEARS = range(2019, 2025)          # 2019-2024: pre-COVID baseline through the latest release
ROOT = Path(__file__).resolve().parents[1]
RAW = ROOT / "Data" / "raw"
RAW.mkdir(parents=True, exist_ok=True)
MANIFEST = RAW / "manifest.json"

CMS_CATALOG = "https://data.cms.gov/data.json"
PRESCRIBER_TITLE = "Medicare Part D Prescribers - by Provider"
GEO_TITLE = "Medicare Part D Opioid Prescribing Rates - by Geography"
CDC_OVERDOSE = "https://data.cdc.gov/api/views/xkb8-kh2a/rows.csv?accessType=DOWNLOAD"
CENSUS = {
    "census_state_pop_2010_2020.csv":
        ["https://www2.census.gov/programs-surveys/popest/datasets/2010-2020/state/totals/nst-est2020-alldata.csv"],
    "census_state_pop_2020_latest.csv": [
        "https://www2.census.gov/programs-surveys/popest/datasets/2020-2025/state/totals/NST-EST2025-ALLDATA.csv",
        "https://www2.census.gov/programs-surveys/popest/datasets/2020-2024/state/totals/NST-EST2024-ALLDATA.csv",
    ],
}

session = requests.Session()
session.headers["User-Agent"] = "medicare-opioid-portfolio-project"


def cms_csv_urls(catalog, title):
    """Return {data_year: csv_url} for one CMS dataset title."""
    dataset = next(d for d in catalog["dataset"] if d["title"] == title)
    urls = {}
    for dist in dataset["distribution"]:
        if dist.get("mediaType") == "text/csv":
            # distribution titles end with the reference date, e.g. "... : 2024-12-03"
            year = int(dist["title"].rsplit(":", 1)[-1].strip()[:4])
            urls[year] = dist["downloadURL"]
    return urls


def download(url, dest: Path):
    """Stream a file to disk (skipped if already present) and return its manifest entry."""
    if not dest.exists():
        tmp = dest.with_suffix(dest.suffix + ".part")
        # curl (bundled with Windows 10+, macOS and Linux) streams the large CMS files far faster
        # than requests does here, and "-C -" resumes a partial download after an interruption
        subprocess.run(["curl", "-L", "--fail", "--silent", "--show-error", "--retry", "5",
                        "--retry-delay", "5", "-C", "-", "-A", session.headers["User-Agent"],
                        "-o", str(tmp), url], check=True)
        tmp.replace(dest)
        print(f"  downloaded {dest.name} ({dest.stat().st_size / 1e6:,.0f} MB)")
    else:
        print(f"  exists     {dest.name}")
    sha = hashlib.sha256()
    with open(dest, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            sha.update(chunk)
    return {"file": dest.name, "url": url, "bytes": dest.stat().st_size, "sha256": sha.hexdigest()}


def main():
    entries = []
    catalog = session.get(CMS_CATALOG, timeout=120).json()

    print("CMS Part D prescribers by provider")
    prescriber_urls = cms_csv_urls(catalog, PRESCRIBER_TITLE)
    missing = [y for y in YEARS if y not in prescriber_urls]
    if missing:
        sys.exit(f"CMS catalog has no prescriber file for {missing}")
    for year in YEARS:
        entries.append({"source": "CMS", "dataset": PRESCRIBER_TITLE, "data_year": year,
                        **download(prescriber_urls[year], RAW / f"cms_partd_prescribers_{year}.csv")})

    print("CMS opioid prescribing rates by geography")
    geo_urls = cms_csv_urls(catalog, GEO_TITLE)
    latest = max(geo_urls)
    entries.append({"source": "CMS", "dataset": GEO_TITLE, "data_year": latest,
                    **download(geo_urls[latest], RAW / "cms_opioid_rates_by_geography.csv")})

    print("CDC provisional drug overdose deaths")
    entries.append({"source": "CDC", "dataset": "VSRR Provisional Drug Overdose Death Counts",
                    **download(CDC_OVERDOSE, RAW / "cdc_vsrr_overdose_deaths.csv")})

    print("Census state population estimates")
    for name, candidates in CENSUS.items():
        for url in candidates:
            try:
                entries.append({"source": "US Census Bureau", "dataset": "State population estimates",
                                **download(url, RAW / name)})
                break
            except subprocess.CalledProcessError:
                print(f"  not available yet: {url}")
        else:
            sys.exit(f"no Census file found for {name}")

    MANIFEST.write_text(json.dumps({
        "downloaded_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "files": entries,
    }, indent=2))
    total = sum(e["bytes"] for e in entries)
    print(f"\n{len(entries)} files, {total / 1e9:.2f} GB -> {RAW.relative_to(ROOT)} (manifest.json written)")


if __name__ == "__main__":
    main()
