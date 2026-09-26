-- =====================================================================
-- Schema for opioid_analytics (PostgreSQL 16+)
--
--   raw        exact copies of the source files (only the columns we use)
--   core       cleaned, typed, conformed tables: the star schema
--   analytics  views that answer the business questions (read by Power BI)
--
-- Run by Python/02_load_postgres.py; safe to re-run (drops and recreates).
--
-- The two large tables are UNLOGGED: they skip the write-ahead log, which makes loading
-- several times faster and keeps the WAL (stored with the server, often on C:) small.
-- Trade-off: after a server crash they are emptied, which is fine here because the whole
-- database is rebuilt from Data/raw by one script.
-- =====================================================================

DROP SCHEMA IF EXISTS raw CASCADE;
CREATE SCHEMA raw;

-- ---------------------------------------------------------------------
-- raw: loaded as text so nothing is lost or silently coerced on the way in
-- ---------------------------------------------------------------------
CREATE UNLOGGED TABLE raw.partd_prescriber (
    data_year               smallint NOT NULL,
    prscrbr_npi             text,
    prscrbr_ent_cd          text,
    prscrbr_city            text,
    prscrbr_state_abrvtn    text,
    prscrbr_state_fips      text,
    prscrbr_zip5            text,
    prscrbr_ruca            text,
    prscrbr_type            text,
    tot_clms                text,
    tot_30day_fills         text,
    tot_drug_cst            text,
    tot_day_suply           text,
    tot_benes               text,
    opioid_tot_clms         text,
    opioid_tot_drug_cst     text,
    opioid_tot_suply        text,
    opioid_tot_benes        text,
    opioid_prscrbr_rate     text,
    opioid_la_tot_clms      text,
    opioid_la_tot_suply     text,
    opioid_la_prscrbr_rate  text,
    bene_avg_age            text,
    bene_avg_risk_scre      text
);

CREATE TABLE raw.opioid_geo (
    year                        text,
    prscrbr_geo_lvl             text,
    prscrbr_geo_cd              text,
    prscrbr_geo_desc            text,
    ruca_cd                     text,
    breakout_type               text,
    breakout                    text,
    tot_prscrbrs                text,
    tot_opioid_prscrbrs         text,
    tot_opioid_clms             text,
    tot_clms                    text,
    opioid_prscrbng_rate        text,
    opioid_prscrbng_rate_5y_chg text,
    opioid_prscrbng_rate_1y_chg text,
    la_tot_opioid_clms          text,
    la_opioid_prscrbng_rate     text,
    la_opioid_prscrbng_rate_5y_chg text,
    la_opioid_prscrbng_rate_1y_chg text
);

CREATE TABLE raw.cdc_overdose (
    state                           text,
    year                            text,
    month                           text,
    period                          text,
    indicator                       text,
    data_value                      text,
    percent_complete                text,
    percent_pending_investigation   text,
    state_name                      text,
    footnote                        text,
    footnote_symbol                 text,
    predicted_value                 text
);

CREATE TABLE raw.census_population (
    state_fips  text,
    state_name  text,
    year        smallint,
    population  bigint
);

