-- =====================================================================
-- raw -> core: clean, type and conform the source data.
-- Every rule below fixes a problem found while profiling the raw files.
-- =====================================================================

-- ---------------------------------------------------------------------
-- dim_state: 50 states + DC.
-- The CMS state FIPS column is unreliable (351 distinct FIPS/abbreviation pairs in 2019),
-- so the abbreviation is taken as the truth and matched to Census FIPS codes: for each
-- Census FIPS code, the abbreviation it appears with most often is that state's.
-- (Matching the other way round fails: military codes such as AE/AP/AA and the unknown
-- codes XX/ZZ carry real state FIPS on a handful of rows.)
-- ---------------------------------------------------------------------
INSERT INTO core.dim_state (state_fips, state_abbr, state_name, census_region)
WITH pairs AS (
    SELECT prscrbr_state_abrvtn AS abbr, prscrbr_state_fips AS fips, count(*) AS n
    FROM raw.partd_prescriber
    WHERE prscrbr_state_fips ~ '^\d{2}$'
    GROUP BY 1, 2
),
best AS (
    SELECT DISTINCT ON (fips) abbr, fips FROM pairs ORDER BY fips, n DESC
),
census AS (
    SELECT DISTINCT p.state_fips, p.state_name, r.region_code
    FROM raw.census_population p
    JOIN raw.census_region r USING (state_fips)
    WHERE p.state_fips <= '56'                       -- 50 states + DC (excludes Puerto Rico, 72)
)
SELECT c.state_fips, b.abbr, c.state_name,
       CASE c.region_code WHEN '1' THEN 'Northeast' WHEN '2' THEN 'Midwest'
                          WHEN '3' THEN 'South'     WHEN '4' THEN 'West' END
FROM census c
JOIN best b ON b.fips = c.state_fips;

-- ---------------------------------------------------------------------
-- dim_specialty: CMS lists ~250 provider types, with spelling variants
-- ("Orthopaedic" / "Orthopedic") and very small categories. Names are standardised
-- and grouped into clinically meaningful groups for comparison.
-- ---------------------------------------------------------------------
CREATE TEMP TABLE specialty_clean AS
SELECT DISTINCT
    coalesce(prscrbr_type, '') AS source_name,       -- blank CSV fields arrive as NULL
    CASE coalesce(trim(prscrbr_type), '')
        WHEN ''                                     THEN 'Unknown'
        WHEN 'Orthopaedic Surgery'                  THEN 'Orthopedic Surgery'
        WHEN 'Physical Medicine & Rehabilitation'   THEN 'Physical Medicine and Rehabilitation'
        WHEN 'Colon & Rectal Surgery'               THEN 'Colorectal Surgery (Proctology)'
        WHEN 'Family Medicine'                      THEN 'Family Practice'
        WHEN 'Pediatrics'                           THEN 'Pediatric Medicine'
        WHEN 'Neurological Surgery'                 THEN 'Neurosurgery'
        WHEN 'Marriage and Family Therapist'        THEN 'Marriage & Family Therapist'
        ELSE trim(prscrbr_type)
    END AS specialty
FROM raw.partd_prescriber;

