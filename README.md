# Spotter Trip Planner Backend

This backend provides trip planning APIs for generating:

- Route summary and geometry
- Stops (pickup, fuel, dropoff)
- Duty timeline events
- Daily log sheets with status totals
- High-level trip summary metrics

It is built with Django and Django REST Framework.

## What Is Implemented

- Input validation for trip planning requests
- Location resolution with live geocoding and offline fallback only when the provider fails
- Route resolution with live OSRM directions and fallback only when the provider fails
- HOS-aware timeline generation
- Fuel stop insertion every 1,000 miles
- Pickup and dropoff insertion (60 minutes each)
- Daily log sheet splitting and totals by duty status
- Health and API info endpoints
- Deterministic test suite across API and service layers

## Project Structure

- config: Django project configuration
- trip_planner: API endpoints, serializers, and planning services
- requirements.txt: Python dependencies
- .env.example: Environment variable template

## Requirements

- Python 3.12+
- Virtual environment

## Local Setup

1. Create and activate virtual environment.
2. Install dependencies from requirements.txt.
3. Optionally copy .env.example to .env and set values.
4. Run database migrations.
5. Start Django development server.

## Environment Variables

- DJANGO_SECRET_KEY: secret key for Django
- DJANGO_DEBUG: true or false
- DJANGO_ALLOWED_HOSTS: comma-separated hosts
- DJANGO_CORS_ALLOWED_ORIGINS: comma-separated allowed origins
- DJANGO_CSRF_TRUSTED_ORIGINS: comma-separated trusted origins
- DATABASE_URL: Postgres connection string, typically your Supabase database URL for production
- TRIP_PLANNER_USE_EXTERNAL_GEOCODING: true by default to enable live geocoding, false to force deterministic fallback
- TRIP_PLANNER_USE_EXTERNAL_ROUTING: true by default to enable live routing, false to force deterministic fallback

## Testing

### Automated Test Suite

Run Django checks, then run tests.

- Django check validates project configuration.
- Test suite validates API contract, timeline behavior, stop insertion, and edge cases.

Current suite includes:

- Health and API info endpoint tests
- Plan trip response integrity tests
- Ordered event timeline tests
- Fuel stop insertion tests for long trips
- High cycle-used reset behavior tests
- Multi-day daily log generation tests
- Validation failure tests (bad cycle hours, duplicate locations)
- Service-level tests for route and daily log generation

### Supabase-backed test mode

By default, `manage.py test` uses in-memory SQLite for fast and deterministic unit tests.

To run tests against Supabase/Postgres as well, enable:

- `DJANGO_TEST_USE_DATABASE_URL=true`
- optionally `DJANGO_TEST_DATABASE_URL` (if you want a dedicated test database URL)

Example:

```bash
DJANGO_TEST_USE_DATABASE_URL=true python manage.py test trip_planner.tests -v 1
```

Quick connectivity check before running Supabase-backed tests:

```bash
python -c "from dotenv import dotenv_values; import psycopg2; d=dotenv_values('.env'); conn=psycopg2.connect(d['DATABASE_URL'], connect_timeout=5); cur=conn.cursor(); cur.execute('select 1'); print(cur.fetchone()); conn.close()"
```

### Interactive API Testing with Swagger

After starting the development server, access the interactive Swagger UI:

- **Swagger UI**: http://localhost:8000/api/docs/
- **Schema (OpenAPI JSON)**: http://localhost:8000/api/schema/

The Swagger interface provides:

- Full API endpoint documentation
- Interactive request/response testing
- Request parameter validation
- Automatic schema generation from code

To start the dev server:

```bash
python manage.py runserver
```

Then open http://localhost:8000/api/docs/ in your browser to test all endpoints interactively.

## Render Deployment

This backend is Render-ready and expects the database to live outside Render.

Recommended service settings:

