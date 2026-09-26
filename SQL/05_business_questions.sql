-- =====================================================================
-- Business questions: where is opioid prescribing concentrated, how has it
-- changed, and does it still track with overdose deaths?
-- PostgreSQL features used: window functions (LAG, FIRST_VALUE, RANK, NTILE),
-- CORR / REGR_SLOPE, FILTER, percentile_cont, CTEs, materialized views.
-- =====================================================================

-- Q1: Twelve years of Medicare opioid prescribing next to overdose deaths
SELECT year,
       opioid_rate                          AS opioid_rate_pct,
       opioid_rate_index_2013,
       la_opioid_rate                       AS long_acting_pct,
       opioid_claims,
       all_drug_deaths,
       opioid_deaths,
       synthetic_opioid_deaths,
       rx_opioid_deaths,
       synthetic_share_pct
FROM analytics.national_trend
ORDER BY year;

-- Q2: Does a state's prescribing rate still predict its overdose deaths? (Pearson r by year)
SELECT year,
       count(*)                                                    AS states,
       round(corr(opioid_rate, overdose_death_rate)::numeric, 2)   AS r_all_overdose,
       round(corr(opioid_rate, opioid_death_rate)::numeric, 2)     AS r_opioid_deaths,
       round(corr(opioid_rate, rx_opioid_death_rate)::numeric, 2)  AS r_rx_opioid_deaths,
       round(corr(opioid_rate, synthetic_death_rate)::numeric, 2)  AS r_synthetic_deaths,
       round(regr_slope(rx_opioid_death_rate, opioid_rate)::numeric, 2) AS rx_deaths_per_rate_point
FROM analytics.state_year
WHERE year BETWEEN 2015 AND 2024
GROUP BY year
ORDER BY year;

-- Q3: Highest-prescribing states in 2024, with their death rates
SELECT prescribing_rank AS rank,
       state_name,
       census_region,
       opioid_rate                  AS opioid_rate_pct,
       overdose_death_rate          AS overdose_deaths_per_100k,
       rx_opioid_death_rate         AS rx_opioid_deaths_per_100k,
       synthetic_death_rate         AS fentanyl_deaths_per_100k
FROM analytics.state_year
WHERE year = 2024
ORDER BY prescribing_rank
LIMIT 10;

-- Q4: Which states cut prescribing the most, 2019 -> 2024?
WITH change AS (
    SELECT state_name, year, opioid_rate,
           FIRST_VALUE(opioid_rate) OVER (PARTITION BY state_name ORDER BY year) AS rate_2019
    FROM analytics.state_year
    WHERE year BETWEEN 2019 AND 2024
)
SELECT state_name,
       rate_2019                                                 AS rate_2019_pct,
       opioid_rate                                               AS rate_2024_pct,
       round(opioid_rate - rate_2019, 2)                         AS change_pts,
       round(100.0 * (opioid_rate - rate_2019) / rate_2019, 1)   AS change_pct,
       RANK() OVER (ORDER BY (opioid_rate - rate_2019) / rate_2019) AS rank_biggest_cut
FROM change
WHERE year = 2024
ORDER BY rank_biggest_cut
LIMIT 10;

-- Q5: Which specialties write the opioid prescriptions? Share of all opioid claims, 2019 vs 2024
SELECT specialty_group,
       max(share_of_all_opioid_claims) FILTER (WHERE year = 2019)  AS share_2019_pct,
       max(share_of_all_opioid_claims) FILTER (WHERE year = 2024)  AS share_2024_pct,
       max(opioid_rate) FILTER (WHERE year = 2024)                 AS opioid_rate_2024_pct,
       max(avg_days_per_opioid_claim) FILTER (WHERE year = 2024)   AS avg_days_supply_2024,
       max(prescribers) FILTER (WHERE year = 2024)                 AS prescribers_2024
FROM analytics.specialty_year
GROUP BY specialty_group
ORDER BY share_2024_pct DESC NULLS LAST;

