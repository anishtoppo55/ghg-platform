# Carbon Emissions Reporting Platform — Prototype

A prototype GHG Protocol-aligned reporting platform: tracks Scope 1 & 2 emissions,
applies versioned emission factors with historical accuracy, and exposes analytics
(YoY, intensity, hotspot) powering a single-page dashboard.

Access the deployed application here:

👉 https://apu-forecast-192u.onrender.com

> Note: The app may take 30–60 seconds to load on first visit due to cold start (Render free tier).

> [!WARNING]
> Due to cold start the audit log will be lost.


## 1. Architecture

```
┌─────────────────────┐        ┌───────────────────────────┐        ┌────────────────┐
│   Browser (SPA)      │ HTTP  │   FastAPI app (uvicorn)     │  SQL  │  SQLite (ghg.db) │
│  index.html + Chart.js│◄─────►│  - CRUD endpoints           │◄─────►│  - EmissionFactors│
│  (dashboard + forms)  │       │  - calc engine (calc.py)    │       │  - EmissionRecords│
└─────────────────────┘        │  - analytics endpoints      │       │  - AuditLog       │
                                 └───────────────────────────┘        │  - BusinessMetrics│
                                                                       └────────────────┘
```

**Stack:** FastAPI (Python) + SQLAlchemy + SQLite, vanilla HTML/JS + Chart.js for the
frontend (no build step — kept deliberately simple given the timeline), single Docker
container running everything (FastAPI serves the static frontend directly via
`StaticFiles`).

**Why SQLite instead of Postgres:** SQLite removes an entire
moving part (no separate DB container, no connection config) while still being "a real
relational database" with the same schema. Swapping to Postgres later is a one-line
change to `database.py`'s connection string plus adding a `postgres` service to
`docker-compose.yml` — the SQLAlchemy models don't change.

## 2. Database Schema

| Table | Purpose |
|---|---|
| `EmissionFactors` | Versioned master data. Each row has `valid_from`/`valid_to`, so the same `activity_type` can have multiple factors across time (some expired). |
| `EmissionRecords` | One row per recorded emission event. Links to the specific `EmissionFactor` that was valid on `activity_date`. |
| `AuditLog` | One row per manual override, with old value, new value, reason, who changed it, and when. |
| `BusinessMetrics` | Time-series of business KPIs (e.g. tons of steel produced) used as the denominator for intensity calculations. |

**The core design decision:** `EmissionRecord.factor_id` is fixed at creation time by
looking up the factor valid *on that activity's date* — not the newest factor for that
activity type. See `backend/app/calc.py::get_valid_factor()`. This is what makes
re-running the calculation on a 2023 record still produce the 2023 answer even after
2024 factors have been added.

## 3. Source Data & Assumptions

The provided `GHG_Sheet_.xlsx` (Scope 1 + Scope 2 tabs) only contains **one year (2024)**
of data, broken into quarters (Q1–Q3). To meet the assignment's requirements — which
need year-over-year comparison and a demonstrable "factor changed over time" scenario —
the seed script (`backend/app/seed.py`) does the following, **explicitly and
transparently**:

1. Loads all real 2024 Scope 1 & Scope 2 rows from the spreadsheet as-is.
2. Generates a **synthetic 2023 dataset** by scaling 2024 quantities down ~5–25% and
   assigning a *different* (now-expired) emission factor per activity/quarter. This
   gives the EmissionFactors table genuine expired vs. current rows, and gives the YoY
   API two real years to compare.
3. Synthesizes `BusinessMetrics` (tons of steel produced per quarter) — the source file
   has no production-volume column, so plausible values were assumed. This is the one
   piece of data with no grounding in the source file at all.

This is flagged here rather than silently fabricated — in a real handoff, #2 and #3
would be replaced by actual prior-year records and actual MES/production data.

## 4. API Endpoints

| Method | Path | Purpose |
|---|---|---|
| POST | `/api/emissions` | Create a Scope 1/2 emission record (engine picks the date-valid factor) |
| GET | `/api/emissions?scope=` | List records |
| POST | `/api/emissions/{id}/override` | Manually override a calculated value (writes AuditLog) |
| GET | `/api/audit-log` | View override history |
| POST | `/api/business-metrics` | Add a business metric (e.g. production volume) |
| GET | `/api/business-metrics` | List business metrics |
| GET | `/api/emission-factors` | List all versioned factors |
| GET | `/api/analytics/yoy?current_year=2024` | Total emissions by scope, current vs previous year |
| GET | `/api/analytics/intensity?year=2024&quarter=Q1` | kgCO2e per ton of product |
| GET | `/api/analytics/hotspot?year=2024&scope=1` | Emissions broken down by source, sorted descending |
| GET | `/api/analytics/monthly-trend?year=2024` | Monthly emissions totals (for the line chart) |

Interactive API docs are auto-generated at `/docs` (Swagger UI).

## 5. Dashboard

Single page (`frontend/index.html`) served directly by the FastAPI app at `/`:
- Form to submit a Scope 1/2 emission record
- Form to submit a business metric
- Manual override panel (writes to AuditLog, visible in the table below)
- **Stacked bar chart** — YoY emissions by scope
- **Donut chart** — emission hotspot by source
- **KPI card** — emission intensity (kgCO2e/ton)
- **Line chart** — monthly emissions trend

## 6. Running it

### Option A — Docker (recommended)
```bash
docker compose up --build
```
Then open **http://localhost:8000** — the dashboard and API are on the same port.

### Option B — Local, no Docker
```bash
cd backend
pip install -r requirements.txt
python -m app.seed              # populates ghg.db from GHG_Sheet_.xlsx
uvicorn app.main:app --reload --port 8000
```
Then open **http://localhost:8000**.

## 7. What was deliberately cut, given the timeline

- Scope 3 ingestion (brief explicitly says "focus on Scope 1 & 2")
- Authentication / multi-tenant org support
- Postgres (SQLite used instead — see rationale above)
- Automated tests (manual verification of each analytics endpoint was done instead;
  see `calc.py` for the single function that matters most: date-aware factor lookup)

## 8. Quick proof of historical accuracy

```bash
curl "http://localhost:8000/api/emission-factors" | python3 -m json.tool
```
Look for `"activity_type": "Bituminous Coal"` — you'll see two rows, one with
`valid_from: 2023-01-01 / valid_to: 2023-03-31` (expired) and one with
`valid_from: 2024-01-01 / valid_to: 2024-03-31` (current), with different
`co2e_factor` values. Any 2023 `EmissionRecord` for coal is linked to the 2023 factor,
not the 2024 one — confirming the engine used the factor valid *at the time*, not the
latest.
