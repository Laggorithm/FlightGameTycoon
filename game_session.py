# Pelisession (GameSession) logiikka ja tietokantatoiminnot.
#
# Iso refaktorointi:
# - Korjattu NameError-ongelmat siirtämällä vakiot upgrade_config.py-tiedostoon
# - ECO-upgrade-funktiot ovat moduulitason apufunktioita (ei luokan sisällä), jolloin niitä
#   voidaan kutsua mistä tahansa ilman self-viittauksia.
# - Menuihin lisätty ikonit ja parempi visuaalinen ulkoasu.
# - Uuden pelin alkuun lisätty lyhyt tarinallinen intro, jota edetään Enterillä.
# - Lisätty kuukausilaskut (HQ + koneiden huolto) joka 30. päivä.
# - Pelin tavoite: selviä 666 päivää (konfiguroitavissa upgrade_configissa).
#
# Yhteysmuuttujat pidetään yhdenmukaisina:
#   yhteys = get_connection()
#   kursori = yhteys.cursor(dictionary=True)  # jos mahdollista, muuten yhteys.cursor()

import math
import random
import string
from typing import List, Optional, Dict, Set
from decimal import Decimal, ROUND_HALF_UP, getcontext
from datetime import datetime
from utils import get_connection
from airplane import init_airplanes, upgrade_airplane as db_upgrade_airplane

# Konfiguraatiot yhdessä paikassa
from upgrade_config import (
    # Palkkiot ja sakot
    TASK_REWARD_PER_KG,
    TASK_REWARD_PER_KM,
    TASK_MIN_REWARD,
    TASK_PENALTY_RATIO,

    # ECO-kertoimen rajat
    ECO_MULT_MIN,
    ECO_MULT_MAX,

    # ECO-upgrade perusparametrit ja luokkasäännöt
    UPGRADE_CODE,
    DEFAULT_ECO_FACTOR_PER_LEVEL,
    DEFAULT_ECO_FLOOR,
    ECO_CLASS_RULES,

    # Upgrade-kustannukset
    STARTER_BASE_COST,
    STARTER_GROWTH,
    NON_STARTER_BASE_PCT,
    NON_STARTER_MIN_BASE,
    NON_STARTER_GROWTH,

    # Talous ja ylläpito
    HQ_MONTHLY_FEE,
    MAINT_PER_AIRCRAFT,
    STARTER_MAINT_DISCOUNT,

    # Peli-”tavoite”
    SURVIVAL_TARGET_DAYS,
)

# Decimal-laskennan tarkkuus – rahalaskennassa on hyvä varata skaalaa
getcontext().prec = 28


# ---------- Yleiset apurit (moduulitaso) ----------

def _to_dec(x):
    """
    Turvallinen muunnos Decimal-muotoon.
    - None -> Decimal('0')
    - Muut numeeriset arvot muutetaan str():n kautta tarkkuuden säilyttämiseksi.
    """
    return x if isinstance(x, Decimal) else Decimal(str(x if x is not None else 0))


def _icon_title(title: str) -> None:
    """
    Pieni visuaalinen apu valikko-otsikoille.
    """
    bar = "═" * (len(title) + 2)
    print(f"\n╔{bar}╗")
    print(f"║ {title} ║")
    print(f"╚{bar}╝")


# ---------- MIGRAATIO: aircraft_upgrades uudet sarakkeet ----------

def migrate_add_eco_columns_to_aircraft_upgrades() -> None:
    """
    Lisää aircraft_upgrades-tauluun sarakkeet (jos puuttuvat):
      - eco_factor_per_level DOUBLE NOT NULL DEFAULT <DEFAULT_ECO_FACTOR_PER_LEVEL>
      - eco_floor DOUBLE NOT NULL DEFAULT <DEFAULT_ECO_FLOOR>
    Lisäksi luo hyödylliset indeksit:
      - idx_air_upg_air_code (aircraft_id, upgrade_code)
      - idx_air_upg_day (installed_day)
    """
    # Huom: käytetään upgrade_config.py:n oletusarvoja taulun defaultteihin
    default_factor = str(float(DEFAULT_ECO_FACTOR_PER_LEVEL))
    default_floor = str(float(DEFAULT_ECO_FLOOR))

    with get_connection() as yhteys:
        kursori = yhteys.cursor(dictionary=True)

        # 1) Haetaan olemassa olevat sarakkeet
        kursori.execute("""
            SELECT COLUMN_NAME
            FROM information_schema.COLUMNS
            WHERE TABLE_SCHEMA = DATABASE()
              AND TABLE_NAME = 'aircraft_upgrades'
        """)
        existing_cols: Set[str] = {row["COLUMN_NAME"] for row in (kursori.fetchall() or [])}

        # 2) Lisätään puuttuvat sarakkeet konfigin oletuksilla
        if "eco_factor_per_level" not in existing_cols:
            kursori.execute(f"""
                ALTER TABLE aircraft_upgrades
                ADD COLUMN eco_factor_per_level DOUBLE NOT NULL DEFAULT {default_factor}
            """)
        if "eco_floor" not in existing_cols:
            kursori.execute(f"""
                ALTER TABLE aircraft_upgrades
                ADD COLUMN eco_floor DOUBLE NOT NULL DEFAULT {default_floor}
            """)

        # 3) Luodaan puuttuvat indeksit
        kursori.execute("""
            SELECT INDEX_NAME
            FROM information_schema.STATISTICS
            WHERE TABLE_SCHEMA = DATABASE()
              AND TABLE_NAME = 'aircraft_upgrades'
        """)
        existing_idx: Set[str] = {row["INDEX_NAME"] for row in (kursori.fetchall() or [])}

        if "idx_air_upg_air_code" not in existing_idx:
            kursori.execute("""
                CREATE INDEX idx_air_upg_air_code
                ON aircraft_upgrades (aircraft_id, upgrade_code)
            """)
        if "idx_air_upg_day" not in existing_idx:
            kursori.execute("""
                CREATE INDEX idx_air_upg_day
                ON aircraft_upgrades (installed_day)
            """)

# ---------- DB-hakufunktiot (moduulitaso) ----------