-- Q6: Nurse practitioners and PAs: a growing share of opioid prescribing (year over year, LAG)
SELECT year,
       prescribers,
       opioid_claims,
       share_of_all_opioid_claims                                   AS share_pct,
       round(share_of_all_opioid_claims
             - LAG(share_of_all_opioid_claims) OVER (ORDER BY year), 1) AS share_change_pts
FROM analytics.specialty_year
WHERE specialty_group = 'Nurse Practitioner / PA'
ORDER BY year;

-- Q7: Rural vs urban: the prescribing gap over time
SELECT year,
       max(opioid_rate) FILTER (WHERE area = 'Rural')  AS rural_rate_pct,
       max(opioid_rate) FILTER (WHERE area = 'Urban')  AS urban_rate_pct,
       round(max(opioid_rate) FILTER (WHERE area = 'Rural')
             - max(opioid_rate) FILTER (WHERE area = 'Urban'), 2) AS rural_gap_pts
FROM analytics.rural_urban_trend
GROUP BY year
ORDER BY year;

-- Q8: Peer outliers in 2024: prescribers at or above the 99th percentile of their specialty
--     (and 3x the specialty median). How much of each group's prescribing do they account for?
SELECT specialty_group,
       eligible_prescribers,
       high_outliers,
       round(100.0 * high_outliers / eligible_prescribers, 2) AS outlier_pct_of_prescribers,
       outlier_share_of_claims_pct
FROM analytics.outlier_summary
WHERE year = 2024 AND high_outliers > 0
ORDER BY outlier_share_of_claims_pct DESC;

-- Q9: Are outliers persistent? Number of years (of 6) each 2024 outlier was also flagged
WITH flagged AS (
    SELECT npi, count(*) FILTER (WHERE is_high_outlier) AS years_flagged,
           bool_or(is_high_outlier AND data_year = 2024) AS flagged_2024
    FROM analytics.prescriber_benchmark
    GROUP BY npi
)
SELECT years_flagged,
       count(*)                                          AS prescribers,
       round(100.0 * count(*) / sum(count(*)) OVER (), 1) AS pct_of_2024_outliers
FROM flagged
WHERE flagged_2024
GROUP BY years_flagged
ORDER BY years_flagged;

-- Q10: Where are the outliers? Outliers per 1,000 eligible prescribers by state, 2024
SELECT s.state_name,
       count(*)                                           AS eligible_prescribers,
       count(*) FILTER (WHERE b.is_high_outlier)          AS high_outliers,
       round(1000.0 * count(*) FILTER (WHERE b.is_high_outlier) / count(*), 1) AS outliers_per_1000,
       NTILE(4) OVER (ORDER BY 1000.0 * count(*) FILTER (WHERE b.is_high_outlier) / count(*) DESC)
                                                          AS quartile
FROM analytics.prescriber_benchmark b
JOIN core.dim_state s USING (state_fips)
WHERE b.data_year = 2024
GROUP BY s.state_name
ORDER BY outliers_per_1000 DESC
LIMIT 10;

-- Q11: Long-acting opioids (higher overdose risk) as a share of opioid claims, by specialty, 2024
SELECT specialty_group,
       la_opioid_rate AS long_acting_pct,
       opioid_claims
FROM analytics.specialty_year
WHERE year = 2024 AND opioid_claims > 100000
ORDER BY la_opioid_rate DESC;

-- Q12: Death composition: what share of opioid deaths involve synthetic opioids (fentanyl)?
SELECT year,
       opioid_deaths,
       synthetic_opioid_deaths,
       rx_opioid_deaths,
       heroin_deaths,
       synthetic_share_pct,
       round(100.0 * rx_opioid_deaths / opioid_deaths, 1) AS rx_share_pct
FROM analytics.national_trend
WHERE opioid_deaths IS NOT NULL
ORDER BY year;
