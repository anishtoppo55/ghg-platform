from sqlalchemy.orm import Session
from . import models


def get_valid_factor(db: Session, activity_type: str, scope: int, activity_date):
    """
    CRITICAL LOGIC: returns the EmissionFactor row whose validity window
    contains activity_date. This is what makes the engine 'historically accurate' --
    it does NOT just grab the newest factor for that activity_type.
    """
    return (
        db.query(models.EmissionFactor)
        .filter(
            models.EmissionFactor.activity_type == activity_type,
            models.EmissionFactor.scope == scope,
            models.EmissionFactor.valid_from <= activity_date,
            models.EmissionFactor.valid_to >= activity_date,
        )
        .first()
    )


def calculate_emissions(db: Session, activity_type: str, scope: int, activity_data: float, activity_date):
    """
    Emission Calculation Engine:
        Activity Data x Emission Factor (valid on activity_date) = GHG Emissions (tCO2e)
    Returns (factor_row, calculated_emissions). factor_row is None if no valid factor found
    (caller should handle this -- e.g. reject the record or flag for manual factor entry).
    """
    factor = get_valid_factor(db, activity_type, scope, activity_date)
    if factor is None:
        return None, None
    emissions = activity_data * factor.co2e_factor
    return factor, emissions
