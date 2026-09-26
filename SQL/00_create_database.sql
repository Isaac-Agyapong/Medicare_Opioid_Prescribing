-- =====================================================================
-- One-time setup (run as a superuser, connected to the "postgres" database):
--   psql -U postgres -d postgres -f SQL/00_create_database.sql
--
-- The database is placed in its own tablespace so its files live on a drive
-- with room for ~10M rows. Change the LOCATION to any empty folder the
-- PostgreSQL service account can write to (on Windows: NT AUTHORITY\NetworkService).
-- =====================================================================

CREATE TABLESPACE opioid_ts LOCATION 'D:/PostgresData/opioid_analytics';

CREATE DATABASE opioid_analytics
    WITH TABLESPACE = opioid_ts
         ENCODING = 'UTF8'
         TEMPLATE = template0;

COMMENT ON DATABASE opioid_analytics IS
    'Medicare Part D opioid prescribing vs. overdose deaths (portfolio project)';
