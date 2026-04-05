# DB_Assignment_3

Olympia is a sports management database project split into two main parts:

- `Module_A` focuses on a custom database engine built in Python, including B+ tree indexing, table management, transaction handling, and recovery experiments.
- `Module_B` is the application-facing implementation: a FastAPI + MySQL system with authentication, RBAC, audit logging, tamper detection, benchmarking, and load testing.

At the root, [`Olympia.sql`](./Olympia.sql) is the earlier single-file schema/data script for the Olympia dataset, while `Module_B/sql/` contains the staged SQL setup used by the web app.

## Repository Structure

```text
DB_Assignment_3/
|-- Olympia.sql
|-- Module_A/
|   |-- requirements.txt
|   |-- database/
|   |   |-- main.ipynb
|   |   |-- acid.ipynb
|   |   |-- db_manager.py
|   |   |-- table.py
|   |   |-- bplustree.py
|   |   |-- transaction_manager.py
|   |   |-- insertions.py
|   |   |-- bruteforce.py
|   |   |-- perfomance_analyser.py
|   |   |-- visualize_graph.py
|   |   |-- database.dat
|   |   `-- wal*.log
|   `-- images/
|       |-- insertion_stages/
|       `-- table_viz/
`-- Module_B/
    |-- .env.example
    |-- requirements.txt
    |-- TESTING_GUIDE.md
    |-- app/
    |   |-- main.py
    |   |-- config.py
    |   |-- database.py
    |   |-- limiter.py
    |   |-- auth/
    |   |-- middleware/
    |   |-- routers/
    |   |-- services/
    |   |-- templates/
    |   `-- ui/
    |-- sql/
    |-- benchmark/
    |-- loadtest/
    `-- logs/
```

## What Each Part Does

### `Olympia.sql`

- A standalone SQL script for the Olympia sports database.
- Useful as a compact reference for the core relational schema and seed data from the earlier assignment stage.

### `Module_A/`

This module is the "build your own database" part of the assignment.

#### `Module_A/database/`

- `bplustree.py`: B+ tree implementation and visualization support.
- `table.py`: table abstraction on top of the B+ tree index.
- `db_manager.py`: database and table lifecycle management, plus snapshot save/load.
- `transaction_manager.py`: ACID-style transaction layer with WAL, locking, commit, rollback, and recovery.
- `main.ipynb`: main notebook for interactive experimentation.
- `acid.ipynb`: notebook focused on ACID and transaction behavior.
- `insertions.py`: insertion demos used to observe index growth.
- `bruteforce.py`: simple baseline implementation for comparison.
- `perfomance_analyser.py`: compares/query performance behavior.
- `visualize_graph.py`: generates table or tree visualizations.
- `database.dat`: persisted database snapshot produced by the custom engine.
- `wal.log`, `wal_crash.log`, `wal_redo.log`: write-ahead log and recovery artifacts.

#### `Module_A/images/`

- `insertion_stages/`: snapshots of B+ tree changes during insert operations.
- `table_viz/`: visual outputs for table state transitions.
- `perfomance_plot.png`: performance-related visualization generated during analysis.

#### `Module_A/requirements.txt`

- Python dependencies needed for the custom database notebooks/scripts.

### `Module_B/`

This module is the production-style application built on MySQL and FastAPI.

#### `Module_B/app/`

Main application code.

- `main.py`: FastAPI entry point; registers routers, middleware, rate limiting, and health checks.
- `config.py`: environment variable loading and DB/JWT settings.
- `database.py`: MySQL pooled connections for `olympia_auth` and `olympia_track`.
- `limiter.py`: request throttling setup.
- `auth/`: login, logout, JWT/session handling, and role dependencies.
- `routers/`: API endpoints for members, teams, tournaments, events, equipment, performance, medical records, admin views, and registrations.
- `services/`: shared logic such as validation, RBAC helpers, ID generation, and audit hash-chain verification.
- `middleware/`: request middleware, including cookie refresh handling.
- `ui/`: server-rendered route layer for the browser interface.
- `templates/`: Jinja templates for dashboards, forms, detail pages, login, and admin views.

#### `Module_B/sql/`

Ordered SQL setup for the MySQL-backed system.

- `01_core_tables.sql`: creates `olympia_auth` and authentication/audit tables.
- `02_project_tables.sql`: creates `olympia_track` schema and inserts core sports data.
- `03_seed_users.sql`: inserts login accounts mapped to seed members.
- `04_tournament_registration.sql`: adds tournament registration support.
- `05_indexes.sql`: adds performance indexes used by the benchmark step.
- `06_tamper_detection.sql`: creates direct-modification logging and audit triggers.
- `generate_tamper_triggers.py`: generator for the tamper-detection trigger script.

#### `Module_B/loadtest/`

Automated reliability and concurrency testing.

- `run_all.py`: orchestrates the full verification flow.
- `test_acid.py`: ACID and consistency checks.
- `test_race_conditions.py`: concurrent write/race-condition scenarios.
- `test_failure.py`: restart, outage, and pool-exhaustion behavior.
- `test_stress.py`: Locust-backed stress and breaking-point tests.
- `verify.py`: post-test invariant checks on the database.
- `locustfile.py`: Locust workloads for admin/coach/player traffic.
- `results/`: generated HTML/CSV/Markdown reports from test runs.

#### `Module_B/benchmark/`

Performance measurement before and after adding indexes.

- `benchmark.py`: runs endpoint latency checks, raw SQL timing, and `EXPLAIN` capture.
- `results/`: stores `before.json`, `after.json`, explain plans, and comparison reports.
- `run_benchmark.sh`: helper script for benchmark execution.

#### `Module_B/logs/`

- `audit.log`: application-side logging output.

#### Other important files

- `TESTING_GUIDE.md`: full setup, demo accounts, curl examples, UI walkthrough, RBAC matrix, and audit-chain demo.
- `.env.example`: required environment variables for DB access, JWT config, tamper detection, and test harness settings.
- `requirements.txt`: Python dependencies for the FastAPI app and testing stack.

## Quick Start For Module B

If you mainly want to run the web application:

1. Create and activate a Python environment.
2. Install dependencies from `Module_B/requirements.txt`.
3. Copy `Module_B/.env.example` to `.env` and adjust values if needed.
4. Run the SQL files in `Module_B/sql/` in order from `01` to `06`.
5. Start the app with:

```bash
cd Module_B
uvicorn app.main:app --reload --port 8000
```

Then open `http://localhost:8000`.

For the full testing and demo workflow, use `Module_B/TESTING_GUIDE.md`.

## Suggested Reading Order

- Start with `Module_A/database/main.ipynb` if you want to understand the custom DB engine.
- Start with `Module_B/app/main.py` if you want the FastAPI app entry point.
- Read `Module_B/sql/01_core_tables.sql` and `02_project_tables.sql` to understand the relational design.
- Read `Module_B/TESTING_GUIDE.md` for how the app is exercised end-to-end.

## Generated / Runtime Artifacts

Some files in this repository are outputs produced by runs rather than hand-written source:

- `.coverage`
- `Module_A/database/database.dat`
- `Module_A/database/wal*.log`
- `Module_B/loadtest/results/*`
- `Module_B/benchmark/results/*`
- `Module_B/logs/*`

These are useful for demonstration, debugging, benchmarking, and recovery analysis.
