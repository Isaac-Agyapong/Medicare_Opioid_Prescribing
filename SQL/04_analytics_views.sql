-- =====================================================================
-- analytics: one view per business question. Power BI and the notebook read these.
-- =====================================================================

-- ---------------------------------------------------------------------
-- 1. National trend: prescribing (CMS, 2013+) next to overdose deaths (CDC, 2015+)
-- ---------------------------------------------------------------------
CREATE VIEW analytics.national_trend AS
SELECT
    g.year,
    g.prescribers,
    g.opioid_prescribers,
    g.opioid_claims,
    g.total_claims,
    g.opioid_rate,
    g.la_opioid_rate,
    round(100.0 * g.opioid_rate / first_value(g.opioid_rate) OVER (ORDER BY g.year), 1) AS opioid_rate_index_2013,
    d.all_drug_deaths,
    d.opioid_deaths,
    d.synthetic_opioid_deaths,
    d.rx_opioid_deaths,
    d.heroin_deaths,
    round(100.0 * d.synthetic_opioid_deaths / nullif(d.opioid_deaths, 0), 1) AS synthetic_share_pct
FROM core.fact_geo_prescribing_year g
LEFT JOIN core.fact_national_overdose_year d ON d.year = g.year
WHERE g.geo_level = 'National' AND g.breakout = 'Overall';

-- ---------------------------------------------------------------------
-- 2. State x year: official prescribing rate next to overdose death rates per 100,000
-- ---------------------------------------------------------------------
CREATE VIEW analytics.state_year AS
SELECT
    s.state_fips,
    s.state_abbr,
    s.state_name,
    s.census_region,
    g.year,
    g.opioid_rate,
    g.la_opioid_rate,
    g.opioid_claims,
    g.opioid_prescribers,
    p.population,
    o.all_drug_deaths,
    o.opioid_deaths,
    o.synthetic_opioid_deaths,
    o.rx_opioid_deaths,
    round(100000.0 * o.all_drug_deaths / p.population, 1)          AS overdose_death_rate,
    round(100000.0 * o.opioid_deaths / p.population, 1)            AS opioid_death_rate,
    round(100000.0 * o.synthetic_opioid_deaths / p.population, 1)  AS synthetic_death_rate,
    round(100000.0 * o.rx_opioid_deaths / p.population, 1)         AS rx_opioid_death_rate,
    rank() OVER (PARTITION BY g.year ORDER BY g.opioid_rate DESC)  AS prescribing_rank,
    g.total_claims
FROM core.fact_geo_prescribing_year g
JOIN core.dim_state s                  ON s.state_fips = g.state_fips
LEFT JOIN core.state_population p      ON p.state_fips = g.state_fips AND p.year = g.year
LEFT JOIN core.fact_state_overdose_year o ON o.state_fips = g.state_fips AND o.year = g.year
WHERE g.geo_level = 'State' AND g.breakout = 'Overall';

-- ---------------------------------------------------------------------
-- 3. Rural vs urban prescribing (CMS published rates)
-- ---------------------------------------------------------------------
CREATE VIEW analytics.rural_urban_trend AS
SELECT year, breakout AS area, opioid_rate, la_opioid_rate, prescribers, opioid_prescribers
FROM core.fact_geo_prescribing_year
WHERE geo_level = 'National' AND breakout IN ('Rural', 'Urban');

-- ---------------------------------------------------------------------
-- 4. Specialty group x year (prescriber-level file). Suppressed opioid counts (1-10)
--    are excluded from sums, so opioid_claims is a slight lower bound; the prescriber
--    count treats a suppressed value as "prescribed some opioids".
-- ---------------------------------------------------------------------
CREATE VIEW analytics.specialty_year AS
SELECT
    f.data_year AS year,
    d.specialty_group,
    count(*)                                                          AS prescribers,
    count(*) FILTER (WHERE f.opioid_claims IS NULL OR f.opioid_claims > 0) AS opioid_prescribers,
    sum(f.total_claims)                                               AS total_claims,
    sum(f.opioid_claims)                                              AS opioid_claims,
    round(100.0 * sum(f.opioid_claims) / sum(f.total_claims), 2)      AS opioid_rate,
    round(100.0 * sum(f.opioid_claims) / sum(sum(f.opioid_claims)) OVER (PARTITION BY f.data_year), 1)
                                                                      AS share_of_all_opioid_claims,
    round(100.0 * sum(f.la_opioid_claims) / nullif(sum(f.opioid_claims), 0), 2) AS la_opioid_rate,
    round(sum(f.opioid_day_supply) / nullif(sum(f.opioid_claims), 0), 1)        AS avg_days_per_opioid_claim
