-- =====================================================================
-- Data quality checks: run after every load. Results are written to
-- SQL/query_results.md by Python/03_run_sql_queries.py.
-- =====================================================================

-- Q1: Row counts, raw vs core, per year (how many rows each cleaning rule removed)
SELECT r.data_year,
       r.raw_rows,
       c.core_rows,
       r.raw_rows - c.core_rows                         AS excluded_rows,
       round(100.0 * (r.raw_rows - c.core_rows) / r.raw_rows, 2) AS excluded_pct
FROM (SELECT data_year, count(*) AS raw_rows FROM raw.partd_prescriber GROUP BY 1) r
JOIN (SELECT data_year, count(*) AS core_rows FROM core.fact_prescriber_year GROUP BY 1) c USING (data_year)
ORDER BY data_year;

-- Q2: Why rows were excluded: prescriber locations outside the 50 states + DC
SELECT prscrbr_state_abrvtn AS location_code,
       CASE WHEN prscrbr_state_abrvtn IN ('AA', 'AE', 'AP') THEN 'Military (APO/FPO)'
            WHEN prscrbr_state_abrvtn IN ('XX', 'ZZ')       THEN 'Unknown / foreign'
            ELSE 'US territory' END                     AS category,
       count(*)                                         AS rows_2019_2024
FROM raw.partd_prescriber r
WHERE NOT EXISTS (SELECT 1 FROM core.dim_state s WHERE s.state_abbr = r.prscrbr_state_abrvtn)
GROUP BY 1, 2
ORDER BY 3 DESC;

-- Q3: The unreliable CMS state FIPS column: rows whose FIPS disagrees with their state abbreviation
SELECT count(*)                                                      AS rows_checked,
       count(*) FILTER (WHERE r.prscrbr_state_fips = '')             AS blank_fips,
       count(*) FILTER (WHERE r.prscrbr_state_fips <> '' AND r.prscrbr_state_fips <> s.state_fips) AS mismatched_fips,
       round(100.0 * count(*) FILTER (WHERE r.prscrbr_state_fips <> s.state_fips OR r.prscrbr_state_fips = '')
             / count(*), 2)                                          AS unreliable_pct
FROM raw.partd_prescriber r
JOIN core.dim_state s ON s.state_abbr = r.prscrbr_state_abrvtn;

-- Q4: Duplicate prescriber-years (the primary key guarantees 0; shown for the record)
SELECT count(*) - count(DISTINCT (data_year, npi)) AS duplicate_npi_years
FROM core.fact_prescriber_year;

-- Q5: Privacy suppression: share of prescribers whose opioid count CMS withheld (1-10 claims)
SELECT data_year,
       count(*)                                         AS prescribers,
       count(*) FILTER (WHERE opioid_claims IS NULL)    AS opioid_count_suppressed,
       round(100.0 * count(*) FILTER (WHERE opioid_claims IS NULL) / count(*), 1) AS suppressed_pct,
       -- worst case: every suppressed prescriber had 10 claims
       round(100.0 * 10 * count(*) FILTER (WHERE opioid_claims IS NULL) / sum(opioid_claims), 2)
                                                        AS max_undercount_pct
FROM core.fact_prescriber_year
GROUP BY data_year
ORDER BY data_year;

-- Q6: Reconciliation: opioid claims in the prescriber file vs CMS's published national total
SELECT f.year,
       f.opioid_claims                                  AS prescriber_file_claims,
       g.opioid_claims                                  AS cms_published_claims,
       round(100.0 * f.opioid_claims / g.opioid_claims, 2) AS coverage_pct
FROM (SELECT data_year AS year, sum(opioid_claims) AS opioid_claims
      FROM core.fact_prescriber_year GROUP BY 1) f
JOIN core.fact_geo_prescribing_year g
  ON g.year = f.year AND g.geo_level = 'National' AND g.breakout = 'Overall'
ORDER BY f.year;

-- Q7: Logic checks on the cleaned fact table (all should be 0)
SELECT count(*) FILTER (WHERE opioid_claims > total_claims)        AS opioid_gt_total,
       count(*) FILTER (WHERE la_opioid_claims > opioid_claims)    AS long_acting_gt_opioid,
       count(*) FILTER (WHERE total_claims <= 0)                   AS non_positive_claims,
       count(*) FILTER (WHERE opioid_rate < 0 OR opioid_rate > 100) AS rate_out_of_range
FROM core.fact_prescriber_year;

-- Q8: Specialty standardisation: raw names collapsed into groups
SELECT specialty_group,
       count(*)                                         AS specialties,
       string_agg(specialty, ', ' ORDER BY specialty) FILTER (WHERE specialty_id IN
           (SELECT specialty_id FROM core.fact_prescriber_year GROUP BY 1 ORDER BY count(*) DESC LIMIT 40))
                                                        AS largest_members
FROM core.dim_specialty
GROUP BY specialty_group
ORDER BY specialties DESC;

-- Q9: CDC coverage: state-years where drug-specific opioid deaths are withheld
SELECT year,
       count(*)                                         AS states,
       count(*) FILTER (WHERE all_drug_deaths IS NULL)  AS missing_all_drug,
       count(*) FILTER (WHERE opioid_deaths IS NULL)    AS missing_opioid_detail,
       min(percent_complete)                            AS min_percent_complete
FROM core.fact_state_overdose_year
WHERE year BETWEEN 2015 AND 2025
GROUP BY year
ORDER BY year;

-- Q10: New York check: NY total = NY excluding NYC + NYC (CDC reports them separately)
SELECT r.year::int,
       max(r.data_value) FILTER (WHERE r.state = 'NY')  AS ny_excl_nyc,
       max(r.data_value) FILTER (WHERE r.state = 'YC')  AS nyc,
       max(o.all_drug_deaths)                           AS ny_total_in_core
FROM raw.cdc_overdose r
JOIN core.fact_state_overdose_year o ON o.state_fips = '36' AND o.year = r.year::int
WHERE r.state IN ('NY', 'YC') AND r.month = 'December'
  AND r.indicator = 'Number of Drug Overdose Deaths' AND r.year::int BETWEEN 2019 AND 2024
GROUP BY r.year
ORDER BY r.year;