def fetch_player_aircrafts_with_model_info(save_id: int) -> List[dict]:
    """
    Hae pelaajan (myymättömät) koneet yhdistettynä malleihin.
    Palautus: list(dict), jossa mm.
      - aircraft_id, registration, model_code
      - model_name, category
      - purchase_price_aircraft (todellinen ostohinta jos tallessa)
      - purchase_price_model (mallin listahinta – fallback)
      - eco_fee_multiplier (mallin perus-eco-kerroin; voi olla negatiivinen)
      - eco_class (A, B, C, D, E, tms.)
    """
    sql = """
        SELECT
            a.aircraft_id,
            a.registration,
            a.model_code,
            am.model_name,
            am.category,
            a.purchase_price  AS purchase_price_aircraft,
            am.purchase_price AS purchase_price_model,
            am.eco_fee_multiplier,
            am.eco_class
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
    """
    Palauttaa koneen tuoreimman ECO-upgrade-tilan dict-muodossa:
      {
        "level": int,                     # nykyinen taso (0 jos ei päivityksiä)
        "eco_factor_per_level": Decimal,  # varaus: per-tason delta override (ei pakollinen käyttö)
        "eco_floor": Decimal              # ekokertoimen alaraja (klampataan luokkakohtaiseen minimiin nähden)
      }
    Jos historiarivejä ei ole, palauttaa oletukset (0, DEFAULT_ECO_FACTOR_PER_LEVEL, DEFAULT_ECO_FLOOR).
    """
    sql = """
        SELECT level, eco_factor_per_level, eco_floor
        FROM aircraft_upgrades
        WHERE aircraft_id = %s
          AND upgrade_code = %s
        ORDER BY aircraft_upgrade_id DESC
        LIMIT 1
    """
    with get_connection() as yhteys:
        kursori = yhteys.cursor(dictionary=True)
        kursori.execute(sql, (aircraft_id, upgrade_code))
        r = kursori.fetchone()

    if not r:
        return {
            "level": 0,
            "eco_factor_per_level": DEFAULT_ECO_FACTOR_PER_LEVEL,
            "eco_floor": DEFAULT_ECO_FLOOR,
        }

    return {
        "level": int(r.get("level") or 0),
        "eco_factor_per_level": _to_dec(r.get("eco_factor_per_level") or DEFAULT_ECO_FACTOR_PER_LEVEL),
        "eco_floor": _to_dec(r.get("eco_floor") or DEFAULT_ECO_FLOOR),
    }

def compute_effective_eco_multiplier(aircraft_id: int, base_eco_multiplier) -> float:
    """
    Lasketaan efektiivinen eco-kerroin additiivisella mallilla eco_classin perusteella:
      - Haetaan koneen eco_class mallista (A–E)
      - Luokkakohtaiset delta/min/max tulevat upgrade_config.ECO_CLASS_RULES:stä
      - effective = clamp(base + level * delta, min_bound, max_bound)

    Huom:
      - base_eco_multiplier voi olla negatiivinen → päivitykset voivat nostaa sen nollan yli.
      - eco_floor huomioidaan vain jos se on negatiivinen (eli halutaan rajoittaa,
        kuinka negatiiviseksi arvo voi mennä). Jos eco_floor >= 0, sitä ei käytetä
        jotta negatiivinen perusarvo näkyy eikä klampata ennen aikojaan nollaan.
    """
    # 1) Turvallinen base (sallitaan negatiivinen)
    try:
        base = float(base_eco_multiplier)
    except (TypeError, ValueError):
        base = 0.0

    # 2) Lue nykyinen taso ja mahdollinen negatiivinen floor
    state = get_current_aircraft_upgrade_state(aircraft_id, UPGRADE_CODE) or {}
    try:
        level = int(state.get("level", 0) or 0)
    except (TypeError, ValueError):
        level = 0
    if level < 0:
        level = 0

    try:
        floor_from_state = float(state.get("eco_floor", float(DEFAULT_ECO_FLOOR)) or float(DEFAULT_ECO_FLOOR))
    except (TypeError, ValueError):
        floor_from_state = float(DEFAULT_ECO_FLOOR)

    # 3) Haetaan eco_class tälle koneelle DB:stä
    sql_class = """
        SELECT am.eco_class
        FROM aircraft a
        JOIN aircraft_models am ON am.model_code = a.model_code
        WHERE a.aircraft_id = %s
    """
    with get_connection() as yhteys:
        kursori = yhteys.cursor()
        kursori.execute(sql_class, (aircraft_id,))
        r = kursori.fetchone()

    if r is None:
        eco_class = "DEFAULT"
    elif isinstance(r, dict):
        eco_class = (r.get("eco_class") or "DEFAULT")
    else:  # tuple
        eco_class = (r[0] if r and r[0] is not None else "DEFAULT")

    eco_class = str(eco_class).upper()

    # 4) Luokkakohtaiset säännöt konfigista
    rules = ECO_CLASS_RULES.get(eco_class, ECO_CLASS_RULES["DEFAULT"])
    class_delta = float(rules["delta"])
    class_min = float(rules["min"])
    class_max = float(rules["max"])

    # 5) Alaraja: käytä eco_flooria vain jos se on negatiivinen; muuten älä estä negatiivisia arvoja
    if floor_from_state < 0.0:
        min_bound = max(class_min, floor_from_state)  # rajoita negatiivisuutta luokan minimin ja floorin välillä
    else:
        min_bound = class_min  # salli luokan mukaiset negatiiviset arvot

    max_bound = class_max
    if min_bound > max_bound:
        min_bound = max_bound  # varotoimi

    # 6) Lasketaan additiivisesti ja klampataan
    effective = base + (level * class_delta)

    if effective < min_bound:
        effective = min_bound
    if effective > max_bound:
        effective = max_bound

    return float(effective)

def preview_next_level_eco(aircraft_id: int) -> dict:
    """
    Palauttaa esikatselun nyky- ja seuraavan tason eco-arvoille ilman että muutetaan kantaa.
    {
      "current_level": int,
      "current_eco": float,
      "next_level": int,
      "next_eco": float
    }
    Käyttö: näytä valikossa "Eco: {current_eco:.2f} → {next_eco:.2f}"
    """
    # 1) Hae mallin base_eco ja eco_class yhdellä kyselyllä
    sql = """
        SELECT am.eco_fee_multiplier, am.eco_class
        FROM aircraft a
        JOIN aircraft_models am ON am.model_code = a.model_code
        WHERE a.aircraft_id = %s
    """
    with get_connection() as yhteys:
        kursori = yhteys.cursor(dictionary=True)
        kursori.execute(sql, (aircraft_id,))
        row = kursori.fetchone() or {}

    # Turvalliset perusarvot
    try:
        base = float(row.get("eco_fee_multiplier"))
    except (TypeError, ValueError):
        base = 0.0
    eco_class = str(row.get("eco_class") or "DEFAULT").upper()

    # 2) Lue nykyinen ECO-upgrade -tila (taso ja floor)
    state = get_current_aircraft_upgrade_state(aircraft_id, UPGRADE_CODE) or {}
    try:
        current_level = int(state.get("level", 0) or 0)
    except (TypeError, ValueError):
        current_level = 0
    if current_level < 0:
        current_level = 0

    # eco_floor kantaa klampissa vain, jos negatiivinen (ettei nollalattia tukahduta parannusta)
    from upgrade_config import ECO_CLASS_RULES, DEFAULT_ECO_FLOOR  # paikallinen import selkeyden vuoksi
    try:
        floor_from_state = float(state.get("eco_floor", float(DEFAULT_ECO_FLOOR)) or float(DEFAULT_ECO_FLOOR))
    except (TypeError, ValueError):
        floor_from_state = float(DEFAULT_ECO_FLOOR)

    rules = ECO_CLASS_RULES.get(eco_class, ECO_CLASS_RULES["DEFAULT"])
    class_delta = float(rules["delta"])
    class_min = float(rules["min"])
    class_max = float(rules["max"])

    # Laske yhdistetty minimi: käytä eco_flooria vain jos se on negatiivinen
    if floor_from_state < 0.0:
        min_bound = max(class_min, floor_from_state)
    else:
        min_bound = class_min
    max_bound = class_max
    if min_bound > max_bound:
        min_bound = max_bound  # varotoimi

    # 3) Laske eco nykyiselle tasolle ja seuraavalle (additiivinen malli)
    def _clamp(x: float) -> float:
        if x < min_bound:
            return min_bound
        if x > max_bound:
            return max_bound
        return x

    current_eco = _clamp(base + current_level * class_delta)
    next_eco = _clamp(base + (current_level + 1) * class_delta)

    return {
        "current_level": current_level,
        "current_eco": float(current_eco),
        "next_level": current_level + 1,
        "next_eco": float(next_eco),
    }

def calc_aircraft_upgrade_cost(aircraft_row: dict, next_level: int) -> Decimal:
    """
    Laske seuraavan ECO-tason hinta annetulle koneelle konfigin kaavoilla.
    - STARTER-kategoria: STARTER_BASE_COST * STARTER_GROWTH^(next_level-1)
    - Muut: max(NON_STARTER_MIN_BASE, NON_STARTER_BASE_PCT * ostohinta) * NON_STARTER_GROWTH^(next_level-1)
      (ostohinta = a.purchase_price tai am.purchase_price fallback)
    Palauttaa Desimalin (2 desimaalin pyöristyksellä).
    """
    # 1) Luokitellaan onko STARTER
    is_starter = (str(aircraft_row.get("category") or "").upper() == "STARTER")
    if is_starter:
        base = STARTER_BASE_COST
        growth = STARTER_GROWTH
    else:
        # 2) Määritä ostohinnan pohja ja vähintään minimipohja configista
        purchase_price = aircraft_row.get("purchase_price_aircraft") or aircraft_row.get("purchase_price_model") or 0
        base = max(NON_STARTER_MIN_BASE, (_to_dec(purchase_price) * NON_STARTER_BASE_PCT))
        growth = NON_STARTER_GROWTH

    # 3) Juuri tämän tason hinta (ei kumulatiivinen). next_level alkaa 1:stä.
    cost = (base * (growth ** (_to_dec(next_level) - _to_dec(1)))).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
    return cost

def apply_aircraft_upgrade(
    aircraft_id: int,
    installed_day: int,
    cost,  # ei käytetä suoraan tässä; kassa veloitetaan kutsuvassa koodissa
    upgrade_code: str = UPGRADE_CODE,
    eco_factor_per_level=None,
    eco_floor=None,
) -> int:
    """
    Kirjaa uuden ECO-upgrade -rivin historiaan:
      - level = edellinen_taso + 1
      - installed_day = annettu päivä
      - eco_factor_per_level ja eco_floor:
          - jos parametreja ei anneta, luetaan nykytilasta (joka palauttaa oletukset jos riviä ei ole)
          - additiivisessa mallissa eco_floor toimii minimi-alarajana
          - eco_factor_per_level on varaus konekohtaiselle delta-override -arvolle (optional)
    Palauttaa: new_level (int).
    """
    # 1) Luetaan nykyinen tila (sis. oletusparametrit jos ei vielä rivejä)
    state = get_current_aircraft_upgrade_state(aircraft_id, upgrade_code)
    new_level = int(state["level"]) + 1

    # 2) Käytetään parametreina annettuja eco-arvoja, tai nykytilaa jos None
    factor = state["eco_factor_per_level"] if eco_factor_per_level is None else _to_dec(eco_factor_per_level)
    floor = state["eco_floor"] if eco_floor is None else _to_dec(eco_floor)

    # 3) Lisätään historian rivi
    sql = """
        INSERT INTO aircraft_upgrades
            (aircraft_id, upgrade_code, level, installed_day, eco_factor_per_level, eco_floor)
        VALUES
            (%s, %s, %s, %s, %s, %s)
    """
    with get_connection() as yhteys:
        kursori = yhteys.cursor()
        kursori.execute(sql, (
            int(aircraft_id),
            str(upgrade_code),
            int(new_level),
            int(installed_day),
            float(factor),
            float(floor),
        ))
    return new_level


def get_effective_eco_for_aircraft(aircraft_id: int) -> float:
    """
    Hakee mallin base eco -kertoimen (voi olla negatiivinen) ja soveltaa päivityksiä.
    Palauttaa efektiivisen eco-kertoimen floattina.

    Huom:
      - eco_class haetaan compute_effective_eco_multiplier -funktion sisällä erikseen.
    """
    sql = """
        SELECT am.eco_fee_multiplier
        FROM aircraft a
        JOIN aircraft_models am ON am.model_code = a.model_code
        WHERE a.aircraft_id = %s
    """
    with get_connection() as yhteys:
        kursori = yhteys.cursor()
        kursori.execute(sql, (aircraft_id,))
        r = kursori.fetchone()

    # Talletetaan base_eco (tuetaan tuple- ja dict-palautuksia)
    if r is None:
        base_eco = float(DEFAULT_ECO_FLOOR)
    elif isinstance(r, dict):
        base_eco = r.get("eco_fee_multiplier", float(DEFAULT_ECO_FLOOR))
    else:  # assume tuple
        base_eco = r[0] if r[0] is not None else float(DEFAULT_ECO_FLOOR)
    return compute_effective_eco_multiplier(aircraft_id, base_eco)


    # ---------- Base upgrade ----------
def fetch_base_current_level_map(base_ids: List[int]) -> Dict[int, str]:
    """
    Palauttaa { base_id: viimeisin upgrade_code } (SMALL/MEDIUM/LARGE/HUGE).
    Jos tukikohdalla ei ole päivityksiä, sitä ei ole dictissä (oletetaan SMALL).
    """
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
        rivit = kursori.fetchall() or []
    return {r["base_id"]: r["upgrade_code"] for r in rivit}

def fetch_base_current_level_map(base_ids: List[int]) -> Dict[int, str]:
    """
    Palauttaa { base_id: viimeisin upgrade_code } (SMALL/MEDIUM/LARGE/HUGE).
    Jos tukikohdalla ei ole päivityksiä, sitä ei ole dictissä (oletetaan SMALL).
    """
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
        rivit = kursori.fetchall() or []
    return {r["base_id"]: r["upgrade_code"] for r in rivit}


def insert_base_upgrade(base_id: int, next_level_code: str, cost, day: int) -> None:
    """
    Lisää base_upgrades-historian rivin annetulle tukikohdalle.
    """
    sql = """
        INSERT INTO base_upgrades (base_id, upgrade_code, installed_day, upgrade_cost)
        VALUES (%s, %s, %s, %s)
    """
    with get_connection() as yhteys:
        kursori = yhteys.cursor()
        kursori.execute(sql, (int(base_id), str(next_level_code), int(day), float(_to_dec(cost))))

# ---------- GameSession-luokka ----------

class GameSession:
    """
    GameSession kapseloi yhden game_saves-rivin ja siihen liittyvän tilan.
    Vastaa mm. kassasta, päivästä, valikoista ja tehtävien/upgradejen käytöstä.
    """

    def __init__(
        self,
        save_id: int,
        current_day: Optional[int] = None,
        player_name: Optional[str] = None,
        cash: Optional[Decimal] = None,
        status: Optional[str] = None,
        rng_seed: Optional[int] = None,
        difficulty: Optional[str] = None,
    ):
        # Tallennetaan konstruktorin parametrit – puuttuvat täydennetään kannasta
        self.save_id = int(save_id)
        self.player_name = player_name
        self.cash = _to_dec(cash) if cash is not None else None
        self.current_day = int(current_day) if current_day is not None else None
        self.status = status
        self.rng_seed = rng_seed
        self.difficulty = difficulty or "NORMAL"

        # Täydennetään puuttuvat kentät kannasta
        self._refresh_save_state()

    # ---------- Luonti / Lataus ----------

    @classmethod
    def new_game(
        cls,
        name: str,
        cash: float = 300000.0,
        show_intro: bool = True,
        rng_seed: Optional[int] = None,
        status: str = "ACTIVE",
        default_difficulty: str = "NORMAL",
    ) -> "GameSession":
        """
        Luo uuden tallennuksen ja käynnistää pelin.
        Vaiheet:
          1) game_saves-rivi luodaan (päivä 1)
          2) (optio) Intro-tarina Enterillä eteenpäin
          3) Pelaaja valitsee ensimmäisen tukikohdan, lisätään SMALL-upgrade
          4) Iso-isä lahjoittaa STARTER-koneen (DC3FREE)
        """
        # Varmistetaan, että migraatio on ajettu (sarakkeet olemassa)
        try:
            migrate_add_eco_columns_to_aircraft_upgrades()
        except Exception:
            # ei kaadeta peliä, jos migraatio epäonnistuu – voidaan ajaa myöhemmin
            pass

        yhteys = get_connection()
        kursori = yhteys.cursor()
        try:
            start_day = 1
            now = datetime.utcnow()
            kursori.execute(
                """
                INSERT INTO game_saves
                  (player_name, current_day, cash, difficulty, status, rng_seed, created_at, updated_at)
                VALUES
                  (%s, %s, %s, %s, %s, %s, %s, %s)
                """,
                (
                    name,
                    start_day,
                    _to_dec(cash),
                    default_difficulty,
                    status,
                    rng_seed,
                    now,
                    now,
                ),
            )
            save_id = kursori.lastrowid
            yhteys.commit()
        except Exception as err:
            yhteys.rollback()
            raise RuntimeError(f"Uuden pelin luonti epäonnistui: {err}") from err
        finally:
            try:
                kursori.close()
            except Exception:
                pass
            yhteys.close()

        session = cls(save_id=save_id)

        if show_intro:
            session._show_intro_story()

        # Ensimmäinen tukikohta + lahjakone (STARTER)
        session._first_time_base_and_gift_setup(starting_cash=_to_dec(cash))

        return session

    @classmethod
    def load(cls, save_id: int) -> "GameSession":
        """
        Lataa olemassa olevan tallennuksen ID:llä.
        """
        return cls(save_id=save_id)

    # ---------- Intro / Tarina ----------

    def _show_intro_story(self) -> None:
        """
        Kevyt tarina, jota edetään Enterillä.
        Tavoite: selviä 666 päivää – 30 päivän välein maksat laskut (HQ + koneiden huolto).
        """
        pages = [
            "Yö on pimeä ja terminaalin neonit hehkuvat. Perit vanhan lentofirman nimen ja velkasalkun.",
            "Iso-isäsi jätti sinulle yhden DC-3:n muistoksi – se on kestänyt vuosikymmeniä, kestäisikö vielä yhden?",
            f"Tavoitteesi: pidä firma hengissä {SURVIVAL_TARGET_DAYS} päivää. Joka 30. päivä maksat palkat ja koneiden huollot.",
            "Toivottavasti kaikki menee hyvin...",
            "Pilvet raottuvat: markkinat odottavat reittejä, rahtia ja rohkeita päätöksiä. Aika nousta.",
        ]
        _icon_title("Prologi")
        for i, page in enumerate(pages, start=1):
            print(f"📖 {page}")
            input("↩︎ Enter jatkaa...")

    # ---------- Ensimmäinen tukikohta + lahjakone ----------

    def _first_time_base_and_gift_setup(self, starting_cash: Decimal) -> None:
        """
        Valitse ensimmäinen tukikohta (EFHK/LFPG/KJFK).
        Hinta on 30/50/70 % aloituskassasta.
        Luodaan owned_bases ja base_upgrades(SMALL), lisätään lahjakone (STARTER: DC3FREE).
        """
        options = [
            {"icao": "EFHK", "name": "Helsinki-Vantaa", "factor": Decimal("0.30")},
            {"icao": "LFPG", "name": "Paris Charles de Gaulle", "factor": Decimal("0.50")},
            {"icao": "KJFK", "name": "New York JFK", "factor": Decimal("0.70")},
        ]
        for o in options:
            o["price"] = (starting_cash * o["factor"]).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)

        _icon_title("Ensimmäinen tukikohta")
        for i, o in enumerate(options, start=1):
            print(f"{i}) 🛫 {o['name']} ({o['icao']}) | 💶 Hinta: {self._fmt_money(o['price'])}")

        # Valinnan validointi
        while True:
            sel = input("Valinta numerolla (1-3): ").strip()
            try:
                idx = int(sel)
                if 1 <= idx <= len(options):
                    break
                print("⚠️  Valitse numero 1-3.")
            except ValueError:
                print("⚠️  Anna numero 1-3.")

        chosen = options[idx - 1]
        base_ident = chosen["icao"]
        base_name = chosen["name"]
        base_cost = chosen["price"]

        if self.cash < base_cost:
            raise RuntimeError(
                f"Kassa ei riitä tukikohtaan {base_ident}. Tarvitaan {self._fmt_money(base_cost)}, "
                f"mutta kassassa on {self._fmt_money(self.cash)}."
            )

        base_id = self._create_owned_base_and_small_upgrade_tx(
            base_ident=base_ident,
            base_name=base_name,
            purchase_cost=base_cost,
        )
        print(f"✅ Ostit tukikohdan: {base_name} ({base_ident}) hintaan {self._fmt_money(base_cost)}.")

        # STARTER-lahjakone
        self._insert_gift_aircraft_tx(
            model_code="DC3FREE",
            current_airport_ident=base_ident,
            base_id=base_id,
            nickname="Iso-isän DC-3",
        )
        print("🎁 Iso-isä lahjoitti Douglas DC-3 -koneen. Onnea matkaan!")

    # ---------- Päävalikko ----------

    def main_menu(self) -> None:
        """
        Päävalikon looppi – laivasto, kauppa, upgrade, tehtävät ja ajan kulku.
        """
        while True:
            home_ident = self._get_primary_base_ident() or "-"
            print("\n" + "🛩️  Päävalikko".center(60, " "))
            print("─" * 60)
            print(
                f"📅 Päivä: {self.current_day:<4} | 💶 Kassa: {self._fmt_money(self.cash):<14} | 👤 Pelaaja: {self.player_name:<16} | 🏢 Tukikohta: {home_ident}")
            print("1) 📋 Listaa koneet")
            print("2) 🛒 Kauppa (osta kone)")
            print("3) ♻️  Päivitä konetta (ECO)")
            print("4) 📦 Aktiiviset tehtävät")
            print("5) ➕ Aloita uusi tehtävä")
            print("6) ⏭️  Seuraava päivä")
            # Uudet pikakelausvaihtoehdot
            print("7) ⏩ Etene X päivää")
            print("8) 🎯 Etene kunnes ensimmäinen kone palaa")
            print("0) 🚪 Poistu")

            choice = input("Valinta: ").strip()

            if choice == "1":
                self.list_aircraft()

            elif choice == "2":
                self.shop_menu()

            elif choice == "3":
                self.upgrade_menu()

            elif choice == "4":
                self.show_active_tasks()

            elif choice == "5":
                self.start_new_task()

            elif choice == "6":
                # Yksi päivä eteenpäin (interaktiivinen: tulostaa ja pysäyttää Enteriin)
                self.advance_to_next_day()
                # Pelitilan tarkastelu (voitto/konkurssi)
                if self.status == "BANKRUPT":
                    print("💀 Yritys meni konkurssiin. Peli päättyy.")
                    break
                if self.current_day >= SURVIVAL_TARGET_DAYS and self.status == "ACTIVE":
                    print(f"🏆 Onnea! Selvisit {SURVIVAL_TARGET_DAYS} päivää. Voitit pelin!")
                    self._set_status("VICTORY")
                    break

            elif choice == "7":
                # Pikakelaus: eteneminen X päivää (hiljaisesti)
                try:
                    n = int(input("Kuinka monta päivää? ").strip())
                except ValueError:
                    print("⚠️  Virheellinen numero.")
                else:
                    self.fast_forward_days(n)
                    # Pelitilan tarkastelu
                    if self.status == "BANKRUPT":
                        print("💀 Yritys meni konkurssiin. Peli päättyy.")
                        break
                    if self.current_day >= SURVIVAL_TARGET_DAYS:
                        # Jos pikakelaus ei jo asettanut VICTORY-tilaa, tee se nyt
                        if self.status == "ACTIVE":
                            self._set_status("VICTORY")
                        print(f"🏆 Onnea! Selvisit {SURVIVAL_TARGET_DAYS} päivää. Voitit pelin!")
                        break

            elif choice == "8":
                # Pikakelaus: eteneminen kunnes ensimmäinen kone palaa (hiljaisesti)
                try:
                    cap_str = input("↩︎ Enter aloittaa pikakelauksen.").strip()
                    cap = int(cap_str) if cap_str else 365
                except ValueError:
                    print("⚠️  Virheellinen numero.")
                else:
                    self.fast_forward_until_first_return(max_days=cap)
                    # Pelitilan tarkastelu
                    if self.status == "BANKRUPT":
                        print("💀 Yritys meni konkurssiin. Peli päättyy.")
                        break
                    if self.current_day >= SURVIVAL_TARGET_DAYS:
                        if self.status == "ACTIVE":
                            self._set_status("VICTORY")
                        print(f"🏆 Onnea! Selvisit {SURVIVAL_TARGET_DAYS} päivää. Voitit pelin!")
                        break

            elif choice == "0":
                print("👋 Heippa!")
                break

            else:
                print("⚠️  Virheellinen valinta.")

    # ---------- Listaus ----------

    def list_aircraft(self) -> None:
        """
        Listaa kaikki aktiiviset koneet ja näytä perusinfot + (ECO)upgradet.
        """
        planes = init_airplanes(self.save_id, include_sold=False)
        if not planes:
            print("ℹ️  Sinulla ei ole vielä koneita.")
            input("\n↩︎ Enter jatkaaksesi...")
            return

        # Haetaan nykyiset ECO-tasot
        upgrade_levels = self._fetch_upgrade_levels([p.aircraft_id for p in planes])

        _icon_title("Laivasto")
        for i, p in enumerate(planes, start=1):
            lvl = upgrade_levels.get(p.aircraft_id, 0)
            eco_now = get_effective_eco_for_aircraft(p.aircraft_id)
            print(f"\n#{i:>2} ✈️  {(getattr(p, 'model_name', None) or p.model_code)} ({p.registration}) @ {p.current_airport_ident}")
            print(f"   💶 Ostohinta: {self._fmt_money(p.purchase_price)} | 🔧 Kunto: {p.condition_percent}% | 🧭 Status: {p.status}")
            print(f"   ⏱️ Tunnit: {p.hours_flown} h | 📅 Hankittu päivä: {p.acquired_day}")
            print(f"   ♻️  ECO-taso: {lvl} | Efektiivinen eco-kerroin: x {eco_now:.2f}")

        input("\n↩︎ Enter jatkaaksesi...")

    # ---------- Kauppa ----------

    def shop_menu(self) -> None:
        """
        Lista myynnissä olevista konemalleista tukikohdan edistymisen mukaan.
        STARTER-kategoriaa ei koskaan näytetä.
        """
        models = self._fetch_aircraft_models_by_base_progress()
        if not models:
            print("ℹ️  Kaupassa ei ole malleja nykyisellä tukikohdan tasolla.")
            input("\n↩︎ Enter jatkaaksesi...")
            return

        _icon_title("Kauppa")
        for idx, m in enumerate(models, start=1):
            price = _to_dec(m["purchase_price"])
            print(
                f"{idx:>2}) 🛒 {m['manufacturer']} {m['model_name']} ({m['model_code']}) | "
                f"💶 {self._fmt_money(price)} | 📦 {m['base_cargo_kg']} kg | 🧭 {m['cruise_speed_kts']} kts | 🏷️ {m['category']}"
            )

        sel = input("\nValitse ostettava malli numerolla (tyhjä = peruuta): ").strip()
        if not sel:
            return
        try:
            sel_i = int(sel)
            if not (1 <= sel_i <= len(models)):
                print("⚠️  Virheellinen valinta.")
                return
        except ValueError:
            print("⚠️  Virheellinen valinta.")
            return

        model = models[sel_i - 1]
        price = _to_dec(model["purchase_price"])
        if self.cash < price:
            print(f"❌ Kassa ei riitä. Tarvitset {self._fmt_money(price)}, sinulla on {self._fmt_money(self.cash)}.")
            input("\n↩︎ Enter jatkaaksesi...")
            return

        default_base = self._get_primary_base()
        default_airport_ident = default_base["base_ident"] if default_base else "EFHK"
        current_airport_ident = input(f"Valitse kenttä (ICAO/IATA) [{default_airport_ident}]: ").strip().upper() or default_airport_ident

        base_id_for_plane = self._get_base_id_by_ident(current_airport_ident) or (default_base["base_id"] if default_base else None)

        registration = input("Syötä rekisteri (tyhjä = generoidaan): ").strip().upper()
        if not registration:
            registration = self._generate_registration()
            print(f"🔖 Luotiin rekisteri: {registration}")

        nickname = input("Anna lempinimi (optional): ").strip() or None

        confirm = input(
            f"Vahvista osto: {model['manufacturer']} {model['model_name']} hintaan {self._fmt_money(price)} (k/e): "
        ).strip().lower()
        if confirm != "k":
            print("❎ Peruutettu.")
            return

        ok = self._purchase_aircraft_tx(
            model_code=model["model_code"],
            current_airport_ident=current_airport_ident,
            registration=registration,
            nickname=nickname,
            purchase_price=price,
            base_id=base_id_for_plane,
        )
        if ok:
            print(f"✅ Osto valmis. Kone {registration} lisätty laivastoon.")
        else:
            print("❌ Osto epäonnistui.")
        input("\n↩︎ Enter jatkaaksesi...")

    # ---------- Päivitykset: Base & ECO ----------

    def upgrade_aircraft_menu(self) -> None:
        """
        Interaktiivinen valikko ECO-päivityksille.
        Näyttää: nykyinen taso, hinta seuraavalle tasolle, eco-kerroin nyt -> seuraava.
        """
        aircrafts = fetch_player_aircrafts_with_model_info(self.save_id)
        if not aircrafts:
            print("ℹ️  Sinulla ei ole vielä koneita.")
            input("\n↩︎ Enter jatkaaksesi...")
            return

        def _eco_preview_for_levels(row: dict, state: dict, level_now: int, level_next: int) -> tuple[float, float]:
            # Base-eco mallista (voi olla negatiivinen). Jos puuttuu, oletus 0.0
            try:
                base_eco = float(row.get("eco_fee_multiplier"))
            except (TypeError, ValueError):
                base_eco = 0.0

            # ECO-luokka ja säännöt
            eco_class = str(row.get("eco_class") or "DEFAULT").upper()
            rules = ECO_CLASS_RULES.get(eco_class, ECO_CLASS_RULES["DEFAULT"])
            class_delta = float(rules["delta"])
            class_min = float(rules["min"])
            class_max = float(rules["max"])

            # Floor vain jos negatiivinen (ei tukahduteta negatiivista perusarvoa nollaan)
            try:
                floor_val = float(state.get("eco_floor"))
            except (TypeError, ValueError):
                floor_val = 0.0
            if floor_val < 0.0:
                min_bound = max(class_min, floor_val)
            else:
                min_bound = class_min

            def _clamp(x: float) -> float:
                if x < min_bound:
                    return min_bound
                if x > class_max:
                    return class_max
                return x

            current_eco = _clamp(base_eco + level_now * class_delta)
            next_eco = _clamp(base_eco + level_next * class_delta)
            return float(current_eco), float(next_eco)

        _icon_title("ECO-päivitykset")
        menu_rows = []
        for idx, row in enumerate(aircrafts, start=1):
            aircraft_id = row["aircraft_id"]
            state = get_current_aircraft_upgrade_state(aircraft_id, UPGRADE_CODE)
            cur_level = int(state.get("level") or 0)
            if cur_level < 0:
                cur_level = 0
            next_level = cur_level + 1

            factor = state.get(
                "eco_factor_per_level")  # varaus mahdolliselle override-deltalle (talletetaan historiaan)
            floor = state.get("eco_floor")

            # Lasketaan esikatselun eco-arvot
            current_eco, new_eco = _eco_preview_for_levels(row, state, cur_level, next_level)

            cost = calc_aircraft_upgrade_cost(row, next_level)
            model_name = row.get("model_name") or row.get("model_code")
            registration = row.get("registration")

            print(
                f"{idx:>2}) ♻️  {model_name} ({registration}) | Taso: {cur_level} → {next_level} | "
                f"Eco: {current_eco:.2f} → {new_eco:.2f} | 💶 {self._fmt_money(cost)}"
            )
            # Talletetaan kaikki tarvittava valintaa varten
            menu_rows.append((row, cur_level, next_level, cost, factor, floor))

        choice = input("Valinta numerolla (tyhjä = peruuta): ").strip()
        if not choice:
            return
        try:
            sel = int(choice)
            if sel < 1 or sel > len(menu_rows):
                print("⚠️  Virheellinen valinta.")
                return
        except ValueError:
            print("⚠️  Virheellinen valinta.")
            return

        row, cur_level, next_level, cost, factor, floor = menu_rows[sel - 1]
        aircraft_id = row["aircraft_id"]
        model_name = row.get("model_name") or row.get("model_code")
        registration = row.get("registration")

        if self.cash < _to_dec(cost):
            print(
                f"❌ Kassa ei riitä päivitykseen. Tarvitset {self._fmt_money(cost)}, sinulla on {self._fmt_money(self.cash)}.")
            input("\n↩︎ Enter jatkaaksesi...")
            return

        # Lasketaan vielä varmistukseksi nykyinen ja uusi eco
        state = get_current_aircraft_upgrade_state(aircraft_id, UPGRADE_CODE)
        current_eco, new_eco = _eco_preview_for_levels(row, state, cur_level, next_level)

        print(f"\nPäivitetään {model_name} ({registration}) tasolta {cur_level} tasolle {next_level}")
        print(f"💶 Hinta: {self._fmt_money(cost)} | ♻️  Eco: {current_eco:.2f} → {new_eco:.2f}")
        confirm = input("Vahvista (k/e): ").strip().lower()
        if confirm != "k":
            print("❎ Peruutettu.")
            return

        try:
            apply_aircraft_upgrade(
                aircraft_id=aircraft_id,
                installed_day=self.current_day,
                cost=cost,
                upgrade_code=UPGRADE_CODE,
                eco_factor_per_level=factor,
                eco_floor=floor
            )
            self._add_cash(-_to_dec(cost))
            print("✅ Päivitys tehty.")
        except Exception as e:
            print(f"❌ Päivitys epäonnistui: {e}")

        input("\n↩︎ Enter jatkaaksesi...")

    # ---------- Tukikohdan päivitykset ----------

    def upgrade_base_menu(self) -> None:
        """
        Interaktiivinen valikko tukikohtien koon päivityksille.
        Kustannus: omistushinta * kerroin (SMALL→MEDIUM 50%, MEDIUM→LARGE 90%, LARGE→HUGE 150%).
        """
        BASE_LEVELS = ["SMALL", "MEDIUM", "LARGE", "HUGE"]
        BASE_UPGRADE_COST_PCTS = {
            ("SMALL", "MEDIUM"): Decimal("0.50"),
            ("MEDIUM", "LARGE"): Decimal("0.90"),
            ("LARGE", "HUGE"): Decimal("1.50"),
        }

        bases = fetch_owned_bases(self.save_id)
        if not bases:
            print("ℹ️  Sinulla ei ole vielä tukikohtia.")
            input("\n↩︎ Enter jatkaaksesi...")
            return

        level_map = fetch_base_current_level_map([b["base_id"] for b in bases])

        _icon_title("Tukikohtien päivitykset")
        menu_rows = []
        for i, b in enumerate(bases, start=1):
            current = level_map.get(b["base_id"], "SMALL")
            cur_idx = BASE_LEVELS.index(current)

            if cur_idx >= len(BASE_LEVELS) - 1:
                print(f"{i:>2}) 🏢 {b['base_name']} ({b['base_ident']}) | Koko: {current} | 🟢 Täysi")
                menu_rows.append((b, current, None, None))
                continue

            nxt = BASE_LEVELS[cur_idx + 1]
            pct = BASE_UPGRADE_COST_PCTS[(current, nxt)]
            cost = (_to_dec(b["purchase_cost"]) * pct).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)

            print(f"{i:>2}) 🏢 {b['base_name']} ({b['base_ident']}) | {current} → {nxt} | 💶 {self._fmt_money(cost)}")
            menu_rows.append((b, current, nxt, cost))

        choice = input("Valinta numerolla (tyhjä = peruuta): ").strip()
        if not choice:
            return
        try:
            sel = int(choice)
            if sel < 1 or sel > len(menu_rows):
                print("⚠️  Virheellinen valinta.")
                return
        except ValueError:
            print("⚠️  Virheellinen valinta.")
            return

        b, current, nxt, cost = menu_rows[sel - 1]
        if not nxt:
            print("ℹ️  Tämä tukikohta on jo täydessä koossa.")
            input("\n↩︎ Enter jatkaaksesi...")
            return

        if self.cash < _to_dec(cost):
            print(f"❌ Kassa ei riitä päivitykseen. Tarvitset {self._fmt_money(cost)}, sinulla on {self._fmt_money(self.cash)}.")
            input("\n↩︎ Enter jatkaaksesi...")
            return

        print(f"\nPäivitetään {b['base_name']} ({b['base_ident']}) tasolta {current} tasolle {nxt}")
        print(f"💶 Hinta: {self._fmt_money(cost)}")
        confirm = input("Vahvista (k/e): ").strip().lower()
        if confirm != "k":
            print("❎ Peruutettu.")
            return

        try:
            insert_base_upgrade(b["base_id"], nxt, cost, self.current_day)
            self._add_cash(-_to_dec(cost))
            print("✅ Tukikohdan päivitys tehty.")
        except Exception as e:
            print(f"❌ Päivitys epäonnistui: {e}")

        input("\n↩︎ Enter jatkaaksesi...")

    def upgrade_menu(self) -> None:
        """
        Päävalikko päivityksille.
        """
        _icon_title("Päivitysvalikko")
        print("1) 🏢 Tukikohta")
        print("2) ♻️  Lentokone (ECO)")
        choice = input("Valinta numerolla (tyhjä = peruuta): ").strip()

        if not choice:
            return
        if choice == "1":
            self.upgrade_base_menu()
        elif choice == "2":
            self.upgrade_aircraft_menu()
        else:
            print("⚠️  Virheellinen valinta.")

    # ---------- Tehtävät ja lentologiikka (tiivistetty, painopisteet ennallaan) ----------

    def _get_airport_coords(self, ident: str):
        """
        Hae kentän koordinaatit airport-taulusta.
        Palauttaa (lat, lon) floatteina tai None jos data puuttuu.
        """
        yhteys = get_connection()
        try:
            try:
                kursori = yhteys.cursor(dictionary=True)
            except TypeError:
                kursori = yhteys.cursor()

            kursori.execute(
                "SELECT latitude_deg, longitude_deg FROM airport WHERE ident = %s",
                (ident,),
            )
            row = kursori.fetchone()
            if not row:
                return None

            if isinstance(row, dict):
                lat, lon = row.get("latitude_deg"), row.get("longitude_deg")
            else:
                lat = row[0] if len(row) > 0 else None
                lon = row[1] if len(row) > 1 else None

            if lat is None or lon is None:
                return None

            return float(lat), float(lon)
        finally:
            try:
                kursori.close()
            except Exception:
                pass
            yhteys.close()

    def _pick_random_destinations(self, n: int, exclude_ident: str):
        """
        Hae n satunnaista kohdekenttää (poislukien exclude_ident).
        """
        yhteys = get_connection()
        try:
            try:
                kursori = yhteys.cursor(dictionary=True)
            except TypeError:
                kursori = yhteys.cursor()

            kursori.execute(
                """
                SELECT ident, name
                FROM airport
                WHERE ident <> %s
                  AND type IN ('small_airport', 'medium_airport', 'large_airport')
                ORDER BY RAND()
                LIMIT %s
                """,
                (exclude_ident, n),
            )
            rows = kursori.fetchall() or []
            kohteet = []
            for r in rows:
                if isinstance(r, dict):
                    kohteet.append({"ident": r["ident"], "name": r.get("name")})
                else:
                    kohteet.append({"ident": r[0], "name": r[1] if len(r) > 1 else None})
            return kohteet
        finally:
            try:
                kursori.close()
            except Exception:
                pass
            yhteys.close()

    def _haversine_km(self, lat1, lon1, lat2, lon2) -> float:
        """
        Haversine-kaava kahden pisteen etäisyyteen (km).
        """
        R = 6371.0
        phi1, phi2 = math.radians(lat1), math.radians(lat2)
        dphi = math.radians(lat2 - lat1)
        dl = math.radians(lon2 - lon1)
        a = math.sin(dphi / 2) ** 2 + math.cos(phi1) * math.cos(phi2) * math.sin(dl / 2) ** 2
        c = 2 * math.atan2(math.sqrt(a), math.sqrt(1 - a))
        return R * c

    def _resolve_effective_eco_multiplier(self, aircraft_id, base_eco_model) -> Decimal:
        """
        Laskee ja normalisoi koneen lopullisen ECO-kertoimen (multiplikatiivinen arvo).
        Perustelut:
        - Laskenta ja näyttö pysyvät yhdenmukaisina, kun kaikki muunnetaan kertoimeksi.
        - Rajaus (ECO_MULT_MIN..ECO_MULT_MAX) estää nollapalkkiot tai kohtuuttomat summat.
        - Talousparametrit sijaitsevat upgrade_configissa, jolloin tasapainotus on keskitetty.

        Palauttaa:
          Decimal kerroinhaarukassa [ECO_MULT_MIN, ECO_MULT_MAX]
        """
        # Yritä käyttää projektin mahdollista ”virallista” funktiota, jos sellainen on saatavilla
        eff_val = None
        try:
            fn = globals().get("compute_effective_eco_multiplier")
            if callable(fn):
                eff_val = float(fn(aircraft_id, float(base_eco_model or 0.0)))
        except Exception:
            eff_val = None

        if eff_val is None:
            try:
                fn2 = globals().get("get_effective_eco_for_aircraft")
                if callable(fn2):
                    eff_val = float(fn2(aircraft_id))
            except Exception:
                eff_val = None

        # Jos emme saaneet arvoa, käytetään mallin kenttää
        if eff_val is None:
            try:
                eff_val = float(base_eco_model or 0.0)
            except Exception:
                eff_val = 0.0

        # Tulkinta: jos arvo on järkevän delta-alueen sisällä, muunna kertoimeksi (1 + delta), muuten pidä kertoimena
        if -0.95 <= eff_val <= 10.0:
            eff_mult = 1.0 + eff_val
        else:
            eff_mult = eff_val

        # Viimeistely: varmista kelvollinen arvo ja rajaa konfiguroidulle välille
        try:
            eff_mult_dec = Decimal(f"{eff_mult}")
        except Exception:
            eff_mult_dec = Decimal("1.00")

        if eff_mult_dec <= Decimal("0.00"):
            eff_mult_dec = Decimal("1.00")

        # Rajaus tehdään upgrade_configin arvoilla (etu: tasapainoa voi säätää keskitetysti)
        eff_mult_dec = max(ECO_MULT_MIN, min(ECO_MULT_MAX, eff_mult_dec))
        return eff_mult_dec

    def _format_eco_for_display(self, eff_mult: Decimal) -> tuple[str, str]:
        """
        Palauttaa kaksi näyttöarvoa ECO:lle:
          - delta: esim. '+0.05' ( johdettu kertoimesta: eff_mult - 1 )
          - kerroin: esim. 'x1.05'
        Näin sekä suhteellinen muutos että varsinainen kerroin ovat selkeästi nähtävissä.
        """
        eco_delta = eff_mult - Decimal("1.00")
        eco_delta_str = f"{eco_delta:+.2f}"
        eco_mult_str = f"x{eff_mult:.2f}"
        return eco_delta_str, eco_mult_str

    def _random_task_offers_for_plane(self, plane, count: int = 5):
        """
        Generoi 'count' kpl tämän päivän rahtitarjouksia annetulle koneelle.
        Perustelut:
        - Palkkion perusosa on lineaarinen painon ja matkan suhteen, mikä on helppoa tasapainottaa.
        - Lopullinen palkkio saadaan kertomalla perusosa ECO-kertoimella, joka on jo rajattu.
        - Rahaluvut lasketaan Decimal-tyypillä tarkkuuden säilyttämiseksi.
        - Parametrit (€/kg, €/km, minimi, sakko-osuus, ECO-rajat) ovat upgrade_configissa.

        Palauttaa listan tarjouksia (dict), mm. payload_kg, distance_km, trips, total_days, reward, penalty, deadline.
        """
        dep_ident = plane["current_airport_ident"]

        # Nopeus solmuista km/päivä
        speed_kts = float(plane.get("cruise_speed_kts") or 200.0)
        speed_km_per_day = max(1.0, speed_kts * 1.852 * 24.0)

        # Kapasiteetti vähintään 1, jotta vältytään jakovirheiltä
        capacity = int(plane.get("base_cargo_kg") or 0) or 1

        # Lopullinen, rajattu ECO-kerroin (Decimal)
        eff_mult_dec = self._resolve_effective_eco_multiplier(
            plane["aircraft_id"],
            plane.get("eco_fee_multiplier") or 0.0
        )

        # Haetaan ylimääräisiä kohteita, jotta saadaan riittävästi kelvollisia tarjouksia
        dests = self._pick_random_destinations(count * 2, dep_ident)
        offers = []

        for d in dests:
            if len(offers) >= count:
                break

            dest_ident = d["ident"]

            # Koordinaatit ovat välttämättömät etäisyyden laskemiseksi
            dep_xy = self._get_airport_coords(dep_ident)
            dst_xy = self._get_airport_coords(dest_ident)
            if not (dep_xy and dst_xy):
                continue

            # Etäisyys (km) Haversinella
            dist_km = self._haversine_km(dep_xy[0], dep_xy[1], dst_xy[0], dst_xy[1])

            # Rahti skaalataan etäisyyden mukaan; sallitaan yli-kapasiteetti, jolloin syntyy useita reissuja
            if dist_km < 500:
                payload = random.randint(max(1, capacity // 2), max(1, capacity * 3))
            elif dist_km < 1500:
                payload = random.randint(capacity, capacity * 4)
            else:
                payload = random.randint(capacity * 2, capacity * 6)

            # Kesto ja reissujen määrä
            base_days = max(1, math.ceil(dist_km / speed_km_per_day))
            trips = max(1, math.ceil(payload / capacity))
            total_days = base_days * trips

            # Peruspalkkio (Decimal), johon sovelletaan ECO-kerrointa
            base_reward = (Decimal(f"{payload}") * TASK_REWARD_PER_KG) + (Decimal(f"{dist_km}") * TASK_REWARD_PER_KM)
            reward = (base_reward * eff_mult_dec).quantize(Decimal("0.01"))

            # Minimiraja ehkäisee mitättömiä tarjouksia lyhyillä lennoilla
            if reward < TASK_MIN_REWARD:
                reward = TASK_MIN_REWARD

            # Sakko suhteessa palkkioon; suojaus negatiivisuutta vastaan, vaikka ratio onkin positiivinen
            penalty = (reward * TASK_PENALTY_RATIO).quantize(Decimal("0.01"))
            if penalty < Decimal("0.00"):
                penalty = Decimal("0.00")

            # Deadline: kokonaiskesto + puskuri, joka skaalautuu reissujen määrän mukaan
            buffer_days = max(1, trips // 2)
            deadline = self.current_day + total_days + buffer_days

            offers.append({
                "dest_ident": dest_ident,
                "dest_name": f"{d.get('name')}",
                "payload_kg": payload,
                "distance_km": dist_km,
                "base_days": base_days,
                "trips": trips,
                "total_days": total_days,
                "reward": reward,
                "penalty": penalty,
                "deadline": deadline,
            })

        return offers[:count]

    def show_active_tasks(self) -> None:
        """
        Listaa aktiiviset tehtävät.

        Selitys:
        - Poimimme kaikki CONTRACTIT, joiden status on 'ACCEPTED' tai 'IN_PROGRESS'.
        - Liitämme mukaan koneen (aircraft) perustiedot ja mahdollisen lennon (flights) tilan.
        - Tulostamme kullekin riville helppolukuiset tiedot: minne, millä koneella, paljonko rahtia,
          mitä palkitaan, deadline ja mahdollinen myöhässä-tila sekä lennon tämänhetkinen tila.

        Vinkki:
        - left_days = deadline - current_day
          Jos left_days < 0, merkkaamme ”myöhässä”.
        - Käytämme self._fmt_money(...) rahasummien siistiin muotoiluun.

        Huom:
        - Tämä funktio EI muuta mitään, se vain näyttää dataa.
        """

        yhteys = get_connection()
        try:
            try:
                kursori = yhteys.cursor(dictionary=True)
            except TypeError:
                # Jotkut klientit eivät tue dictionary=True -flagia
                kursori = yhteys.cursor()

            # Haetaan aktiiviset contractit ja niiden liitokset
            kursori.execute(
                """
                SELECT c.contractId,
                       c.payload_kg,
                       c.reward,
                       c.penalty,
                       c.created_day,
                       c.deadline_day,
                       c.accepted_day,
                       c.status,
                       c.ident  AS dest_ident,
                       a.registration,
                       a.current_airport_ident,
                       f.arrival_day,
                       f.status AS flight_status
                FROM contracts c
                         LEFT JOIN aircraft a ON a.aircraft_id = c.aircraft_id
                         LEFT JOIN flights f ON f.contract_id = c.contractId
                WHERE c.save_id = %s
                  AND c.status IN ('ACCEPTED', 'IN_PROGRESS')
                ORDER BY c.deadline_day ASC, c.contractId ASC
                """,
                (self.save_id,),
            )

            rows = kursori.fetchall() or []
            if not rows:
                print("\nℹ️  Ei aktiivisia tehtäviä.")
                input("\n↩︎ Enter jatkaaksesi...")
                return

            _icon_title("Aktiiviset tehtävät")
            for r in rows:
                # Joustava hakutapa: joko dict-tyylinen rivi tai tuple
                rd = r if isinstance(r, dict) else None

                cid = rd["contractId"] if rd else r[0]
                payload = rd["payload_kg"] if rd else r[1]
                reward = rd["reward"] if rd else r[2]
                penalty = rd["penalty"] if rd else r[3]
                deadline = rd["deadline_day"] if rd else r[5]
                status = rd["status"] if rd else r[7]
                dest = rd["dest_ident"] if rd else r[8]
                reg = rd["registration"] if rd else r[9]
                arr_day = rd["arrival_day"] if rd else r[11]
                fl_status = rd["flight_status"] if rd else r[12]

                # Päiviä jäljellä deadlineen; negatiivinen tarkoittaa myöhässä
                left_days = (deadline - self.current_day) if deadline is not None else None
                late = left_days is not None and left_days < 0

                print(
                    f"📦 #{cid} -> {dest} | ✈️ {reg or '-'} | 🧱 {int(payload)} kg | 💶 {self._fmt_money(reward)} | "
                    f"DL: {deadline} ({'myöhässä' if late else f'{left_days} pv jäljellä'}) | "
                    f"🧭 Tila: {status}{f' / Lento: {fl_status}, ETA {arr_day}' if arr_day is not None else ''}"
                )

            input("\n↩︎ Enter jatkaaksesi...")
        finally:
            # Tavanmukainen siivous: suljetaan kursori ja yhteys turvallisesti
            try:
                kursori.close()
            except Exception:
                pass
            yhteys.close()

    def start_new_task(self) -> None:
        """
        Aloittaa uuden tehtävän:
        1) Listaa IDLE-koneet ja näyttää ECO:n sekä deltana että kertoimena (sama, rajattu arvo molemmissa).
        2) Generoi valitulle koneelle tehtävät, joissa palkkio huomioi ECO:n.
        3) Luo contractin ja flightin atomisesti, ja merkitsee koneen varatuksi.
        Yhdenmukainen ECO-näyttö estää harhaanjohtavat arvot (esim. x0.00).
        """
        yhteys = get_connection()
        try:
            try:
                kursori = yhteys.cursor(dictionary=True)
            except TypeError:
                kursori = yhteys.cursor()

            # Vapaana olevat koneet
            kursori.execute(
                """
                SELECT a.aircraft_id,
                       a.registration,
                       a.current_airport_ident,
                       a.model_code,
                       am.model_name,
                       am.base_cargo_kg,
                       am.cruise_speed_kts,
                       am.eco_fee_multiplier
                FROM aircraft a
                         JOIN aircraft_models am ON am.model_code = a.model_code
                WHERE a.save_id = %s
                  AND a.status = 'IDLE'
                ORDER BY a.aircraft_id
                """,
                (self.save_id,),
            )
            planes = kursori.fetchall() or []
            if not planes:
                print("ℹ️  Ei vapaita (IDLE) koneita.")
                input("\n↩︎ Enter jatkaaksesi...")
                return

            _icon_title("Valitse kone tehtävään")

            # Listaus: ECO näytetään sekä deltana että kertoimena samasta, rajatusta arvosta
            for i, p in enumerate(planes, start=1):
                cap = int(p["base_cargo_kg"] if isinstance(p, dict) else 0)

                eff_mult_dec = self._resolve_effective_eco_multiplier(
                    p["aircraft_id"],
                    p.get("eco_fee_multiplier") or 0.0
                )
                eco_delta_str, eco_mult_str = self._format_eco_for_display(eff_mult_dec)

                print(
                    f"{i:>2}) ✈️ {p['registration']} {p['model_name']} @ {p['current_airport_ident']} | "
                    f"📦 {cap} kg | ♻️ {eco_delta_str} ({eco_mult_str})"
                )

            sel = input("Valinta numerolla (tyhjä = peruuta): ").strip()
            if not sel:
                return
            try:
                idx = int(sel)
                if idx < 1 or idx > len(planes):
                    print("⚠️  Virheellinen valinta.")
                    return
            except ValueError:
                print("⚠️  Virheellinen valinta.")
                return

            plane = planes[idx - 1]
            offers = self._random_task_offers_for_plane(plane, count=5)
            if not offers:
                print("ℹ️  Ei tarjouksia saatavilla juuri nyt.")
                input("\n↩︎ Enter jatkaaksesi...")
                return

            _icon_title("Tarjotut tehtävät")
            for i, o in enumerate(offers, start=1):
                print(
                    f"{i:>2}) {plane['current_airport_ident']} → {o['dest_ident']} ({o['dest_name'] or '-'}) | "
                    f"📦 {o['payload_kg']} kg | 📏 {int(o['distance_km'])} km | 🔁 {o['trips']} | "
                    f"🕒 {o['total_days']} pv | 💶 {self._fmt_money(o['reward'])} | ❗ Sakko {self._fmt_money(o['penalty'])} | "
                    f"DL {o['deadline']}"
                )

            sel = input("Valitse tehtävä numerolla (tyhjä = peruuta): ").strip()
            if not sel:
                return
            try:
                oidx = int(sel)
                if oidx < 1 or oidx > len(offers):
                    print("⚠️  Virheellinen valinta.")
                    return
            except ValueError:
                print("⚠️  Virheellinen valinta.")
                return

            offer = offers[oidx - 1]
            print("\nTehtäväyhteenveto:")
            print(
                f"🛫 {plane['current_airport_ident']} → 🛬 {offer['dest_ident']} | "
                f"📦 {offer['payload_kg']} kg | 🔁 {offer['trips']} | "
                f"🕒 {offer['total_days']} pv | 💶 {self._fmt_money(offer['reward'])} | DL: päivä {offer['deadline']}"
            )
            ok = input("Aloitetaanko tehtävä? (k/e): ").strip().lower()
            if ok != "k":
                print("❎ Peruutettu.")
                return

            now_day = self.current_day
            total_dist = float(offer["distance_km"]) * offer["trips"]
            arr_day = now_day + offer["total_days"]

            try:
                yhteys.start_transaction()

                # Contract
                kursori.execute(
                    """
                    INSERT INTO contracts (payload_kg, reward, penalty, priority,
                                           created_day, deadline_day, accepted_day, completed_day,
                                           status, lost_packages, damaged_packages,
                                           save_id, aircraft_id, ident, event_id)
                    VALUES (%s, %s, %s, %s,
                            %s, %s, %s, %s,
                            %s, %s, %s,
                            %s, %s, %s, %s)
                    """,
                    (
                        offer["payload_kg"], offer["reward"], offer["penalty"], "NORMAL",
                        now_day, offer["deadline"], now_day, None,
                        "IN_PROGRESS", 0, 0,
                        self.save_id, plane["aircraft_id"], offer["dest_ident"], None
                    ),
                )
                contract_id = kursori.lastrowid

                # Flight
                kursori.execute(
                    """
                    INSERT INTO flights (created_day, dep_day, arrival_day, status, distance_km, schedule_delay_min,
                                         emission_kg_co2, eco_fee, dep_ident, arr_ident, aircraft_id, save_id,
                                         contract_id)
                    VALUES (%s, %s, %s, %s, %s, %s,
                            %s, %s, %s, %s, %s, %s, %s)
                    """,
                    (
                        now_day, now_day, arr_day, "ENROUTE", total_dist, 0,
                        0.0, Decimal("0.00"),
                        plane["current_airport_ident"], offer["dest_ident"],
                        plane["aircraft_id"], self.save_id, contract_id
                    ),
                )

                # Merkitään kone varatuksi
                kursori.execute(
                    "UPDATE aircraft SET status = 'BUSY' WHERE aircraft_id = %s",
                    (plane["aircraft_id"],)
                )

                yhteys.commit()
                print(f"✅ Tehtävä #{contract_id} aloitettu. ETA: {arr_day} (lähtöjä {offer['trips']}).")
                print("ℹ️  Palkkio hyvitetään, kun lento on saapunut (Seuraava päivä).")
            except Exception as e:
                yhteys.rollback()
                print(f"❌ Tehtävän aloitus epäonnistui: {e}")
                return

            input("\n↩︎ Enter jatkaaksesi...")
        finally:
            try:
                kursori.close()
            except Exception:
                pass
            yhteys.close()

    # ---------- Seuraava päivä + kuukausilaskut ----------

    def advance_to_next_day(self, silent: bool = False) -> dict:
        """
        Siirtää päivän eteenpäin yhdellä, prosessoi saapuneet lennot ja päivittää kassaa.
        - Palauttaa yhteenvedon: {"arrivals": int, "earned": Decimal}
        - silent=True: ei tulostuksia eikä Enter-pysäytystä (soveltuu pikakelaus-looppeihin).
        - Joka 30. päivä veloitetaan kuukausilaskut.
        HUOM: Python 3.9 -yhteensopiva: käytetään datetime.utcnow().
        """

        new_day = self.current_day + 1
        arrivals_count = 0
        total_delta = Decimal("0.00")

        # UTC-naive aikaleima tietokantaan
        db_timestamp = datetime.utcnow()

        yhteys = get_connection()
        try:
            try:
                kursori = yhteys.cursor(dictionary=True)
            except TypeError:
                kursori = yhteys.cursor()

            try:
                yhteys.start_transaction()

                # Päivän vaihto + updated_at
                kursori.execute(
                    "UPDATE game_saves SET current_day = %s, updated_at = %s WHERE save_id = %s",
                    (new_day, db_timestamp, self.save_id),
                )

                # Haetaan tähän päivään mennessä saapuvat lennot
                kursori.execute(
                    """
                    SELECT f.flight_id,
                           f.contract_id,
                           f.aircraft_id,
                           f.arr_ident,
                           f.arrival_day,
                           c.deadline_day,
                           c.reward,
                           c.penalty
                    FROM flights f
                             JOIN contracts c ON c.contractId = f.contract_id
                    WHERE f.save_id = %s
                      AND f.status = 'ENROUTE'
                      AND f.arrival_day <= %s
                    """,
                    (self.save_id, new_day),
                )
                arrivals = kursori.fetchall() or []
                arrivals_count = len(arrivals)

                for rd in arrivals:
                    # Salli sekä dict- että tuple-rivit
                    flight_id = rd["flight_id"] if isinstance(rd, dict) else rd[0]
                    contract_id = rd["contract_id"] if isinstance(rd, dict) else rd[1]
                    aircraft_id = rd["aircraft_id"] if isinstance(rd, dict) else rd[2]
                    arr_ident = rd["arr_ident"] if isinstance(rd, dict) else rd[3]
                    deadline = int(rd["deadline_day"] if isinstance(rd, dict) else rd[5])
                    reward = _to_dec(rd["reward"] if isinstance(rd, dict) else rd[6])
                    penalty = _to_dec(rd["penalty"] if isinstance(rd, dict) else rd[7])

                    # Lennon tila saapuneeksi
                    kursori.execute("UPDATE flights SET status = 'ARRIVED' WHERE flight_id = %s", (flight_id,))

                    # Kone vapautuu ja siirtyy määräkentälle
                    kursori.execute(
                        "UPDATE aircraft SET status = 'IDLE', current_airport_ident = %s WHERE aircraft_id = %s",
                        (arr_ident, aircraft_id),
                    )

                    # Sopimuksen lopputulos (myöhästyminen vähentää palkkiota, mutta ei alle nollan)
                    if new_day <= deadline:
                        final_reward = reward
                        new_status = "COMPLETED"
                    else:
                        final_reward = max(Decimal("0.00"), reward - penalty)
                        new_status = "COMPLETED_LATE"

                    kursori.execute(
                        "UPDATE contracts SET status = %s, completed_day = %s WHERE contractId = %s",
                        (new_status, new_day, contract_id),
                    )

                    total_delta += final_reward

                # Hyvitä ansiot kassaan kerralla
                if total_delta != Decimal("0.00"):
                    kursori.execute("SELECT cash FROM game_saves WHERE save_id = %s FOR UPDATE", (self.save_id,))
                    row = kursori.fetchone()
                    cur_cash = _to_dec(row["cash"] if isinstance(row, dict) else row[0])
                    new_cash = (cur_cash + total_delta).quantize(Decimal("0.01"))
                    kursori.execute("UPDATE game_saves SET cash = %s WHERE save_id = %s", (new_cash, self.save_id))
                    self.cash = new_cash

                yhteys.commit()
                self.current_day = new_day

            except Exception as e:
                yhteys.rollback()
                if not silent:
                    print(f"❌ Seuraava päivä -käsittely epäonnistui: {e}")
                return {"arrivals": 0, "earned": Decimal("0.00")}
        finally:
            try:
                kursori.close()
            except Exception:
                pass
            try:
                yhteys.close()
            except Exception:
                pass

        # Kuukausilaskut joka 30. päivä (vain aktiiviselle yritykselle)
        if self.current_day % 30 == 0 and self.status == "ACTIVE":
            self._process_monthly_bills(silent=silent)

        # Tulosteet vain ei-hiljaisessa tilassa
        if not silent:
            gained_str = f", ansaittu {self._fmt_money(total_delta)}" if arrivals_count > 0 else ""
            print(f"⏭️  Päivä siirtyi: {self.current_day}{gained_str}.")
            input("\n↩︎ Enter jatkaaksesi...")

            if self.status == "BANKRUPT":
                print("💀 Yritys meni konkurssiin.")
            if self.current_day >= SURVIVAL_TARGET_DAYS and self.status == "ACTIVE":
                print(f"🏆 Onnea! Selvisit {SURVIVAL_TARGET_DAYS} päivää.")

        return {"arrivals": arrivals_count, "earned": total_delta}

    def _process_monthly_bills(self, silent: bool = False) -> None:
        """
        Veloittaa kuukausittaiset kulut:
          - HQ_MONTHLY_FEE
          - MAINT_PER_AIRCRAFT per aktiivinen kone
          - STARTER-koneille alennus (STARTER_MAINT_DISCOUNT)
        Jos rahat eivät riitä: asetetaan status = BANKRUPT.
        """
        yhteys = get_connection()
        try:
            kursori = yhteys.cursor(dictionary=True)
            # Laske aktiivisten (ei myytyjen) koneiden määrä ja STARTER-koneiden osuus
            kursori.execute(
                """
                SELECT COUNT(*)                                                 AS total,
                       SUM(CASE WHEN am.category = 'STARTER' THEN 1 ELSE 0 END) AS starters
                FROM aircraft a
                         JOIN aircraft_models am ON am.model_code = a.model_code
                WHERE a.save_id = %s
                  AND (a.sold_day IS NULL OR a.sold_day = 0)
                """,
                (self.save_id,),
            )
            r = kursori.fetchone() or {"total": 0, "starters": 0}
            total_planes = int(r["total"] or 0)
            starter_planes = int(r["starters"] or 0)
        finally:
            try:
                kursori.close()
            except Exception:
                pass
            try:
                yhteys.close()
            except Exception:
                pass

        # Huoltokulu: STARTER-koneille alennus, muille täysi hinta
        maint_starter = (MAINT_PER_AIRCRAFT * STARTER_MAINT_DISCOUNT) * starter_planes
        maint_nonstarter = MAINT_PER_AIRCRAFT * max(0, total_planes - starter_planes)
        total_bill = (HQ_MONTHLY_FEE + maint_starter + maint_nonstarter).quantize(Decimal("0.01"))

        if not silent:
            print("\n💸 Kuukausilaskut erääntyivät!")
            print(f"   🏢 HQ: {self._fmt_money(HQ_MONTHLY_FEE)}")
            print(f"   🔧 Huollot ({total_planes} kpl): {self._fmt_money(maint_starter + maint_nonstarter)}")
            print(f"   ➖ Yhteensä: {self._fmt_money(total_bill)}")

        # Maksu tai konkurssi
        if self.cash < total_bill:
            if not silent:
                print("💀 Rahat eivät riitä laskuihin. Yritys menee konkurssiin.")
            self._set_status("BANKRUPT")
            return

        try:
            self._add_cash(-total_bill)
            if not silent:
                print("✅ Laskut maksettu.")
        except Exception as e:
            if not silent:
                print(f"❌ Laskujen veloitus epäonnistui: {e}")

    # ---------- Pikakelaus ---------

    def fast_forward_days(self, days: int) -> None:
        """
        Etenee 'days' päivää eteenpäin, hiljaisesti (ei tulostuksia per päivä).
        Pysähtyy, jos:
          - status muuttuu BANKRUPT
          - saavutetaan tai ylitetään SURVIVAL_TARGET_DAYS (status asetetaan VICTORY, jos vielä ACTIVE)
        Tulostaa lopuksi yhteenvedon.
        """
        days = max(0, int(days))
        arrived_total = 0
        earned_total = Decimal("0.00")

        for _ in range(days):
            summary = self.advance_to_next_day(silent=True)
            arrived_total += int(summary.get("arrivals", 0))
            earned_total += _to_dec(summary.get("earned", 0))
            if self.status == "BANKRUPT":
                break
            if self.current_day >= SURVIVAL_TARGET_DAYS:
                if self.status == "ACTIVE":
                    self._set_status("VICTORY")
                break

        print(f"⏩ Pikakelaus valmis. Päivä nyt {self.current_day}.")
        print(f"   ✈️ Saapuneita lentoja: {arrived_total} | 💶 Yhteensä ansaittu: {self._fmt_money(earned_total)}")

    def fast_forward_until_first_return(self, max_days: int = 365) -> None:
        """
        Etenee päivä kerrallaan, kunnes ensimmäinen lento palaa (eli sinä päivänä on ≥1 saapuminen).
        - Turvaraja: max_days (ettei jäädä ikuiseen looppiin).
        - Pysähtyy myös konkurssiin tai voittoon (asetetaan VICTORY, jos vielä ACTIVE).
        - Jos ei ole käynnissä olevia lentoja, ilmoitetaan ja palataan heti.
        """
        # Varmista kelvollinen raja
        max_days = max(1, int(max_days))

        # Esitarkistus: onko yhtään käynnissä olevaa lentoa?
        enroute_count = 0
        yhteys = get_connection()
        try:
            try:
                kursori = yhteys.cursor()
                kursori.execute(
                    "SELECT COUNT(*) FROM flights WHERE save_id = %s AND status = 'ENROUTE'",
                    (self.save_id,),
                )
                r = kursori.fetchone()
                enroute_count = int(r[0] if r else 0)
            finally:
                try:
                    kursori.close()
                except Exception:
                    pass
        finally:
            try:
                yhteys.close()
            except Exception:
                pass

        if enroute_count == 0:
            print("ℹ️  Ei käynnissä olevia lentoja. Aloita ensin tehtävä, jotta on jotain mihin palata.")
            return

        days_advanced = 0
        earned_total = Decimal("0.00")
        stop_reason = "max"  # oletus: maksimipäiväraja täyttyi

        for _ in range(max_days):
            summary = self.advance_to_next_day(silent=True)
            days_advanced += 1
            earned_total += _to_dec(summary.get("earned", 0))

            # 1) Ensimmäiset saapumiset havaittu
            if int(summary.get("arrivals", 0)) > 0:
                stop_reason = "arrival"
                break
            # 2) Konkurssi
            if self.status == "BANKRUPT":
                stop_reason = "bankrupt"
                break
            # 3) Voitto (selviytymisraja saavutettu)
            if self.current_day >= SURVIVAL_TARGET_DAYS:
                if self.status == "ACTIVE":
                    self._set_status("VICTORY")
                stop_reason = "victory"
                break

        # Yhteenveto
        if stop_reason == "arrival":
            print(f"🎯 Ensimmäinen lento palasi. Päiviä edetty: {days_advanced}, päivä nyt {self.current_day}.")
        elif stop_reason == "bankrupt":
            print(f"💀 Konkurssi keskeytti. Päiviä edetty: {days_advanced}, päivä nyt {self.current_day}.")
        elif stop_reason == "victory":
            print(f"🏆 Selviytymisraja saavutettu. Päiviä edetty: {days_advanced}, päivä nyt {self.current_day}.")
        else:  # "max"
            print(f"⏹️  Ei paluuta {max_days} päivän aikana. Päivä nyt {self.current_day}.")

        print(f"   💶 Kertynyt ansio: {self._fmt_money(earned_total)}")
        input("\n↩︎ Enter jatkaaksesi...")

    # ---------- DB: apurit ----------

    def _refresh_save_state(self) -> None:
        """
        Täydennä puuttuvat kentät (nimi, kassa, päivä, status, rng_seed, difficulty) game_saves-taulusta.
        """
        need = any(v is None for v in (self.player_name, self.cash, self.current_day, self.status))
        if not need:
            return

        yhteys = get_connection()
        try:
            try:
                kursori = yhteys.cursor(dictionary=True)
            except TypeError:
                kursori = yhteys.cursor()

            kursori.execute(
                """
                SELECT player_name, cash, difficulty, current_day, status, rng_seed
                FROM game_saves
                WHERE save_id = %s
                """,
                (self.save_id,),
            )
            r = kursori.fetchone()
            if not r:
                raise ValueError(f"Tallennetta save_id={self.save_id} ei löytynyt.")

            if isinstance(r, dict):
                self.player_name = r["player_name"]
                self.cash = _to_dec(r["cash"])
                self.difficulty = r.get("difficulty") or self.difficulty
                self.current_day = int(r["current_day"])
                self.status = r["status"]
                self.rng_seed = r.get("rng_seed")
            else:
                self.player_name = r[0]
                self.cash = _to_dec(r[1])
                self.difficulty = r[2] or self.difficulty
                self.current_day = int(r[3])
                self.status = r[4]
                self.rng_seed = r[5]
        finally:
            try:
                kursori.close()
            except Exception:
                pass
            yhteys.close()

    def _fetch_aircraft_models_by_base_progress(self) -> List[dict]:
        """
        Hae myynnissä olevat mallit korkeimman tukikohdan tason mukaan (SMALL..HUGE).
        STARTER ei näy kaupassa.
        """
        yhteys = get_connection()
        kursori = yhteys.cursor(dictionary=True)
        try:
            kursori.execute(
                """
                WITH max_tier AS (
                  SELECT
                    COALESCE(MAX(
                      CASE bu.upgrade_code
                        WHEN 'SMALL' THEN 1
                        WHEN 'MEDIUM' THEN 2
                        WHEN 'LARGE' THEN 3
                        WHEN 'HUGE' THEN 4
                        ELSE 0
                      END
                    ), 0) AS t
                  FROM owned_bases ob
                  JOIN base_upgrades bu ON bu.base_id = ob.base_id
                  WHERE ob.save_id = %s
                )
                SELECT am.model_code, am.manufacturer, am.model_name, am.purchase_price,
                       am.base_cargo_kg, am.range_km, am.cruise_speed_kts, am.category
                FROM aircraft_models am
                CROSS JOIN max_tier mt
                WHERE am.category <> 'STARTER'
                  AND CASE am.category
                        WHEN 'SMALL' THEN 1
                        WHEN 'MEDIUM' THEN 2
                        WHEN 'LARGE' THEN 3
                        WHEN 'HUGE' THEN 4
                        ELSE 0
                      END <= mt.t
                ORDER BY am.purchase_price ASC, am.model_code ASC
                """,
                (self.save_id,),
            )
            return kursori.fetchall() or []
        finally:
            kursori.close()
            yhteys.close()

    def _create_owned_base_and_small_upgrade_tx(self, base_ident: str, base_name: str, purchase_cost: Decimal) -> int:
        """
        Luo owned_bases-rivin ja lisää base_upgrades-tauluun SMALL-rivin.
        Veloittaa hinnan kassasta. Palauttaa base_id:n.
        """
        yhteys = get_connection()
        kursori = yhteys.cursor()
        try:
            kursori.execute("SELECT cash FROM game_saves WHERE save_id = %s FOR UPDATE", (self.save_id,))
            row = kursori.fetchone()
            if not row:
                raise ValueError("Tallennetta ei löytynyt tukikohtaa luodessa.")
            cur_cash = _to_dec(row["cash"] if isinstance(row, dict) else row[0])
            if cur_cash < purchase_cost:
                raise ValueError("Kassa ei riitä tukikohtaan.")

            now = datetime.utcnow()
            kursori.execute(
                """
                INSERT INTO owned_bases
                  (save_id, base_ident, base_name, acquired_day, purchase_cost, created_at, updated_at)
                VALUES
                  (%s, %s, %s, %s, %s, %s, %s)
                """,
                (
                    self.save_id,
                    base_ident,
                    base_name,
                    self.current_day,
                    purchase_cost,
                    now,
                    now,
                ),
            )
            base_id = int(kursori.lastrowid)

            kursori.execute(
                """
                INSERT INTO base_upgrades (base_id, upgrade_code, installed_day, upgrade_cost)
                VALUES (%s, %s, %s, %s)
                """,
                (base_id, "SMALL", self.current_day, Decimal("0.00")),
            )

            new_cash = (cur_cash - purchase_cost).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
            kursori.execute(
                "UPDATE game_saves SET cash = %s, updated_at = %s WHERE save_id = %s",
                (new_cash, now, self.save_id),
            )

            yhteys.commit()
            self.cash = new_cash
            return base_id
        except Exception:
            yhteys.rollback()
            raise
        finally:
            try:
                kursori.close()
            except Exception:
                pass
            yhteys.close()

    def _get_primary_base(self) -> Optional[dict]:
        """
        Palauta ensimmäinen ostettu tukikohta dictinä tai None.
        """
        yhteys = get_connection()
        try:
            try:
                kursori = yhteys.cursor(dictionary=True)
            except TypeError:
                kursori = yhteys.cursor()

            kursori.execute(
                """
                SELECT base_id, base_ident, base_name, acquired_day
                FROM owned_bases
                WHERE save_id = %s
                ORDER BY acquired_day ASC, base_id ASC
                LIMIT 1
                """,
                (self.save_id,),
            )
            r = kursori.fetchone()
            if not r:
                return None
            return r if isinstance(r, dict) else {
                "base_id": r[0],
                "base_ident": r[1],
                "base_name": r[2],
                "acquired_day": r[3],
            }
        finally:
            try:
                kursori.close()
            except Exception:
                pass
            yhteys.close()

    def _get_primary_base_ident(self) -> Optional[str]:
        """
        Palauta ensimmäisen tukikohdan ICAO-tunnus tai None.
        """
        b = self._get_primary_base()
        return b["base_ident"] if b else None

    def _get_base_id_by_ident(self, base_ident: str) -> Optional[int]:
        """
        Hae base_id annetulla tunnuksella tältä tallennukselta.
        """
        yhteys = get_connection()
        try:
            kursori = yhteys.cursor()
            kursori.execute(
                "SELECT base_id FROM owned_bases WHERE save_id = %s AND base_ident = %s",
                (self.save_id, base_ident),
            )
            r = kursori.fetchone()
            if not r:
                return None
            return int(r["base_id"] if isinstance(r, dict) else r[0])
        finally:
            try:
                kursori.close()
            except Exception:
                pass
            yhteys.close()

    def _fetch_upgrade_levels(self, aircraft_ids: List[int]) -> Dict[int, int]:
        """
        Palauta (aircraft_id -> ECO-upgrade -taso) -mappi.
        """
        if not aircraft_ids:
            return {}

        yhteys = get_connection()
        kursori = yhteys.cursor()
        try:
            placeholders = ",".join(["%s"] * len(aircraft_ids))
            kursori.execute(
                f"""
                SELECT aircraft_id, MAX(level) AS max_level
                FROM aircraft_upgrades
                WHERE upgrade_code = %s AND aircraft_id IN ({placeholders})
                GROUP BY aircraft_id
                """,
                tuple([UPGRADE_CODE] + aircraft_ids),
            )
            rows = kursori.fetchall() or []
            if rows and isinstance(rows[0], dict):
                return {int(r["aircraft_id"]): int(r["max_level"] or 0) for r in rows}
            return {int(r[0]): int(r[1] or 0) for r in rows}
        finally:
            try:
                kursori.close()
            except Exception:
                pass
            yhteys.close()

    # ---------- Kassan ja statuksen hallinta ----------

    def _set_cash(self, new_cash: Decimal) -> None:
        """
        Päivitä kassa kantaan ja pidä olion tila synkassa.
        """
        yhteys = get_connection()
        kursori = yhteys.cursor()
        try:
            kursori.execute(
                "UPDATE game_saves SET cash = %s, updated_at = %s WHERE save_id = %s",
                (_to_dec(new_cash), datetime.utcnow(), self.save_id),
            )
            yhteys.commit()
            self.cash = _to_dec(new_cash)
        except Exception:
            yhteys.rollback()
            raise
        finally:
            try:
                kursori.close()
            except Exception:
                pass
            yhteys.close()

    def _add_cash(self, delta: Decimal) -> None:
        """
        Lisää tai vähennä kassaa (ei saa mennä negatiiviseksi).
        """
        new_val = (self.cash + _to_dec(delta)).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
        if new_val < Decimal("0"):
            raise ValueError("Kassa ei voi mennä negatiiviseksi.")
        self._set_cash(new_val)

    def _set_status(self, new_status: str) -> None:
        """
        Päivitä tallennuksen status (ACTIVE, BANKRUPT, VICTORY, ...).
        """
        yhteys = get_connection()
        kursori = yhteys.cursor()
        try:
            kursori.execute(
                "UPDATE game_saves SET status = %s, updated_at = %s WHERE save_id = %s",
                (new_status, datetime.utcnow(), self.save_id),
            )
            yhteys.commit()
            self.status = new_status
        except Exception:
            yhteys.rollback()
            raise
        finally:
            try:
                kursori.close()
            except Exception:
                pass
            yhteys.close()

    # ---------- Osto ja lahjakone ----------

    def _purchase_aircraft_tx(
        self,
        model_code: str,
        current_airport_ident: str,
        registration: str,
        nickname: Optional[str],
        purchase_price: Decimal,
        base_id: Optional[int],
    ) -> bool:
        """
        Atominen ostotapahtuma:
          - Lukitse kassa
          - Lisää kone
          - Veloita hinta
        """
        yhteys = get_connection()
        kursori = yhteys.cursor()
        try:
            kursori.execute("SELECT cash FROM game_saves WHERE save_id = %s FOR UPDATE", (self.save_id,))
            row = kursori.fetchone()
            if not row:
                raise ValueError("Tallennetta ei löytynyt ostohetkellä.")
            cash_now = _to_dec(row["cash"] if isinstance(row, dict) else row[0])
            if cash_now < purchase_price:
                yhteys.rollback()
                return False

            kursori.execute(
                """
                INSERT INTO aircraft
                  (model_code, base_level, current_airport_ident, registration, nickname,
                   acquired_day, purchase_price, condition_percent, status, hours_flown,
                   sold_day, sale_price, save_id, base_id)
                VALUES
                  (%s, %s, %s, %s, %s,
                   %s, %s, %s, %s, %s,
                   %s, %s, %s, %s)
                """,
                (
                    model_code,
                    1,
                    current_airport_ident,
                    registration,
                    nickname,
                    self.current_day,
                    purchase_price,
                    100,
                    "IDLE",
                    0,
                    None,
                    None,
                    self.save_id,
                    base_id,
                ),
            )

            new_cash = (cash_now - purchase_price).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
            kursori.execute(
                "UPDATE game_saves SET cash = %s, updated_at = %s WHERE save_id = %s",
                (new_cash, datetime.utcnow(), self.save_id),
            )

            yhteys.commit()
            self.cash = new_cash
            return True
        except Exception as e:
            print(f"❌ Virhe ostossa: {e}")
            yhteys.rollback()
            return False
        finally:
            try:
                kursori.close()
            except Exception:
                pass
            yhteys.close()

    def _insert_gift_aircraft_tx(
        self,
        model_code: str,
        current_airport_ident: str,
        base_id: int,
        nickname: Optional[str] = None,
    ) -> None:
        """
        Lisää lahjakoneen (STARTER: DC3FREE) transaktion sisällä (hinta 0).
        """
        registration = f"666-{self._rand_letters(2)}{self._rand_digits(2)}"
        yhteys = get_connection()
        kursori = yhteys.cursor()
        try:
            kursori.execute("SELECT save_id FROM game_saves WHERE save_id = %s FOR UPDATE", (self.save_id,))
            r = kursori.fetchone()
            if not r:
                raise ValueError("Tallennetta ei löytynyt lahjakonetta lisättäessä.")

            kursori.execute(
                """
                INSERT INTO aircraft
                  (model_code, base_level, current_airport_ident, registration, nickname,
                   acquired_day, purchase_price, condition_percent, status, hours_flown,
                   sold_day, sale_price, save_id, base_id)
                VALUES
                  (%s, %s, %s, %s, %s,
                   %s, %s, %s, %s, %s,
                   %s, %s, %s, %s)
                """,
                (
                    model_code,
                    1,
                    current_airport_ident,
                    registration,
                    nickname,
                    self.current_day,
                    Decimal("0.00"),
                    100,
                    "IDLE",
                    0,
                    None,
                    None,
                    self.save_id,
                    base_id,
                ),
            )

            kursori.execute(
                "UPDATE game_saves SET updated_at = %s WHERE save_id = %s",
                (datetime.utcnow(), self.save_id),
            )

            yhteys.commit()
        except Exception:
            yhteys.rollback()
            raise
        finally:
            try:
                kursori.close()
            except Exception:
                pass
            yhteys.close()

    # ---------- Aputyökalut ----------

    def _generate_registration(self) -> str:
        """
        Luo simppeli rekisteri N-XX99 -tyyliin.
        """
        letters = "".join(random.choices(string.ascii_uppercase, k=2))
        digits = "".join(random.choices(string.digits, k=2))
        return f"N-{letters}{digits}"

    def _rand_letters(self, n: int) -> str:
        return "".join(random.choices(string.ascii_uppercase, k=n))

    def _rand_digits(self, n: int) -> str:
        return "".join(random.choices(string.digits, k=n))

    def _fmt_money(self, amount) -> str:
        """
        Muotoile rahasumma euroiksi kahdella desimaalilla.
        Esim. Decimal('1234567.8') -> '1 234 567,80 €'
        """
        d = _to_dec(amount).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
        return f"{d:,.2f} €".replace(",", " ").replace(".", ",")
