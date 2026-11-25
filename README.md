# Phase 1 Data Engineering Project

## Project
Global Energy Trends using the Our World in Data Energy dataset.

## Repository layout
- `docs/` proposal and phase notes
- `Phase 2/scripts/` ingestion, raw profiling, and Phase 3 cleaning/loading
- `Phase 2/sql/` raw and clean schemas, quality checks, and analytical views
- `Phase 2/tests/` pass/fail tests for cleaning rules
- `Phase 2/docker-compose.phase2.yml` Phase 2 ingestion service
- `Phase 2/docker-compose.phase3.yml` Phase 3 cleaning service
- `flows/` reserved for Kestra orchestration
- `docker-compose.yml` PostgreSQL and pgAdmin services
- `.env.example` local configuration template

## Start the environment
1. Install Docker Desktop and start it.
2. Copy `.env.example` to `.env` and change both passwords.
3. Run `docker compose up -d`.
4. Open pgAdmin at http://localhost:5050 and sign in with `PGADMIN_DEFAULT_EMAIL` and `PGADMIN_DEFAULT_PASSWORD` from `.env`.
5. Register a server: host `postgres`, port `5432`, maintenance database `energy_db`, username `energy_user`, and the password from `.env`.
6. Stop services with `docker compose down`. Data persists in named volumes. To intentionally erase it, use `docker compose down -v`.

The PostgreSQL health check gates pgAdmin startup. Containers communicate by the Compose service name `postgres`; use `localhost:5432` only from software running on your computer. Never commit `.env`.

## Dataset
https://catalog.ourworldindata.org/energy/owid_energy/

See `docs/proposal.md` for questions, expected database tables, and team details.

Phase 2 ingestion and Phase 3 cleaning steps are documented in `Phase 2/README.md`. Phase 3 rules and null thresholds are in `Phase 2/docs/DATA_QUALITY.md`.
