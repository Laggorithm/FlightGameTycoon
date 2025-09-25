#Error Codes:
#1 -- wrong input during upgrading (upgrade level possibly wasn't an int)
#2 -- error in connecting to sql database or fetching data from it
#3 -- error in list checker (problem with adding or checking for airplanes)
#4 -- list of airplanes is empty. Either initialization went wrong or append didn't work properly

from typing import List, Optional
from decimal import Decimal
from utils import get_connection

class Airplane:
    def __init__(
        self,
        aircraft_id: int,
        model_code: str,
        base_level: int,
        current_airport_ident: str,
        registration: str,
        nickname: Optional[str],
        acquired_day: int,
        purchase_price: Decimal,
        condition_percent: int,
        status: str,
        hours_flown: int,
        sold_day: Optional[int],
        sale_price: Optional[Decimal],
        save_id: int,
        base_id: Optional[int],
        model_name: Optional[str] = None,
    ):
        self.aircraft_id = aircraft_id
        self.model_code = model_code
        self.base_level = base_level
        self.current_airport_ident = current_airport_ident
        self.registration = registration
        self.nickname = nickname
        self.acquired_day = acquired_day
        self.purchase_price = purchase_price
        self.condition_percent = condition_percent
        self.status = status
        self.hours_flown = hours_flown
        self.sold_day = sold_day
        self.sale_price = sale_price
        self.save_id = save_id
        self.base_id = base_id
        # Lisäattribuutteja/takav. yhteensopivuus
        self.model_name = model_name
        self.ident = current_airport_ident  # alias vanhalle nimelle
        self.speed_day = None               # ei saraketta kannassa; pidetään attribuutti

class AircraftModel:
    def __init__(
        self,
        model_code: str,
        manufacturer: str,
        model_name: str,
        purchase_price: Decimal,
        base_cargo_kg: int,
        range_km: int,
        cruise_speed_kts: int,
        category: str,
        upkeep_price: Decimal,
        efficiency_score: int,
        co2_kg_per_km: Decimal,
        eco_class: str,
        eco_free_multiplier: Decimal,
    ):
        self.model_code = model_code
        self.manufacturer = manufacturer
        self.model_name = model_name
        self.purchase_price = purchase_price
        self.base_cargo_kg = base_cargo_kg
        self.range_km = range_km
        self.cruise_speed_kts = cruise_speed_kts
        self.category = category
        self.upkeep_price = upkeep_price
        self.efficiency_score = efficiency_score
        self.co2_kg_per_km = co2_kg_per_km
        self.eco_class = eco_class
        self.eco_free_multiplier = eco_free_multiplier

class AircraftUpgrade:
    def __init__(self, aircraft_upgrade_id: int, aircraft_id: int, upgrade_code: str, level: int, installed_day: int):
        self.aircraft_upgrade_id = aircraft_upgrade_id
        self.aircraft_id = aircraft_id
        self.upgrade_code = upgrade_code
        self.level = level
        self.installed_day = installed_day

# Globaali lista helppoon selailuun/tulostukseen
Aircrafts: List[Airplane] = []

def init_airplanes(save_id: int, include_sold: bool = False) -> List[Airplane]:
    """
    Lataa save_id:tä vastaavat koneet kannasta ja täyttää Aircrafts-listan.
    """
    global Aircrafts
    yhteys = get_connection()
    kursori = yhteys.cursor(dictionary=True)
    try:
        where_sold = "" if include_sold else "AND a.sold_day IS NULL"
        query = f"""
            SELECT
                a.aircraft_id, a.model_code, a.base_level, a.current_airport_ident, a.registration,
                a.nickname, a.acquired_day, a.purchase_price, a.condition_percent, a.status,
                a.hours_flown, a.sold_day, a.sale_price, a.save_id, a.base_id,
                am.model_name
            FROM aircraft a
            JOIN aircraft_models am ON a.model_code = am.model_code
            WHERE a.save_id = %s {where_sold}
            ORDER BY a.aircraft_id ASC
        """
        kursori.execute(query, (save_id,))
        rows = kursori.fetchall() or []

        Aircrafts = []
        for r in rows:
            plane = Airplane(
                aircraft_id=r["aircraft_id"],
                model_code=r["model_code"],
                base_level=int(r["base_level"] or 0),
                current_airport_ident=r["current_airport_ident"],
                registration=r["registration"],
                nickname=r.get("nickname"),
                acquired_day=int(r["acquired_day"] or 0),
                purchase_price=Decimal(str(r["purchase_price"] or "0")),
                condition_percent=int(r["condition_percent"] or 0),
                status=r["status"],
                hours_flown=int(r["hours_flown"] or 0),
                sold_day=(int(r["sold_day"]) if r.get("sold_day") is not None else None),
                sale_price=(Decimal(str(r["sale_price"])) if r.get("sale_price") is not None else None),
                save_id=int(r["save_id"]),
                base_id=(int(r["base_id"]) if r.get("base_id") is not None else None),
                model_name=r.get("model_name"),
            )
            Aircrafts.append(plane)
        return Aircrafts
    finally:
        kursori.close()
        yhteys.close()

def print_aircrafts():
    """
    Tulostaa Aircrafts-listalla olevat koneet.
    """
    if not Aircrafts:
        print("Sinulla ei ole vielä koneita.")
        return

    for i, plane in enumerate(Aircrafts, start=1):
        cond = int(plane.condition_percent or 0)
        cond_icon = "🟢" if cond > 80 else "🟡" if cond > 50 else "🔴"
        name = plane.model_name or plane.model_code
        nick = plane.nickname or ""
        print(f"\n✈ Plane #{i}")
        print(f"  {name} ({plane.registration}) '{nick}'")
        print(f"  Sijainti: {plane.current_airport_ident} | Kunto: {cond}% {cond_icon} | Status: {plane.status}")
        print(f"  Tunnit: {plane.hours_flown} h | Hankittu päivä: {plane.acquired_day}")
        if plane.sale_price is not None or plane.sold_day is not None:
            print(f"  Myyty: päivä {plane.sold_day}, hinta {plane.sale_price}")

def upgrade_airplane(aircraft_id: int, upgrade_code: str, level: int, current_day: int) -> None:
    """
    Lisää tai päivittää koneen upgrade-tason aircraft_upgrades-taulussa.
    """
    yhteys = get_connection()
    cur = yhteys.cursor()
    try:
        cur.execute(
            "SELECT aircraft_upgrade_id, level FROM aircraft_upgrades WHERE aircraft_id = %s AND upgrade_code = %s",
            (aircraft_id, upgrade_code),
        )
        row = cur.fetchone()
        if row:
            cur.execute(
                "UPDATE aircraft_upgrades SET level = %s, installed_day = %s WHERE aircraft_upgrade_id = %s",
                (level, current_day, row[0]),
            )
        else:
            cur.execute(
                "INSERT INTO aircraft_upgrades (aircraft_id, upgrade_code, level, installed_day) VALUES (%s, %s, %s, %s)",
                (aircraft_id, upgrade_code, level, current_day),
            )
        yhteys.commit()
    finally:
        try:
            cur.close()
        except Exception:
            pass
        yhteys.close()