"""Database helpers for aircraft state, upgrades, and ECO calculations."""

from decimal import Decimal, ROUND_HALF_UP
from typing import List

from upgrade_config import (
    UPGRADE_CODE,
    STARTER_BASE_COST,
    STARTER_GROWTH,
    NON_STARTER_BASE_PCT,
    NON_STARTER_MIN_BASE,
    NON_STARTER_GROWTH,
)
from utils import get_connection

from .common import _to_dec


def fetch_player_aircrafts_with_model_info(save_id: int) -> List[dict]:
    """Return all unsold aircraft for the save, hydrated with model metadata."""
    sql = """
        SELECT
            a.aircraft_id,
            a.registration,
            a.model_code,
            am.model_name,
            am.category,
            a.purchase_price  AS purchase_price_aircraft,
            am.purchase_price AS purchase_price_model,
            am.eco_fee_multiplier
        FROM aircraft a
        JOIN aircraft_models am ON am.model_code = a.model_code
        WHERE a.save_id = %s
          AND (a.sold_day IS NULL OR a.sold_day = 0)
        ORDER BY a.aircraft_id
    """
    with get_connection() as yhteys:
        kursori = yhteys.cursor(dictionary=True)
        kursori.execute(sql, (save_id,))
        return kursori.fetchall() or []


def get_current_aircraft_upgrade_state(aircraft_id: int, upgrade_code: str = UPGRADE_CODE) -> dict:
    """Return the latest upgrade level entry for the aircraft."""
    sql = """
        SELECT level
        FROM aircraft_upgrades
        WHERE aircraft_id = %s
          AND upgrade_code = %s
        ORDER BY aircraft_upgrade_id DESC
        LIMIT 1
    """
    with get_connection() as yhteys:
        kursori = yhteys.cursor(dictionary=True)
        kursori.execute(sql, (aircraft_id, upgrade_code))
        row = kursori.fetchone()

    if not row:
        return {"level": 0}

    return {"level": int(row.get("level") or 0)}


def compute_effective_eco_multiplier(aircraft_id: int, base_eco_multiplier: float) -> float:
    """Compute the effective ECO multiplier after taking installed upgrades into account."""
    state = get_current_aircraft_upgrade_state(aircraft_id)
    level = int(state["level"])

    factor_per_level = Decimal("1.05")
    base_dec = Decimal(str(base_eco_multiplier))
    effective_multiplier = base_dec * (factor_per_level ** level)

    floor = Decimal("0.50")
    cap = Decimal("5.00")
    final_multiplier = max(floor, min(effective_multiplier, cap))
    return float(final_multiplier)


def calc_aircraft_upgrade_cost(aircraft_row: dict, next_level: int) -> Decimal:
    """Calculate the price of the next ECO level for the given aircraft row."""
    is_starter = (str(aircraft_row.get("category") or "").upper() == "STARTER")
    if is_starter:
        base = STARTER_BASE_COST
        growth = STARTER_GROWTH
    else:
        purchase_price = (
            aircraft_row.get("purchase_price_aircraft")
            or aircraft_row.get("purchase_price_model")
            or 0
        )
        base = max(NON_STARTER_MIN_BASE, (_to_dec(purchase_price) * NON_STARTER_BASE_PCT))
        growth = NON_STARTER_GROWTH

    cost = (base * (growth ** (_to_dec(next_level) - _to_dec(1)))).quantize(
        Decimal("0.01"), rounding=ROUND_HALF_UP
    )
    return cost


def apply_aircraft_upgrade(aircraft_id: int, installed_day: int) -> int:
    """Insert a new upgrade history row and return the new level."""
    state = get_current_aircraft_upgrade_state(aircraft_id)
    new_level = int(state["level"]) + 1

    sql = """
        INSERT INTO aircraft_upgrades
            (aircraft_id, upgrade_code, level, installed_day)
        VALUES
            (%s, %s, %s, %s)
    """
    with get_connection() as yhteys:
        kursori = yhteys.cursor()
        kursori.execute(
            sql,
            (
                int(aircraft_id),
                str(UPGRADE_CODE),
                int(new_level),
                int(installed_day),
            ),
        )
    return new_level


def get_effective_eco_for_aircraft(aircraft_id: int) -> float:
    """Fetch base ECO multiplier for the model and apply upgrades to get the effective multiplier."""
    sql = """
        SELECT am.eco_fee_multiplier
        FROM aircraft a
        JOIN aircraft_models am ON am.model_code = a.model_code
        WHERE a.aircraft_id = %s
    """
    with get_connection() as yhteys:
        kursori = yhteys.cursor()
        kursori.execute(sql, (aircraft_id,))
        row = kursori.fetchone()

    if row is None:
        base_eco = 1.0
    elif isinstance(row, dict):
        base_eco = row.get("eco_fee_multiplier", 1.0)
    else:
        base_eco = row[0] if row[0] is not None else 1.0

    return compute_effective_eco_multiplier(aircraft_id, base_eco)
