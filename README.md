# Carbon Emissions Reporting Platform

A full-stack prototype for tracking, calculating, and visualizing Scope 1 and Scope 2
greenhouse gas (GHG) emissions, built around the GHG Protocol. The platform combines a
versioned emission-factor engine with historical accuracy, advanced analytics (YoY,
intensity, hotspot), and an interactive dashboard.

**Live deployment:** https://ghg-platform-el9v.onrender.com

> Note: the deployment runs on Render's free tier with an ephemeral filesystem, so the
> database is freshly re-seeded from the source spreadsheet on every container start —
> manually submitted records or overrides will not persist across a redeploy or a
> free-tier sleep/wake cycle. See "Persistence" below for what a production setup
> would change.

---

## 1. Architecture
![Architecture Diagram](./assets/flowchart.png)

**Stack:**
- **Backend:** FastAPI + SQLAlchemy + SQLite
- **Frontend:** Single-page HTML/CSS/JS with Chart.js (no build step — served directly
  by the FastAPI app via `StaticFiles`)
- **Containerization:** Single Docker image runs both the API and the static frontend
- **Deployment:** Render (Docker-based web service)

**Why SQLite instead of Postgres:** the schema, queries, and ORM models are
database-agnostic via SQLAlchemy. SQLite was chosen to keep the stack to a single
container with zero external dependencies. Moving to Postgres is a one-line change to
the connection string in `database.py` plus adding a `postgres` service to
`docker-compose.yml` — no model or endpoint code changes required.

---

## 2. Database Schema

| Table | Purpose |
|---|---|
| `EmissionFactors` | Versioned master data. Each row carries `valid_from` / `valid_to`, so the same `activity_type` can have multiple factors across time — some current, some expired. |
| `EmissionRecords` | One row per recorded emission event. Linked to the specific `EmissionFactor` that was valid on that record's `activity_date`. |
| `AuditLog` | One row per manual override: old value, new value, reason, who made the change, and when. |
| `BusinessMetrics` | Time-series of business KPIs (production tonnage, headcount, energy consumption) used as denominators for intensity calculations. |

**Core design decision — historical accuracy:** `EmissionRecord.factor_id` is resolved
at creation time by looking up the factor valid *on that activity's date*, not simply
the newest factor for that activity type. See `backend/app/calc.py::get_valid_factor()`.
This means recalculating a 2023 record still returns the 2023 answer even after newer
2024 factors have been added to the system — the engine never silently substitutes a
more recent factor for a historical one.

---

## 3. Source Data & Documented Assumptions

The provided `GHG_Sheet_.xlsx` (Scope 1 and Scope 2 tabs) contains one year of real
facility data (2024), broken into quarters. To exercise the full feature set required
by the brief — year-over-year comparison and a genuine "factor changed over time"
scenario — the seed script (`backend/app/seed.py`) does the following, transparently:

1. **Loads all real 2024 Scope 1 and Scope 2 rows** from the spreadsheet as-is, with no
   modification to quantities, factors, or emission values.
2. **Generates a synthetic 2023 dataset** by scaling 2024 quantities down by a random
   factor (roughly 5–25% lower) and assigning a different — now expired — emission
   factor per activity/quarter. This gives `EmissionFactors` genuine expired-vs-current
   pairs and gives the YoY API two real years of data to compare.
3. **Synthesizes `BusinessMetrics`** for three metric types per quarter, since the
   source file has no production, headcount, or energy columns:
   - Tons of Steel Produced
   - Employee Headcount
   - Total Energy Consumed (kWh)

These assumptions are documented here rather than silently fabricated. In a production
handoff, items 2 and 3 would be replaced with actual prior-year emission records and
actual production/HR/energy data sourced from the relevant systems of record.

---

## 4. API Endpoints

