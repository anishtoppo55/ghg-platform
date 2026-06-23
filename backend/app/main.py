import os
from datetime import date
from typing import Optional
from collections import defaultdict

from fastapi import FastAPI, Depends, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel
from sqlalchemy.orm import Session
from sqlalchemy import extract

from .database import Base, engine, get_db
from . import models, calc

Base.metadata.create_all(bind=engine)

app = FastAPI(title="GHG Emissions Reporting Platform")
app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_methods=["*"], allow_headers=["*"])


# ---------- Schemas ----------
class EmissionRecordIn(BaseModel):
    scope: int
    activity_type: str
    activity_data: float
    unit: str
    activity_date: date
    facility: str = "Central Steel Plant"


class OverrideIn(BaseModel):
    new_value: float
    reason: str
    changed_by: str = "user"


class BusinessMetricIn(BaseModel):
    date: date
    metric_name: str
    value: float
    facility: str = "Central Steel Plant"


# ---------- Milestone 3: Core CRUD ----------
@app.post("/api/emissions")
def create_emission_record(payload: EmissionRecordIn, db: Session = Depends(get_db)):
    factor, emissions = calc.calculate_emissions(
        db, payload.activity_type, payload.scope, payload.activity_data, payload.activity_date
    )
    if factor is None:
        raise HTTPException(
            status_code=422,
            detail=f"No valid emission factor found for '{payload.activity_type}' (scope {payload.scope}) on {payload.activity_date}",
        )
    rec = models.EmissionRecord(
        scope=payload.scope,
        activity_type=payload.activity_type,
        activity_data=payload.activity_data,
        unit=payload.unit,
        factor_id=factor.id,
        activity_date=payload.activity_date,
        calculated_emissions=emissions,
        facility=payload.facility,
        is_override=False,
    )
    db.add(rec)
    db.commit()
    db.refresh(rec)
    return rec


@app.get("/api/emissions")
def list_emission_records(scope: Optional[int] = None, db: Session = Depends(get_db)):
    q = db.query(models.EmissionRecord)
    if scope:
        q = q.filter(models.EmissionRecord.scope == scope)
    return q.order_by(models.EmissionRecord.activity_date.desc()).limit(200).all()


@app.post("/api/emissions/{record_id}/override")
def override_emission_record(record_id: int, payload: OverrideIn, db: Session = Depends(get_db)):
    rec = db.query(models.EmissionRecord).get(record_id)
    if rec is None:
        raise HTTPException(404, "Record not found")

    old_value = rec.calculated_emissions
    audit = models.AuditLog(
        record_id=rec.id,
        field_changed="calculated_emissions",
        old_value=str(old_value),
        new_value=str(payload.new_value),
        changed_by=payload.changed_by,
        reason=payload.reason,
    )
    rec.calculated_emissions = payload.new_value
    rec.is_override = True
    db.add(audit)
    db.commit()
    return {"record": rec, "audit_entry": audit}


@app.get("/api/audit-log")
def get_audit_log(db: Session = Depends(get_db)):
    return db.query(models.AuditLog).order_by(models.AuditLog.changed_at.desc()).all()


@app.post("/api/business-metrics")
def create_business_metric(payload: BusinessMetricIn, db: Session = Depends(get_db)):
    bm = models.BusinessMetric(**payload.dict())
    db.add(bm)
    db.commit()
    db.refresh(bm)
    return bm


@app.get("/api/business-metrics")
def list_business_metrics(db: Session = Depends(get_db)):
    return db.query(models.BusinessMetric).order_by(models.BusinessMetric.date).all()


@app.get("/api/emission-factors")
def list_emission_factors(db: Session = Depends(get_db)):
    return db.query(models.EmissionFactor).order_by(models.EmissionFactor.valid_from).all()


@app.get("/api/activity-types")
def list_activity_types(scope: int, db: Session = Depends(get_db)):
    """Distinct activity types + their default unit, for populating the dropdown."""
    rows = (
        db.query(models.EmissionFactor.activity_type, models.EmissionFactor.unit)
        .filter(models.EmissionFactor.scope == scope)
        .distinct()
        .order_by(models.EmissionFactor.activity_type)
        .all()
    )
    seen = {}
    for activity_type, unit in rows:
        seen[activity_type] = unit
    return [{"activity_type": k, "unit": v} for k, v in seen.items()]


