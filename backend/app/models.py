from sqlalchemy import Column, Integer, String, Float, Date, Boolean, ForeignKey, DateTime
from sqlalchemy.sql import func
from .database import Base


class EmissionFactor(Base):
    """Versioned master data: a factor is only valid between valid_from and valid_to."""
    __tablename__ = "emission_factors"

    id = Column(Integer, primary_key=True, index=True)
    activity_type = Column(String, index=True)      # e.g. "Bituminous Coal", "Purchased Electricity - Grid"
    scope = Column(Integer)                          # 1 or 2
    unit = Column(String)                            # e.g. "tonnes", "kWh"
    co2e_factor = Column(Float)                       # value of the factor
    factor_unit = Column(String)                      # e.g. "tCO2/t", "tCO2/kWh"
    source = Column(String)                           # e.g. "IPCC 2006 Guidelines"
    valid_from = Column(Date)
    valid_to = Column(Date)


class EmissionRecord(Base):
    """One recorded emission event, linked to the factor that was valid at activity_date."""
    __tablename__ = "emission_records"

    id = Column(Integer, primary_key=True, index=True)
    scope = Column(Integer)
    activity_type = Column(String, index=True)
    activity_data = Column(Float)                      # raw quantity, e.g. liters/kWh/tonnes
    unit = Column(String)
    factor_id = Column(Integer, ForeignKey("emission_factors.id"), nullable=True)
    activity_date = Column(Date, index=True)            # date the activity actually occurred
    calculated_emissions = Column(Float)                 # tCO2e = activity_data * factor
    facility = Column(String, default="Central Steel Plant")
    is_override = Column(Boolean, default=False)
    created_at = Column(DateTime, server_default=func.now())


class AuditLog(Base):
    """Tracks every manual override made to an EmissionRecord."""
    __tablename__ = "audit_log"

    id = Column(Integer, primary_key=True, index=True)
    record_id = Column(Integer, ForeignKey("emission_records.id"))
    field_changed = Column(String)
    old_value = Column(String)
    new_value = Column(String)
    changed_by = Column(String, default="system")
    reason = Column(String, nullable=True)
    changed_at = Column(DateTime, server_default=func.now())


class BusinessMetric(Base):
    """Production / headcount metrics used for intensity calculations."""
    __tablename__ = "business_metrics"

    id = Column(Integer, primary_key=True, index=True)
    date = Column(Date, index=True)
    metric_name = Column(String)        # e.g. "Tons of Steel Produced"
    value = Column(Float)
    facility = Column(String, default="Central Steel Plant")