| Method | Path | Purpose |
|---|---|---|
| POST | `/api/emissions` | Create a Scope 1/2 emission record. The engine resolves the date-valid factor and calculates emissions automatically. |
| GET | `/api/emissions?scope=` | List recorded emissions, optionally filtered by scope. |
| POST | `/api/emissions/{id}/override` | Manually override a calculated value. Writes an `AuditLog` entry. |
| GET | `/api/audit-log` | View the full override history. |
| POST | `/api/business-metrics` | Add a business metric (production, headcount, energy). |
| GET | `/api/business-metrics` | List business metrics. |
| GET | `/api/emission-factors` | List all versioned emission factors, including expired ones. |
| GET | `/api/activity-types?scope=` | Distinct activity types and their units for a given scope — powers the dashboard's dropdown. |
| GET | `/api/analytics/yoy?current_year=` | Total emissions by scope, current year vs. previous year. |
| GET | `/api/analytics/intensity?year=&quarter=` | kgCO2e per ton of product for a given period. |
| GET | `/api/analytics/hotspot?year=&scope=` | Emissions broken down by source, sorted by largest contributor. |
| GET | `/api/analytics/monthly-trend?year=` | Monthly emissions totals for the line chart. |

Interactive API documentation (Swagger UI) is available at `/docs` on both the local
and deployed instance.

---

## 5. Dashboard

A single page (`frontend/index.html`), served directly by the FastAPI app at `/`,
organized into a light, card-based layout:

- **Emission Record form** — Scope selector, an Activity Type dropdown populated live
  from the database (filtered by scope), an Activity Data quantity field, an
  auto-filled read-only Unit field, an activity date, and a facility field.
- **Business Metric form** — submit production tonnage, headcount, or energy
  consumption figures for a given date.
- **Manual Override panel** — correct a previously calculated emission value with a
  required reason, fully logged.
- **Stacked bar chart** — YoY emissions comparison, Scope 1 vs Scope 2.
- **Donut chart** — emission hotspot breakdown by source.
- **KPI cards** — emission intensity, Scope 1/2 totals, and YoY percentage change.
- **Line chart** — monthly emissions trend across the year.
- **Audit log table** — every manual override, with old/new values, reason, who, and
  when.

---

## 6. Running it

### Option A — Docker (recommended, matches the deployed environment)
```bash
docker compose up --build
```
Open **http://localhost:8000** — the dashboard and API are served on the same port.

### Option B — Local, no Docker
```bash
cd backend
pip install -r requirements.txt
python -m app.seed              # populates ghg.db from GHG_Sheet_.xlsx
uvicorn app.main:app --reload --port 8000
```
Open **http://localhost:8000**.

### Option C — Deployed instance
Visit **https://ghg-platform-el9v.onrender.com** directly. No setup required. Note the
free-tier sleep/wake behavior mentioned above — the first request after a period of
inactivity may take 30–60 seconds while the instance wakes up.

---

## 7. Persistence — what changes for production

SQLite on Render's free tier is ephemeral: the container re-seeds on every start, which
is intentional for a demo (it guarantees a known-good dataset) but means user-submitted
records and overrides do not survive a redeploy. A production deployment would:

- Move to a managed Postgres instance (Render Postgres, RDS, etc.) — no application
  code changes needed beyond the connection string, since the schema is defined via
  SQLAlchemy models, not raw SQL.
- Run the seed script once, on initial setup only, rather than on every container start.
- Add a persistent volume or rely on the managed database's own durability guarantees.

---

## 8. Quick proof of historical accuracy

```bash
curl "https://ghg-platform-el9v.onrender.com/api/emission-factors" | python3 -m json.tool
```
Look for `"activity_type": "Bituminous Coal"`. You'll see two date ranges — one
`2023-01-01` to `2023-03-31` (expired) and one `2024-01-01` to `2024-03-31` (current) —
with different `co2e_factor` values. Any 2023 `EmissionRecord` for coal links to the
2023 factor, not the 2024 one, confirming the engine resolves the factor valid *at the
time of the activity*, not the most recently added one.

---

## 9. Scope Notes

- Scope 3 (value chain) emissions are present in the source spreadsheet but out of
  scope for this build, per the brief's instruction to focus on Scope 1 and 2.
- Authentication and multi-tenant organization support are not implemented — this is a
  single-organization prototype.