# ---------- Milestone 2: Advanced Analytics ----------
@app.get("/api/analytics/yoy")
def yoy_emissions(current_year: int = 2024, db: Session = Depends(get_db)):
    """Total emissions by Scope for current_year vs current_year-1."""
    previous_year = current_year - 1
    result = {str(current_year): {"scope1": 0.0, "scope2": 0.0},
              str(previous_year): {"scope1": 0.0, "scope2": 0.0}}

    for year in (current_year, previous_year):
        for scope in (1, 2):
            total = (
                db.query(models.EmissionRecord)
                .filter(
                    extract("year", models.EmissionRecord.activity_date) == year,
                    models.EmissionRecord.scope == scope,
                )
                .all()
            )
            result[str(year)][f"scope{scope}"] = round(sum(r.calculated_emissions for r in total), 2)

    return result


@app.get("/api/analytics/intensity")
def emission_intensity(year: int = 2024, quarter: Optional[str] = None, db: Session = Depends(get_db)):
    """kgCO2e per Ton of Product for a given period (year, optionally narrowed to a quarter)."""
    q_records = db.query(models.EmissionRecord).filter(extract("year", models.EmissionRecord.activity_date) == year)
    q_metrics = db.query(models.BusinessMetric).filter(
        extract("year", models.BusinessMetric.date) == year,
        models.BusinessMetric.metric_name == "Tons of Steel Produced",
    )

    if quarter:
        q_starts = {"Q1": 1, "Q2": 4, "Q3": 7, "Q4": 10}
        month_start = q_starts[quarter]
        month_end = month_start + 2
        q_records = q_records.filter(
            extract("month", models.EmissionRecord.activity_date) >= month_start,
            extract("month", models.EmissionRecord.activity_date) <= month_end,
        )
        q_metrics = q_metrics.filter(
            extract("month", models.BusinessMetric.date) >= month_start,
            extract("month", models.BusinessMetric.date) <= month_end,
        )

    total_emissions_tco2e = sum(r.calculated_emissions for r in q_records.all())
    total_production_tons = sum(m.value for m in q_metrics.all())

    if total_production_tons == 0:
        raise HTTPException(422, "No production data available for this period")

    # tCO2e -> kgCO2e
    intensity_kg_per_ton = (total_emissions_tco2e * 1000) / total_production_tons

    return {
        "year": year,
        "quarter": quarter,
        "total_emissions_tco2e": round(total_emissions_tco2e, 2),
        "total_production_tons": total_production_tons,
        "intensity_kgco2e_per_ton": round(intensity_kg_per_ton, 4),
    }


@app.get("/api/analytics/hotspot")
def emission_hotspot(year: int = 2024, scope: Optional[int] = None, db: Session = Depends(get_db)):
    """Breaks down total emissions by source/activity_type to find the largest contributors."""
    q = db.query(models.EmissionRecord).filter(extract("year", models.EmissionRecord.activity_date) == year)
    if scope:
        q = q.filter(models.EmissionRecord.scope == scope)

    totals = defaultdict(float)
    for r in q.all():
        totals[r.activity_type] += r.calculated_emissions

    breakdown = sorted(
        [{"source": k, "emissions_tco2e": round(v, 2)} for k, v in totals.items()],
        key=lambda x: x["emissions_tco2e"],
        reverse=True,
    )
    total = sum(b["emissions_tco2e"] for b in breakdown)
    for b in breakdown:
        b["percentage"] = round((b["emissions_tco2e"] / total) * 100, 2) if total else 0

    return {"year": year, "scope": scope, "breakdown": breakdown}


@app.get("/api/analytics/monthly-trend")
def monthly_trend(year: int = 2024, db: Session = Depends(get_db)):
    """Total emissions per month for the given year (for the line chart)."""
    records = db.query(models.EmissionRecord).filter(extract("year", models.EmissionRecord.activity_date) == year).all()
    by_month = defaultdict(float)
    for r in records:
        by_month[r.activity_date.month] += r.calculated_emissions
    return [{"month": m, "emissions_tco2e": round(by_month.get(m, 0), 2)} for m in range(1, 13)]


# Serve the frontend. Works both in Docker (/app/frontend) and locally
# (../../frontend relative to this file, i.e. backend/../frontend).
_docker_path = "/app/frontend"
_local_path = os.path.join(os.path.dirname(__file__), "..", "..", "frontend")
_frontend_dir = _docker_path if os.path.isdir(_docker_path) else _local_path

app.mount("/", StaticFiles(directory=_frontend_dir, html=True), name="frontend")