INSERT INTO core.dim_specialty (specialty, specialty_group)
SELECT DISTINCT specialty,
    CASE
        WHEN specialty IN ('Pain Management', 'Interventional Pain Management', 'Pain Medicine',
                           'Anesthesiology', 'Certified Registered Nurse Anesthetist (CRNA)',
                           'Anesthesiology Assistant')
            THEN 'Pain Medicine & Anesthesiology'
        WHEN specialty IN ('Physical Medicine and Rehabilitation', 'Sports Medicine',
                           'Osteopathic Manipulative Medicine', 'Neuromusculoskeletal Medicine, Sports Medicine')
            THEN 'Physical Medicine & Rehab'
        WHEN specialty = 'Hospice and Palliative Care'
            THEN 'Hospice & Palliative Care'
        WHEN specialty IN ('Family Practice', 'Internal Medicine', 'General Practice', 'Geriatric Medicine',
                           'Preventive Medicine', 'Pediatric Medicine')
            THEN 'Primary Care'
        WHEN specialty IN ('Nurse Practitioner', 'Physician Assistant', 'Certified Clinical Nurse Specialist',
                           'Certified Nurse Midwife', 'Registered Nurse', 'Licensed Practical Nurse',
                           'Licensed Vocational Nurse', 'Midwife')
            THEN 'Nurse Practitioner / PA'
        WHEN specialty IN ('Emergency Medicine', 'Hospitalist', 'Critical Care (Intensivists)')
            THEN 'Emergency & Hospital Medicine'
        WHEN specialty ~* '(^dentist|oral|maxillofacial|dental|periodont|prosthodont|denturist|orofacial)'
            THEN 'Dental'
        WHEN specialty ~* '(oncolog|hematolog|hematopoietic)'
            THEN 'Oncology & Hematology'
        -- checked before the surgery pattern: 'Neurology' contains the letters 'urology'
        WHEN specialty ~* '(psychiatr|neurology|addiction|epileptolog|sleep medicine)'
            THEN 'Psychiatry, Neurology & Addiction'
        WHEN specialty ~* '(surg|\murology|otolaryngology|podiatry|obstetrics)'
            THEN 'Surgery & Procedural'
        WHEN specialty LIKE 'Student in an Organized%'
            THEN 'Residents & Trainees'
        WHEN specialty IN ('Rheumatology', 'Cardiology', 'Gastroenterology', 'Nephrology', 'Pulmonary Disease',
                           'Endocrinology', 'Infectious Disease', 'Dermatology', 'Ophthalmology',
                           'Allergy/ Immunology', 'Interventional Cardiology', 'Clinical Cardiac Electrophysiology',
                           'Diagnostic Radiology', 'Interventional Radiology', 'Optometry')
            THEN 'Other Medical Specialties'
        ELSE 'Other / Non-physician'
    END
FROM specialty_clean;

-- ---------------------------------------------------------------------
-- fact_prescriber_year
--   * only prescribers located in the 50 states + DC (drops military APO/FPO codes,
--     territories and the XX/ZZ "unknown" codes)
--   * blanks -> NULL. CMS blanks opioid measures when the count is 1-10 (privacy
--     suppression), so NULL opioid_claims means "some, but fewer than 11", not zero
--   * RUCA 4-10 = micropolitan / small town / rural; 1-3 = metropolitan; 99 = unknown
-- ---------------------------------------------------------------------
INSERT INTO core.fact_prescriber_year
SELECT
    p.data_year,
    p.prscrbr_npi::bigint,
    p.prscrbr_ent_cd,
    s.state_fips,
    nullif(left(p.prscrbr_zip5, 5), ''),
    CASE WHEN p.prscrbr_ruca ~ '^\d' AND floor(p.prscrbr_ruca::numeric) BETWEEN 4 AND 10 THEN true
         WHEN p.prscrbr_ruca ~ '^\d' AND floor(p.prscrbr_ruca::numeric) BETWEEN 1 AND 3  THEN false
    END,
    d.specialty_id,
    p.tot_clms::numeric,
    p.tot_drug_cst::numeric,
    nullif(p.tot_benes, '')::numeric::integer,
    nullif(p.opioid_tot_clms, '')::numeric,
    nullif(p.opioid_tot_drug_cst, '')::numeric,
    nullif(p.opioid_tot_suply, '')::numeric,
    nullif(p.opioid_tot_benes, '')::numeric::integer,
    nullif(p.opioid_prscrbr_rate, '')::numeric,
    nullif(p.opioid_la_tot_clms, '')::numeric,
    nullif(p.opioid_la_prscrbr_rate, '')::numeric,
    nullif(p.bene_avg_age, '')::numeric,
    nullif(p.bene_avg_risk_scre, '')::numeric
FROM raw.partd_prescriber p
JOIN core.dim_state s        ON s.state_abbr = p.prscrbr_state_abrvtn
JOIN specialty_clean c       ON c.source_name = coalesce(p.prscrbr_type, '')
JOIN core.dim_specialty d    ON d.specialty = c.specialty;

CREATE INDEX ON core.fact_prescriber_year (specialty_id, data_year);
CREATE INDEX ON core.fact_prescriber_year (state_fips, data_year);

