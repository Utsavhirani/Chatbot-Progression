-- Runs once, on first container start (empty volume).
CREATE DATABASE assistant_test;
\connect assistant
CREATE EXTENSION IF NOT EXISTS citext;
\connect assistant_test
CREATE EXTENSION IF NOT EXISTS citext;
