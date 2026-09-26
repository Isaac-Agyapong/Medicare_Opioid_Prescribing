-- core + analytics schemas: rebuilt on every run from the raw layer
DROP SCHEMA IF EXISTS analytics CASCADE;
DROP SCHEMA IF EXISTS core CASCADE;
CREATE SCHEMA core;
CREATE SCHEMA analytics;

-- ---------------------------------------------------------------------
-- core: star schema
-- ---------------------------------------------------------------------
CREATE TABLE core.dim_state (
    state_fips      char(2) PRIMARY KEY,
    state_abbr      char(2) NOT NULL UNIQUE,
    state_name      text    NOT NULL UNIQUE,
    census_region   text    NOT NULL
);

CREATE TABLE core.dim_specialty (
    specialty_id        smallint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    specialty           text NOT NULL UNIQUE,
    specialty_group     text NOT NULL
);

-- one row per prescriber (NPI) per year: the grain of the CMS file
CREATE UNLOGGED TABLE core.fact_prescriber_year (
    data_year               smallint NOT NULL,
    npi                     bigint   NOT NULL,
    entity_type             char(1)  NOT NULL,           -- I = individual, O = organization
    state_fips              char(2)  NOT NULL REFERENCES core.dim_state,
    zip5                    char(5),
    rural                   boolean,                      -- RUCA code 4-10 = micropolitan, small town or rural
    specialty_id            smallint NOT NULL REFERENCES core.dim_specialty,
    total_claims            numeric(12,1) NOT NULL,
    total_drug_cost         numeric(14,2) NOT NULL,
    total_beneficiaries     integer,                      -- NULL where CMS suppresses counts under 11
    opioid_claims           numeric(12,1),                -- NULL where suppressed
    opioid_drug_cost        numeric(14,2),
    opioid_day_supply       numeric(14,1),
    opioid_beneficiaries    integer,
    opioid_rate             numeric(7,4),                 -- opioid claims / total claims, as a percent (CMS definition)
    la_opioid_claims        numeric(12,1),
    la_opioid_rate          numeric(7,4),                 -- long-acting opioid claims / opioid claims, percent
    bene_avg_age            numeric(5,1),
    bene_avg_risk_score     numeric(6,3),
    PRIMARY KEY (data_year, npi)
);

-- CDC 12-month-ending counts, taken at December so each row is a calendar year
CREATE TABLE core.fact_state_overdose_year (
    state_fips              char(2)  NOT NULL REFERENCES core.dim_state,
    year                    smallint NOT NULL,
    all_drug_deaths         integer,
    opioid_deaths           integer,
    synthetic_opioid_deaths integer,                      -- mainly illicit fentanyl
    rx_opioid_deaths        integer,                      -- natural & semi-synthetic: prescription-type opioids
    heroin_deaths           integer,
    percent_complete        numeric(5,1),
    PRIMARY KEY (state_fips, year)
);

CREATE TABLE core.fact_national_overdose_year (
    year                    smallint PRIMARY KEY,
    all_drug_deaths         integer,
    opioid_deaths           integer,
    synthetic_opioid_deaths integer,
    rx_opioid_deaths        integer,
    heroin_deaths           integer,
    percent_complete        numeric(5,1)
);

-- CMS's own published opioid prescribing rates (no suppression), 2013 onward
CREATE TABLE core.fact_geo_prescribing_year (
    year                    smallint NOT NULL,
    geo_level               text     NOT NULL CHECK (geo_level IN ('National', 'State')),
    state_fips              char(2)  REFERENCES core.dim_state,       -- NULL for National
    breakout                text     NOT NULL CHECK (breakout IN ('Overall', 'Rural', 'Urban')),
    prescribers             integer,
    opioid_prescribers      integer,
    opioid_claims           numeric(14,1),
    total_claims            numeric(16,1),
    opioid_rate             numeric(6,2),                            -- percent of all Part D claims
    la_opioid_claims        numeric(14,1),
    la_opioid_rate          numeric(6,2),                            -- percent of opioid claims
    UNIQUE (year, geo_level, state_fips, breakout)
);

CREATE TABLE core.state_population (
    state_fips  char(2)  NOT NULL REFERENCES core.dim_state,
    year        smallint NOT NULL,
    population  bigint   NOT NULL,
    PRIMARY KEY (state_fips, year)
);
