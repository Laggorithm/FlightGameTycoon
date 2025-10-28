"""Database helpers for base ownership and upgrades."""

from typing import Dict, List

from utils import get_connection

from .common import _to_dec


def fetch_owned_bases(save_id: int) -> List[dict]:
    """Return the owned bases for a save ordered by name."""
    sql = """
        SELECT base_id, base_ident, base_name, purchase_cost
        FROM owned_bases
        WHERE save_id = %s
        ORDER BY base_name
    """
    with get_connection() as yhteys:
        kursori = yhteys.cursor(dictionary=True)
        kursori.execute(sql, (save_id,))
        return kursori.fetchall() or []


def fetch_base_current_level_map(base_ids: List[int]) -> Dict[int, str]:
    """Return a mapping of base_id -> latest upgrade code."""
    if not base_ids:
        return {}

    placeholders = ",".join(["%s"] * len(base_ids))
    sql = f"""
        SELECT bu.base_id, bu.upgrade_code
        FROM base_upgrades bu
        JOIN (
            SELECT base_id, MAX(base_upgrade_id) AS maxid
            FROM base_upgrades
            WHERE base_id IN ({placeholders})
            GROUP BY base_id
        ) x ON x.base_id = bu.base_id AND x.maxid = bu.base_upgrade_id
    """
    with get_connection() as yhteys:
        kursori = yhteys.cursor(dictionary=True)
        kursori.execute(sql, tuple(base_ids))
        rows = kursori.fetchall() or []
    return {r["base_id"]: r["upgrade_code"] for r in rows}


def insert_base_upgrade(base_id: int, next_level_code: str, cost, day: int) -> None:
    """Insert a base upgrade history row for the provided base."""
    sql = """
        INSERT INTO base_upgrades (base_id, upgrade_code, installed_day, upgrade_cost)
        VALUES (%s, %s, %s, %s)
    """
    with get_connection() as yhteys:
        kursori = yhteys.cursor()
        kursori.execute(
            sql,
            (
                int(base_id),
                str(next_level_code),
                int(day),
                float(_to_dec(cost)),
            ),
        )
