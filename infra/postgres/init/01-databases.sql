-- Runs once, on first container start (empty volume).
CREATE DATABASE assistant_test;
CREATE DATABASE assistant_e2e;
\connect assistant
CREATE EXTENSION IF NOT EXISTS citext;
\connect assistant_test
CREATE EXTENSION IF NOT EXISTS citext;
\connect assistant_e2e
CREATE EXTENSION IF NOT EXISTS citext;
