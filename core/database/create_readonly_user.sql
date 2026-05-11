CREATE USER postgres_readonly
WITH PASSWORD 'industria123';

GRANT CONNECT ON DATABASE postgres
TO postgres_readonly;

GRANT USAGE ON SCHEMA public
TO postgres_readonly;

GRANT SELECT ON ALL TABLES IN SCHEMA public
TO postgres_readonly;

ALTER DEFAULT PRIVILEGES IN SCHEMA public
GRANT SELECT ON TABLES TO postgres_readonly;
