# Medicare Opioid Prescribing vs. Overdose Deaths

An analysis of **7.8 million real Medicare prescription records (2019–2024)** alongside 12 years of national prescribing
rates and overdose deaths, built with **PostgreSQL, Python and Power BI**.

> **In short:** doctors and other prescribers in Medicare wrote about **40% fewer** opioid prescriptions in 2024 than in 2013,
> yet overdose deaths **doubled**. Most deaths now involve illegal fentanyl rather than prescription pills, and the states
> that prescribe the most are not the states with the most deaths. Nurse practitioners and physician assistants now write
> almost **a third** of these prescriptions. The project uses only public government data (Medicare, CDC, US Census).

**Question:** US opioid prescribing has been falling for a decade. Did overdose deaths follow, and where should
payers and public-health programs focus now?

![Power BI: national trend](Image/powerbi_page1.png)

---

## Key findings

| | Finding | Evidence |
|---|---|---|
| 📉 | **Opioid prescribing in Medicare fell 39.5% from 2013 to 2024** (5.82% to 3.52% of all Part D prescriptions), and it dropped every single year. | SQL Q1 |
| 📈 | **Over the same period overdose deaths doubled**, from 52,600 in 2015 to a peak of 109,400 in 2022. The share of opioid deaths involving **synthetic opioids (mainly illicit fentanyl) rose from 29% to 92%**, while deaths from prescription-type opioids stayed roughly flat. | SQL Q1, Q12 |
| 🗺️ | **Across states, prescribing no longer predicts deaths.** States that prescribe more actually tend to have *fewer* fentanyl deaths: the prescribing rate correlates *negatively* with fentanyl deaths in every year from 2015 to 2024 (r = −0.21 to −0.56), and only weakly positively with prescription-opioid deaths (r = 0.11 to 0.34). | SQL Q2 |
| 🩺 | **Nurse practitioners and PAs now write 30.5% of Medicare opioid prescriptions**, up from 22.5% in 2019, while primary care physicians fell from 42.8% to 34.6%. | SQL Q5, Q6 |
| 🎯 | **Pain medicine is concentrated.** About 10,900 prescribers (0.8% of all) write 12.6% of opioid prescriptions, and opioids make up 52% of what they prescribe. | SQL Q5 |
| 🔎 | **5,721 prescribers (0.8%) are extreme outliers against peers in their own specialty** (at or above the 99th percentile and at least 3x the specialty median). **One in five of them was flagged in every year from 2019 to 2024.** | SQL Q8, Q9 |

## Recommendations

1. **Fund overdose prevention from death and drug-supply data, not prescribing rates.** Since about 2016 the crisis has been driven by illicit fentanyl, and the states that prescribe most are not the states with the most deaths.
2. **Extend prescriber education and prescription monitoring to NPs and PAs**, who are now close to a third of Medicare opioid prescribing.
3. **Focus payer review on persistent peer outliers.** About 1,100 prescribers have been extreme outliers against their own specialty for six straight years. That is a short, defensible review list, and it avoids penalising specialties like pain medicine and hospice care where high use is expected.

---

## Data (all real, public, free)