FROM core.fact_prescriber_year f
JOIN core.dim_specialty d USING (specialty_id)
GROUP BY f.data_year, d.specialty_group;

-- ---------------------------------------------------------------------
-- 5. Peer benchmarking: each prescriber vs others in the same specialty and year.
--    Eligible: individual prescribers with >= 100 Part D claims and an unsuppressed
--    opioid count. High outlier = opioid rate at or above the 99th percentile of peers
--    AND at least 3x the peer median. Identified only by NPI; analysed in aggregate.
-- ---------------------------------------------------------------------
CREATE MATERIALIZED VIEW analytics.prescriber_benchmark AS
WITH eligible AS (
    SELECT f.data_year, f.npi, f.state_fips, f.rural, f.specialty_id, f.total_claims,
           f.opioid_claims, f.la_opioid_claims, f.opioid_day_supply,
           100.0 * f.opioid_claims / f.total_claims AS opioid_rate
    FROM core.fact_prescriber_year f
    WHERE f.entity_type = 'I' AND f.total_claims >= 100 AND f.opioid_claims IS NOT NULL
),
peers AS (
    SELECT data_year, specialty_id,
           count(*)                                                         AS peer_count,
           percentile_cont(0.5)  WITHIN GROUP (ORDER BY opioid_rate)       AS peer_median,
           percentile_cont(0.99) WITHIN GROUP (ORDER BY opioid_rate)       AS peer_p99
    FROM eligible
    GROUP BY data_year, specialty_id
)
SELECT
    e.*,
    p.peer_count,
    round(p.peer_median::numeric, 3) AS peer_median_rate,
    round(p.peer_p99::numeric, 3)    AS peer_p99_rate,
    percent_rank() OVER (PARTITION BY e.data_year, e.specialty_id ORDER BY e.opioid_rate) AS peer_percentile,
    (p.peer_count >= 50 AND e.opioid_rate >= p.peer_p99 AND e.opioid_rate >= 3 * p.peer_median
     AND e.opioid_claims >= 50) AS is_high_outlier
FROM eligible e
JOIN peers p USING (data_year, specialty_id);

CREATE INDEX ON analytics.prescriber_benchmark (data_year, specialty_id);

-- ---------------------------------------------------------------------
-- 6. Outlier summary: how concentrated is opioid prescribing among outliers?
-- ---------------------------------------------------------------------
CREATE VIEW analytics.outlier_summary AS
SELECT
    b.data_year AS year,
    d.specialty_group,
    count(*)                                         AS eligible_prescribers,
    count(*) FILTER (WHERE b.is_high_outlier)        AS high_outliers,
    sum(b.opioid_claims)                             AS opioid_claims,
    sum(b.opioid_claims) FILTER (WHERE b.is_high_outlier) AS outlier_opioid_claims,
    round(100.0 * sum(b.opioid_claims) FILTER (WHERE b.is_high_outlier) / sum(b.opioid_claims), 1)
                                                     AS outlier_share_of_claims_pct
FROM analytics.prescriber_benchmark b
JOIN core.dim_specialty d USING (specialty_id)
GROUP BY b.data_year, d.specialty_group;

-- ---------------------------------------------------------------------
-- 7. Prescribing vs deaths, one row per state: 2019-2024 averages, used for the
--    correlation analysis and the scatter plot
-- ---------------------------------------------------------------------
CREATE VIEW analytics.state_prescribing_vs_deaths AS
SELECT
    state_abbr,
    state_name,
    census_region,
    round(avg(opioid_rate), 2)               AS avg_opioid_rate,
    round(avg(overdose_death_rate), 1)       AS avg_overdose_death_rate,
    round(avg(opioid_death_rate), 1)         AS avg_opioid_death_rate,
    round(avg(synthetic_death_rate), 1)      AS avg_synthetic_death_rate,
    round(avg(rx_opioid_death_rate), 1)      AS avg_rx_opioid_death_rate,
    count(opioid_death_rate)                 AS years_with_opioid_detail
FROM analytics.state_year
WHERE year BETWEEN 2019 AND 2024
GROUP BY state_abbr, state_name, census_region;