- Build command: `pip install -r requirements.txt && python manage.py collectstatic --noinput && python manage.py migrate`
- Start command: `gunicorn config.wsgi:application`
- Environment variables: set `DJANGO_SECRET_KEY`, `DJANGO_DEBUG=false`, `DJANGO_ALLOWED_HOSTS`, `DJANGO_CORS_ALLOWED_ORIGINS`, `DJANGO_CSRF_TRUSTED_ORIGINS`, and `DATABASE_URL`

For the database, create a Supabase Postgres instance and paste its connection string into `DATABASE_URL` on Render.

For Render deployments, Supabase pooler URLs are usually the most reliable:

`postgresql://postgres.<project-ref>:<password>@aws-0-<region>.pooler.supabase.com:6543/postgres?sslmode=require`

If your project exposes direct DB host access, this format can be used:

`postgresql://postgres:<password>@db.<project-ref>.supabase.co:5432/postgres?sslmode=require`

The app uses `DATABASE_URL` when available and falls back to SQLite for local development.

Local development & secrets
---------------------------

- **Do not commit secrets.** Keep `backend/.env` out of source control. Use `backend/.env.example` as a template and copy it locally:

```bash
cp backend/.env.example backend/.env
# Edit backend/.env and replace placeholders with your values
```

- **Rotate credentials** if you previously committed real secrets. Remove them from history (or rotate credentials) and replace with placeholders.

- **Frontend env:** create or update `frontend/.env` to point to your backend during local development:

```bash
# frontend/.env
VITE_API_BASE_URL=http://127.0.0.1:8000
```

- **Run locally** (recommended):

```bash
# Backend
python -m venv .venv
source .venv/bin/activate
pip install -r backend/requirements.txt
cp backend/.env.example backend/.env
# edit backend/.env with real values
python backend/manage.py migrate
python backend/manage.py runserver

# Frontend
cd frontend
pnpm install
pnpm dev
```

- **CI:** A GitHub Actions workflow has been added at `.github/workflows/ci.yml` to run backend tests and build the frontend.

If you want deterministic behavior during assessment demos, override these to false:

- `TRIP_PLANNER_USE_EXTERNAL_GEOCODING=false`
- `TRIP_PLANNER_USE_EXTERNAL_ROUTING=false`

## API Overview

Base path: /api

### GET /api/

Returns API metadata:

- Service name
- Version
- Available endpoint paths

### GET /api/health

Returns service health status.

### POST /api/plan-trip

Generates the trip plan using:

- current_location
- pickup_location
- dropoff_location
- cycle_used_hours
- trip_start_time (optional)

Response includes:

- route
- stops
- duty_events
- daily_logs
- summary
- assumptions_applied

### POST /api/plan-trip Contract

Request fields:

| Field | Type | Required | Rules | Example |
|---|---|---|---|---|
| current_location | string | Yes | Must not equal pickup_location | Dallas, TX |
| pickup_location | string | Yes | Must not equal current_location or dropoff_location | Oklahoma City, OK |
| dropoff_location | string | Yes | Must not equal pickup_location | Denver, CO |
| cycle_used_hours | number | Yes | Range: 0 to 70 | 24 |
| trip_start_time | datetime (ISO 8601) | No | Parsed as UTC if timezone absent | 2026-04-29T08:00:00Z |

Top-level response fields:

| Field | Type | Description |
|---|---|---|
| route | object | Route metrics, geometry, provider, waypoints, and leg summaries |
| stops | array | Ordered stop list including pickup, fuel, and dropoff events |
| duty_events | array | Full duty timeline events with type, status, and timestamps |
| daily_logs | array | Day-split logs with events and totals_by_status |
| summary | object | Aggregated trip totals and remaining cycle hours |
| assumptions_applied | object | Planning assumptions used during computation |

Nested response contracts:

`route` object:

| Field | Type | Description |
|---|---|---|
| distance_miles | number | Total planned route distance |
| duration_minutes | integer | Total planned route duration |
| geometry | object | GeoJSON-like line geometry |
| provider | string | Source of route data (for example, osrm or fallback_haversine) |
| waypoints | array | Current, pickup, and dropoff waypoint coordinates |
| legs | array | Per-leg mileage summary |

`stop` item:

| Field | Type | Description |
|---|---|---|
| type | string | pickup, fuel, or dropoff |
| eta | datetime (ISO 8601) | Planned stop start time |
| duration_minutes | integer | Stop duration in minutes |
| location | string | Stop location label |

`duty_event` item:

| Field | Type | Description |
|---|---|---|
| type | string | Event type (for example DRIVING, FUEL, PICKUP, DROPOFF, OFF_DUTY) |
| duty_status | string | OFF_DUTY, SLEEPER, DRIVING, or ON_DUTY_NOT_DRIVING |
| start_time | datetime (ISO 8601) | Event start time |
| end_time | datetime (ISO 8601) | Event end time |
| duration_minutes | integer | Event duration |
| location | string | Associated location label |
| notes | string | Planner notes for the event |

`daily_log` item:

| Field | Type | Description |
|---|---|---|
| date | string (YYYY-MM-DD) | Log date |
| events | array | Duty events on this date |
| totals_by_status | object | Hour totals by duty status |

`summary` object:

| Field | Type | Description |
|---|---|---|
| days | integer | Total number of daily logs generated |
| driving_hours | number | Total driving hours |
| on_duty_hours | number | Total on-duty hours |
| off_duty_hours | number | Total off-duty hours |
| remaining_cycle_hours | number | Remaining cycle hours at trip end |

## How The API Works

1. Request is received and validated.
2. Locations are geocoded.
3. Route data is resolved.
4. Trip is expanded into duty events with HOS constraints.
5. Pickup/dropoff/fuel stops are inserted.
6. Events are split into per-day logs.
7. Summary metrics and assumptions are returned.

## Route and Function Responsibility Map

### Routes and View Functions

- ApiInfoView.get: Returns API metadata and route listing.
- HealthCheckView.get: Returns backend health status.
- PlanTripView.post: Validates request and returns planned trip payload.

### Serializer Functions

- TripRequestSerializer.validate: Enforces location uniqueness rules and request-level validation.

### Service Functions

- build_trip_plan: Orchestrates complete planning workflow and returns final payload.
- _parse_start_time: Normalizes trip start time into UTC.
- _geocode_location: Resolves coordinates from external geocoding with fallback behavior.
- _pseudo_geocode: Generates deterministic fallback coordinates.
- _resolve_route: Chooses route provider strategy.
- _fetch_osrm_route: Fetches route geometry and route metrics from OSRM.
- _fallback_route: Computes fallback route using haversine distance.
- _distance_miles: Calculates distance between coordinates.
- _split_events_by_day: Splits timeline events into daily logs and totals.
- _event_dict: Creates normalized event payload entries.

### PlannerState Methods

- __init__: Initializes timeline state, cycle counters, and output containers.
- _append_event: Adds an event and updates driving, duty, and cycle counters.
- _add_stop: Appends stop entries to stop output payload.
- _take_reset_break: Adds reset off-duty block and resets shift counters.
- _take_short_break_if_needed: Applies break when driving threshold is reached.
- _ensure_capacity_for_on_duty: Prevents on-duty events from violating shift or cycle limits.
- add_on_duty_stop: Adds ON_DUTY_NOT_DRIVING stop events.
- drive_leg: Converts route miles into driving, break, reset, and fuel events.

## Notes and Current Assumptions

- Property-carrying driver assumptions are applied.
- 70-hour cycle assumptions are applied.
- Fuel interval is 1,000 miles.
- Pickup and dropoff are each 60 minutes.
- No adverse driving conditions are modeled.

## Production Notes

- Configure all environment variables before deployment.
- Use gunicorn for production serving.
- Restrict allowed hosts and origins in production.