| Source | What | Rows |
|---|---|---|
| [CMS Medicare Part D Prescribers – by Provider](https://data.cms.gov/provider-summary-by-type-of-service/medicare-part-d-prescribers/medicare-part-d-prescribers-by-provider) | One row per prescriber per year: total and opioid claims, long-acting opioids, specialty, location | 7.9M (2019–2024) |
| [CMS Medicare Part D Opioid Prescribing Rates – by Geography](https://data.cms.gov/summary-statistics-on-use-and-payments/medicare-medicaid-opioid-prescribing-rates/medicare-part-d-opioid-prescribing-rates-by-geography) | Official national and state rates, rural/urban | 2013–2024 |
| [CDC VSRR Provisional Drug Overdose Death Counts](https://data.cdc.gov/NCHS/VSRR-Provisional-Drug-Overdose-Death-Counts/xkb8-kh2a) | Deaths by state, month and drug type | 2015–2025 |
| [US Census Bureau population estimates](https://www.census.gov/programs-surveys/popest.html) | State population, for rates per 100,000 | 2015–2025 |

`Python/01_download_data.py` finds each file in the official CMS catalog and records its URL, size and SHA-256 in
[`Data/raw/manifest.json`](Data/raw/manifest.json). The raw files (4.4 GB) are not stored in this repo; the script re-downloads them.

**Privacy:** prescriber names and street addresses are deliberately not loaded. Prescribers are analysed in aggregate by
specialty and state, and outliers are counted, never named.

---

## How it's built

```
CMS / CDC / Census ──> Data/raw (4.4 GB) ──COPY──> PostgreSQL: raw ──> core (star schema) ──> analytics (views)
                                                                                                │
                                              Python notebook (charts) <────────────────────────┤
                                              Power BI (imports the views from PostgreSQL) <────┘
```

| Layer | Contents |
|---|---|
| `raw` | Source files loaded as text with PostgreSQL `COPY`, so nothing is coerced on the way in |
| `core` | Star schema: `fact_prescriber_year` (7.8M rows), `dim_specialty`, `dim_state`, overdose, population and CMS rate facts |
| `analytics` | 6 views, one per business question, plus a materialized view that benchmarks every prescriber against peers |

### Data problems found and fixed ([`SQL/02_transform.sql`](SQL/02_transform.sql))

- **Suppressed counts:** CMS blanks opioid counts of 1–10 for privacy (about 25% of prescribers). These are kept as NULL rather than zero, and the reconciliation check shows the prescriber file still covers **97.8% of CMS's published national opioid total** every year.
- **Inconsistent state codes:** the FIPS column disagrees with the state abbreviation on some rows, and military and unknown codes (AE, AP, XX, ZZ) sometimes carry real state FIPS codes. States are therefore matched through the abbreviation, with each FIPS code assigned to the abbreviation it co-occurs with most often.
- **250 specialty names:** spelling variants ("Orthopaedic" vs "Orthopedic") are merged and names grouped into 13 clinical groups. A regex trap was caught during validation: "Neurology" contains "urology" and was landing in Surgery.
- **New York City:** CDC reports NYC separately from the rest of New York, so the two are summed. Without this, New York's deaths would be undercounted by about half.
- **Withheld CDC detail:** drug-specific death counts are withheld in some state-years, so they stay NULL and are excluded from rate denominators rather than treated as zero.

All checks are in [`SQL/03_data_quality.sql`](SQL/03_data_quality.sql), with results in [`SQL/query_results.md`](SQL/query_results.md).

### SQL skills shown
PostgreSQL `COPY` bulk loading, schemas and a star schema, unlogged staging tables, CTEs, window functions (`LAG`,
`FIRST_VALUE`, `RANK`, `NTILE`, `percent_rank`), `FILTER` aggregates, `percentile_cont`, statistical aggregates
(`corr`, `regr_slope`), `DISTINCT ON`, regex classification, materialized views and indexes.

---

## Power BI dashboard

A 4-page report built as a **Power BI Project (`.pbip`)** that imports the analytics views directly from PostgreSQL
(server and database are parameters). The whole report is generated from code
([`Python/05_build_powerbi_project.py`](Python/05_build_powerbi_project.py)), so the model (TMDL), every visual (PBIR JSON)
and all 53 DAX measures are readable on GitHub. Every number was checked against the SQL results.

**Design choices**
- One colour, one meaning across all pages: **teal** = prescribing, **coral** = overdose deaths, **indigo** = NPs/PAs,
  **amber** = outliers, grey = everything else.
- Every chart title states the finding, and every KPI card has a context line (comparison or trend).
- A US **tile map** built from a matrix with measure-driven colours, a **hover tooltip page** with each state's profile,
  a year filter, cross-filtering, and a Data Notes page with sources, definitions and limitations.

**National overview**: KPI cards, area chart (prescribing −40%), stacked columns (deaths by drug type), donut (fentanyl share)
![Overview](Image/powerbi_page1.png)

**State comparison**: tile map of death rates, top-10 prescribing states, and the 10 deadliest states with their prescribing rank
![States](Image/powerbi_page2.png)

**Who prescribes**: 2019 vs 2024 prescriber mix, outlier KPIs, outliers by prescriber group with data bars
![Prescribers](Image/powerbi_page3.png)

**Data notes**
![Data notes](Image/powerbi_page4.png)

To open it: install Power BI Desktop, open `dashboard/Opioid_Prescribing.pbip`, sign in to PostgreSQL when prompted
(Database tab), then click **Refresh**.

## Python charts (analysis notebook)

| | |
|---|---|
| ![](Image/01_prescribing_vs_deaths.png) | ![](Image/02_state_scatter.png) |
| ![](Image/03_correlation_by_year.png) | ![](Image/04_specialty_shift.png) |
| ![](Image/05_outlier_persistence.png) | ![](Image/06_rural_urban.png) |

---
## Project structure

```
Medicare_Opioid_Prescribing/
├── Data/
│   ├── raw/manifest.json      # sources, sizes and checksums (raw files re-downloaded, not committed)
│   └── analytics/             # CSV exports of every analytics view
├── SQL/
│   ├── 00_create_database.sql # one-time setup (database + tablespace)
│   ├── 01a_schema_raw.sql, 01b_schema_core.sql
│   ├── 02_transform.sql       # cleaning rules
│   ├── 03_data_quality.sql    # 10 checks
│   ├── 04_analytics_views.sql # 6 views + peer-benchmark materialized view
│   ├── 05_business_questions.sql  # 12 queries
│   └── query_results.md       # every query with its output
├── Python/                    # download, load, run SQL, analysis notebook, Power BI generator, export
├── dashboard/                 # Power BI project (.pbip): model, report, background asset
├── Image/                     # charts and dashboard screenshots
└── run_all.py
```

## Reproduce it

1. Install PostgreSQL 16+ and Python 3.11+, then `pip install -r requirements.txt`.
2. Create the database once: `psql -U postgres -f SQL/00_create_database.sql`. Edit the tablespace path first; the database needs about 6 GB.
3. Save your password in `pgpass.conf` (Windows: `%APPDATA%\postgresql\pgpass.conf`), or set the `PGPASSWORD` environment variable.
4. Run `python run_all.py`. It downloads about 4.4 GB and takes roughly 20–30 minutes.
5. Optional: open `dashboard/Opioid_Prescribing.pbip` in Power BI Desktop, sign in to PostgreSQL when prompted, and click Refresh.

## Limitations

- **Medicare Part D only.** It covers mostly adults 65+ and people with disabilities, so it doesn't represent all US prescribing.
- **Aggregate data.** State-level correlations are ecological: they describe states, not individual patients.
- **Provisional 2024–2025 CDC counts** may still be revised.
- **Outliers are not wrongdoing.** "Outlier" is a statistical flag for review; high opioid use can be clinically appropriate.