-- ---------------------------------------------------------------------
-- fact_geo_prescribing_year: CMS's published (unsuppressed) national and state rates
-- ---------------------------------------------------------------------
INSERT INTO core.fact_geo_prescribing_year
SELECT
    g.year::smallint,
    g.prscrbr_geo_lvl,
    s.state_fips,
    g.breakout,
    nullif(g.tot_prscrbrs, '')::numeric::integer,
    nullif(g.tot_opioid_prscrbrs, '')::numeric::integer,
    nullif(g.tot_opioid_clms, '')::numeric,
    nullif(g.tot_clms, '')::numeric,
    nullif(g.opioid_prscrbng_rate, '')::numeric,
    nullif(g.la_tot_opioid_clms, '')::numeric,
    nullif(g.la_opioid_prscrbng_rate, '')::numeric
FROM raw.opioid_geo g
LEFT JOIN core.dim_state s ON s.state_fips = g.prscrbr_geo_cd
WHERE g.prscrbr_geo_lvl = 'National'
   OR (g.prscrbr_geo_lvl = 'State' AND s.state_fips IS NOT NULL);

-- ---------------------------------------------------------------------
-- Overdose deaths: CDC reports 12-month-ending counts every month. The December value
-- is the calendar-year total. CDC reports New York City ("YC") separately from the rest
-- of New York ("NY"), so the two are added together. Where CDC withholds a drug-specific
-- count for either part, the New York total for that drug is left NULL rather than undercounted.
-- ---------------------------------------------------------------------
CREATE TEMP TABLE overdose_long AS
SELECT
    CASE state WHEN 'YC' THEN 'NY' ELSE state END AS state_abbr,
    year::smallint AS year,
    CASE indicator
        WHEN 'Number of Drug Overdose Deaths'              THEN 'all_drug'
        WHEN 'Opioids (T40.0-T40.4,T40.6)'                 THEN 'opioid'
        WHEN 'Synthetic opioids, excl. methadone (T40.4)'  THEN 'synthetic'
        WHEN 'Natural & semi-synthetic opioids (T40.2)'    THEN 'rx'
        WHEN 'Heroin (T40.1)'                              THEN 'heroin'
    END AS measure,
    nullif(replace(data_value, ',', ''), '')::numeric AS deaths,
    nullif(percent_complete, '')::numeric AS percent_complete
FROM raw.cdc_overdose
WHERE month = 'December'
  AND period = '12 month-ending'
  AND indicator IN ('Number of Drug Overdose Deaths', 'Opioids (T40.0-T40.4,T40.6)',
                    'Synthetic opioids, excl. methadone (T40.4)',
                    'Natural & semi-synthetic opioids (T40.2)', 'Heroin (T40.1)');

CREATE TEMP TABLE overdose_state_year AS
SELECT state_abbr, year, measure,
       CASE WHEN count(*) = count(deaths) THEN sum(deaths) END AS deaths,   -- NULL if any part withheld
       min(percent_complete) AS percent_complete
FROM overdose_long
GROUP BY 1, 2, 3;

INSERT INTO core.fact_state_overdose_year
SELECT s.state_fips, o.year,
       max(deaths) FILTER (WHERE measure = 'all_drug'),
       max(deaths) FILTER (WHERE measure = 'opioid'),
       max(deaths) FILTER (WHERE measure = 'synthetic'),
       max(deaths) FILTER (WHERE measure = 'rx'),
       max(deaths) FILTER (WHERE measure = 'heroin'),
       min(o.percent_complete)
FROM overdose_state_year o
JOIN core.dim_state s ON s.state_abbr = o.state_abbr
GROUP BY s.state_fips, o.year;

INSERT INTO core.fact_national_overdose_year
SELECT year,
       max(deaths) FILTER (WHERE measure = 'all_drug'),
       max(deaths) FILTER (WHERE measure = 'opioid'),
       max(deaths) FILTER (WHERE measure = 'synthetic'),
       max(deaths) FILTER (WHERE measure = 'rx'),
       max(deaths) FILTER (WHERE measure = 'heroin'),
       min(percent_complete)
FROM overdose_state_year
WHERE state_abbr = 'US'
GROUP BY year;

-- ---------------------------------------------------------------------
-- Population
-- ---------------------------------------------------------------------
INSERT INTO core.state_population
SELECT p.state_fips, p.year, p.population
FROM raw.census_population p
JOIN core.dim_state s USING (state_fips);

ANALYZE core.fact_prescriber_year;
