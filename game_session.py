# Pelisession (GameSession) logiikka ja tietokantatoiminnot.
# - STARTER-kone (DC3FREE) annetaan vain uuden pelin alussa iso-isän lahjana.
# - Pelaaja ostaa ensimmäisen tukikohdan (EFHK/LFPG/KJFK) hinnalla ~30/50/70 % aloitusrahasta.
# - Ensimmäisen tukikohdan luonnin yhteydessä lisätään base_upgrades-tauluun rivi koodilla SMALL.
# - Kaupassa listataan vain koneluokat, jotka tukikohdan upgrade-taso sallii (SMALL/MEDIUM/LARGE/HUGE).
# - Tietokantayhteys saadaan get_connection(), backupina rollback.

import random
import string
import math
from typing import List, Optional, Dict
from decimal import Decimal, ROUND_HALF_UP, getcontext
from datetime import datetime
from utils import get_connection
from airplane import init_airplanes, upgrade_airplane as db_upgrade_airplane

# Decimal-laskennan tarkkuus – haluan minimoida pyöristysvirheet rahalaskennassa
getcontext().prec = 28

# Yhdenmukainen konemodernisaatioiden koodi (konekohtaiset upgradet)
UPGRADE_CODE = "UPG"

# Tukikohdan tasojen järjestys arvolla – helpottaa vertailua SQL:ssä ja Pythonissa
CATEGORY_TIER = {
    "STARTER": 0,  # ei myynnissä, vain lahja
    "SMALL": 1,
    "MEDIUM": 2,
    "LARGE": 3,
    "HUGE": 4,
}


class GameSession:
    """
    GameSession kapseloi yhden game_saves-rivin ja siihen liittyvän tilan.
    Pidän huolen kassan, päivän ja muiden avainarvojen päivityksestä kantaan.
    """

    def __init__(
        self,
        save_id: int,
        current_day: Optional[int] = None,
        player_name: Optional[str] = None,
        cash: Optional[Decimal] = None,
        status: Optional[str] = None,
        rng_seed: Optional[int] = None,
        difficulty: Optional[str] = None,  # taulussa olemassa, UI ei käytä
    ):
        # Konstruktorin parametrit talteen, puuttuvat täydennetään kannasta
        self.save_id = int(save_id)
        self.player_name = player_name
        self.cash = Decimal(str(cash)) if cash is not None else None
        self.current_day = int(current_day) if current_day is not None else None
        self.status = status
        self.rng_seed = rng_seed
        self.difficulty = difficulty or "NORMAL"  # en kysy vaikeutta, käytän oletusta

        # Lataan puuttuvat tallennuksen tiedot
        self._refresh_save_state()

    # ---------- Luonti / lataus ----------

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
        Luo uuden tallennuksen.
        Heti alussa:
        1) Pelaaja ostaa ensimmäisen tukikohdan (EFHK/LFPG/KJFK) 30/50/70 % hinnalla.
        2) Lisään base_upgrades-tauluun SMALL-koodin ko. tukikohdalle.
        3) Iso-isä lahjoittaa DC3FREE STARTER-koneen valittuun tukikohtaan.
        """
        # Avataan yhteys ja luodaan tallennus
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
                    Decimal(str(cash)),
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

        # Rakennan session olion ja luotsaan pelaajan alkuasetusten läpi
        session = cls(save_id=save_id)

        if show_intro:
            print(f"Tervetuloa, {session.player_name}! Aloituskassa: {session._fmt_money(session.cash)}.")

        # Ensimmäinen tukikohta + SMALL-upgrade + lahjakone DC3FREE (STARTER)
        session._first_time_base_and_gift_setup(starting_cash=Decimal(str(cash)))

        return session

    @classmethod
    def load(cls, save_id: int) -> "GameSession":
        """
        Lataan olemassa olevan tallennuksen ID:llä.
        """
        return cls(save_id=save_id)

    # ---------- Ensimmäinen tukikohta + SMALL-upgrade + STARTER-lahjakone ----------

    def _first_time_base_and_gift_setup(self, starting_cash: Decimal):
        """
        Pelaaja valitsee ensimmäisen tukikohdan (EFHK/LFPG/KJFK).
        Hinnat ovat 30/50/70 % aloitusrahasta. Luodaan owned_bases-rivin,
        lisään base_upgrades-tauluun SMALL-rivin ja lisään STARTER-koneen (DC3FREE) lahjana.
        """
        # Tukikohtaoptiot ja hinnan laskenta aloitusrahasta
        options = [
            {"icao": "EFHK", "name": "Helsinki-Vantaa", "factor": Decimal("0.30")},
            {"icao": "LFPG", "name": "Paris Charles de Gaulle", "factor": Decimal("0.50")},
            {"icao": "KJFK", "name": "New York JFK", "factor": Decimal("0.70")},
        ]
        for o in options:
            o["price"] = (starting_cash * o["factor"]).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)

        # Tulostetaan vaihtoehdot
        print("\n=== Valitse ensimmäinen tukikohta ===")
        for i, o in enumerate(options, start=1):
            print(f"{i}) {o['name']} ({o['icao']}) | Hinta: {self._fmt_money(o['price'])}")

        # Pakotetaan kelvollinen valinta
        while True:
            sel = input("Valinta numerolla (1-3): ").strip()
            try:
                idx = int(sel)
                if 1 <= idx <= len(options):
                    break
                else:
                    print("Valitse numero 1-3.")
            except ValueError:
                print("Anna numero 1-3.")

        chosen = options[idx - 1]
        base_ident = chosen["icao"]
        base_name = chosen["name"]
        base_cost = chosen["price"]

        # Kassan riittävyys – tässä vaiheessa pitäisi riittää, mutta tarkistan silti
        if self.cash < base_cost:
            raise RuntimeError(
                f"Kassa ei riitä tukikohtaan {base_ident}. Tarvitaan {self._fmt_money(base_cost)}, "
                f"mutta kassassa on {self._fmt_money(self.cash)}."
            )

        # Luon owned_bases-rivin + SMALL-upgraden atomisesti ja veloitan hinnan
        base_id = self._create_owned_base_and_small_upgrade_tx(
            base_ident=base_ident,
            base_name=base_name,
            purchase_cost=base_cost,
        )
        print(f"Ostit tukikohdan: {base_name} ({base_ident}) hintaan {self._fmt_money(base_cost)}.")

        # Lisään iso-isän STARTER-lahjakoneen (DC3FREE) tukikohtaan; EI NÄY KAUPASSA
        self._insert_gift_aircraft_tx(
            model_code="DC3FREE",
            current_airport_ident=base_ident,
            base_id=base_id,
            nickname="Iso-isän DC-3",
        )
        print("Iso-isä lahjoitti ensimmäisen Douglas DC-3 -lentokoneen tukikohtaasi. Onnea matkaan!")

    # ---------- Päävalikko ----------

    def main_menu(self):
        """
        Päävalikon looppi – laivasto, kauppa, koneiden päivitykset,
        tehtävät ja ajan kulku.
        """
        while True:
            home_ident = self._get_primary_base_ident() or "-"
            print("\n=== Päävalikko ===")
            print(
                f"Päivä: {self.current_day} | Kassa: {self._fmt_money(self.cash)} | Pelaaja: {self.player_name} | Tukikohta: {home_ident}")
            print("1) Listaa koneet")
            print("2) Kauppa (osta kone)")
            print("3) Päivitä konetta (upgrade)")
            print("4) Aktiiviset tehtävät")
            print("5) Aloita uusi tehtävä")
            print("6) Seuraava päivä")
            print("0) Poistu")

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
                self.advance_to_next_day()
            elif choice == "0":
                print("Heippa!")
                break
            else:
                print("Virheellinen valinta.")

    # ---------- Listaus ----------

    def list_aircraft(self):
        """
        Listaan kaikki aktiiviset koneet ja näytän perusinfot + upgradet.
        """
        planes = init_airplanes(self.save_id, include_sold=False)
        if not planes:
            print("Sinulla ei ole vielä koneita.")
            input("\nPaina Enter jatkaaksesi...")
            return

        # Haen kerralla päivitystasot
        upgrade_levels = self._fetch_upgrade_levels([p.aircraft_id for p in planes])

        print("\nKoneesi:")
        for i, p in enumerate(planes, start=1):
            lvl = upgrade_levels.get(p.aircraft_id, 0)
            profit_mult = self._calc_profit_multiplier(lvl)
            bonus_pct = (profit_mult - Decimal("1.0")) * Decimal("100")
            bonus_str = f"+{bonus_pct.quantize(Decimal('1.'), rounding=ROUND_HALF_UP)}%"

            print(f"\n#{i} {getattr(p, 'model_name', None) or p.model_code} ({p.registration}) @ {p.current_airport_ident}")
            print(f"  Ostohinta: {self._fmt_money(p.purchase_price)} | Kunto: {p.condition_percent}% | Status: {p.status}")
            print(f"  Tunnit: {p.hours_flown} h | Hankittu päivä: {p.acquired_day}")
            print(f"  Upgrade-taso: {lvl} | Tuottavuusbonus: {bonus_str}")

        input("\nPaina Enter jatkaaksesi...")

    # ---------- Kauppa ----------

    def shop_menu(self):
        """
        Kauppa listaa konemallit tukikohdan edistymisen mukaan:
        - STARTER-kategoriaa EI näytetä koskaan.
        - Näkyvät kategoriat määräytyvät korkeimman base_upgrades-tason (SMALL..HUGE) mukaan.
        """
        # Haen sallittujen kategorioiden mallit yhdellä kyselyllä
        models = self._fetch_aircraft_models_by_base_progress()
        if not models:
            print("Kaupasta ei löytynyt malleja nykyisellä tukikohdan tasolla.")
            input("\nPaina Enter jatkaaksesi...")
            return

        print("\n=== Kauppa ===")
        for idx, m in enumerate(models, start=1):
            price = Decimal(str(m["purchase_price"]))
            print(
                f"{idx}) {m['manufacturer']} {m['model_name']} "
                f"({m['model_code']}) | Hinta: {self._fmt_money(price)} | "
                f"Cargo: {m['base_cargo_kg']} kg | Range: {m['range_km']} km | "
                f"Nopeus: {m['cruise_speed_kts']} kts | Luokka: {m['category']}"
            )

        sel = input("\nValitse ostettava malli numerolla (tyhjä = peruuta): ").strip()
        if not sel:
            return
        try:
            sel_i = int(sel)
            if not (1 <= sel_i <= len(models)):
                print("Virheellinen valinta.")
                return
        except ValueError:
            print("Virheellinen valinta.")
            return

        model = models[sel_i - 1]
        price = Decimal(str(model["purchase_price"]))
        if self.cash < price:
            print(f"Kassa ei riitä. Tarvitset {self._fmt_money(price)}, sinulla on {self._fmt_money(self.cash)}.")
            input("\nPaina Enter jatkaaksesi...")
            return

        # Oletuskenttä ja base_id: käytän ensimmäistä omistettua tukikohtaa
        default_base = self._get_primary_base()
        default_airport_ident = default_base["base_ident"] if default_base else "EFHK"
        current_airport_ident = input(f"Valitse kenttä (ICAO/IATA) [{default_airport_ident}]: ").strip().upper() or default_airport_ident

        # Yritän linkittää ostettavan koneen base_id:hen valinnan perusteella (jos pelaajalla useampi base)
        base_id_for_plane = self._get_base_id_by_ident(current_airport_ident) or (default_base["base_id"] if default_base else None)

        # Rekisteri generoidaan, ellei anneta
        registration = input("Syötä rekisteri (tyhjä = generoidaan): ").strip().upper()
        if not registration:
            registration = self._generate_registration()
            print(f"Luotiin rekisteri: {registration}")

        nickname = input("Anna lempinimi (optional): ").strip() or None

        confirm = input(
            f"Vahvista osto: {model['manufacturer']} {model['model_name']} hintaan {self._fmt_money(price)} (k/e): "
        ).strip().lower()
        if confirm != "k":
            print("Peruutettu.")
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
            print(f"Osto valmis. Kone {registration} lisätty laivastoon.")
        else:
            print("Osto epäonnistui.")
        input("\nPaina Enter jatkaaksesi...")

    # ---------- Päivitykset (koneet) ----------

    def upgrade_menu(self):
        """
        Yksinkertainen konepäivitysten (ei tukikohdan) valikko.
        """
        planes = init_airplanes(self.save_id, include_sold=False)
        if not planes:
            print("Sinulla ei ole vielä koneita.")
            input("\nPaina Enter jatkaaksesi...")
            return

        levels = self._fetch_upgrade_levels([p.aircraft_id for p in planes])

        print("\nValitse päivitettävä kone:")
        for i, p in enumerate(planes, start=1):
            lvl = levels.get(p.aircraft_id, 0)
            next_lvl = lvl + 1
            cost = self._calc_upgrade_cost(p.purchase_price, next_lvl)
            print(
                f"{i}) {getattr(p, 'model_name', None) or p.model_code} ({p.registration}) | "
                f"Taso: {lvl} -> {next_lvl} | Hinta: {self._fmt_money(cost)}"
            )

        sel = input("Valinta numerolla (tyhjä = peruuta): ").strip()
        if not sel:
            return
        try:
            sel_i = int(sel)
            if sel_i < 1 or sel_i > len(planes):
                print("Virheellinen valinta.")
                return
        except ValueError:
            print("Virheellinen valinta.")
            return

        plane = planes[sel_i - 1]
        cur_lvl = levels.get(plane.aircraft_id, 0)
        new_lvl = cur_lvl + 1
        cost = self._calc_upgrade_cost(plane.purchase_price, new_lvl)
        profit_mult = self._calc_profit_multiplier(new_lvl)
        bonus_pct = (profit_mult - Decimal("1.0")) * Decimal("100")

        if self.cash < cost:
            print(f"Kassa ei riitä päivitykseen. Tarvitset {self._fmt_money(cost)}, sinulla on {self._fmt_money(self.cash)}.")
            input("\nPaina Enter jatkaaksesi...")
            return

        print(
            f"\nPäivitetään {getattr(plane, 'model_name', None) or plane.model_code} ({plane.registration}) "
            f"tasolta {cur_lvl} tasolle {new_lvl}"
        )
        print(f"Hinta: {self._fmt_money(cost)} | Uusi tuottavuusbonus: +{bonus_pct.quantize(Decimal('1.'), rounding=ROUND_HALF_UP)}%")
        confirm = input("Vahvista (k/e): ").strip().lower()
        if confirm != "k":
            print("Peruutettu.")
            return

        try:
            # Tallennan päivitystason ja veloitan kassan loogisena operaatioina
            db_upgrade_airplane(plane.aircraft_id, UPGRADE_CODE, new_lvl, self.current_day)
            self._add_cash(-cost)
            print("Päivitys tehty.")
        except Exception as e:
            print(f"Päivitys epäonnistui: {e}")

        input("\nPaina Enter jatkaaksesi...")

    # ---------- Lentokenttähaku -----------

    def _get_airport_coords(self, ident: str):
        """
        (Oma apu) Haen kentän koordinaatit airport-taulusta.
        - Palautan (lat, lon) floatteina tai None, jos data puuttuu.
        - Käytän täällä omia muuttujia 'yhteys' ja 'kursori' SQL:ää varten.
        """
        yhteys = get_connection()
        try:
            # Yritän ensin dictionary-kursorin (esim. MySQL), muuten fallback
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
                # Jos ei dictionary-kurssoria, indeksoin positioilla
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

    # --------- Random kohteen valinta ---------------------

    def _pick_random_destinations(self, n: int, exclude_ident: str):
        """
        (Oma apu) Haen n satunnaista kohdekenttää airport-taulusta.
        - En valitse samaa kenttää kuin lähtökenttä (exclude_ident).
        - Pidän kiinni tavanomaisista lentokenttätyypeistä (small/medium/large).
        - Palautan listan dict-olioita: {ident, name}
        """
        yhteys = get_connection()
        try:
            # Yritän dictionary=True, fallback jos ei onnistu
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

    # --------- Etäisyyslaskuri -------------------

    def _haversine_km(self, lat1, lon1, lat2, lon2) -> float:
        """
        (Oma apu) Haversine-kaava kahden pisteen väliseen etäisyyteen (km).
        - Tässä ei ole SQL:ää, joten ei yhteys/kursori-tarvetta.
        """

        R = 6371.0  # maan säde kilometreissä
        phi1, phi2 = math.radians(lat1), math.radians(lat2)
        dphi = math.radians(lat2 - lat1)
        dl = math.radians(lon2 - lon1)
        a = math.sin(dphi / 2) ** 2 + math.cos(phi1) * math.cos(phi2) * math.sin(dl / 2) ** 2
        c = 2 * math.atan2(math.sqrt(a), math.sqrt(1 - a))
        return R * c

    # ---------- Tehtävägeneraattori --------------

    def _random_task_offers_for_plane(self, plane, count: int = 5):
        """
        (Oma apu) Generoin 'count' kpl tämän päivän tarjouksia annetulle koneelle.
        - Aika vähintään 1 päivä (base_days >= 1).
        - Jos rahti ylittää kapasiteetin: trips = ceil(payload / capacity),
          total_days = base_days * trips (shuttle-ajoa edestakaisin).
        - Palkkio huomioi koneen eco_multiplierin.
        Palautan listan, jossa jokainen alkio on dict:
          {dest_ident, dest_name, payload_kg, distance_km, base_days, trips, total_days, reward, penalty, deadline}
        """
        import math
        import random
        from decimal import Decimal

        dep_ident = plane["current_airport_ident"]
        speed_kts = float(plane.get("cruise_speed_kts") or 200.0)
        speed_km_per_day = max(1.0, speed_kts * 1.852 * 24.0)  # kt -> km/h -> km/päivä
        capacity = int(plane.get("base_cargo_kg") or 0) or 1
        eco_mult = float(plane.get("eco_multiplier") or 1.0)

        # Haen vähän ylimääräisiä kohteita (count*2), jos osa karsiutuu koordinaattipuutteiden takia
        dests = self._pick_random_destinations(count * 2, dep_ident)
        offers = []

        for d in dests:
            if len(offers) >= count:
                break

            dest_ident = d["ident"]

            # Hae koordinaatit; jos puuttuu -> ohitan tämän kohteen
            dep_xy = self._get_airport_coords(dep_ident)
            dst_xy = self._get_airport_coords(dest_ident)
            if not (dep_xy and dst_xy):
                continue

            # Lasketaan etäisyys (km)
            dist_km = self._haversine_km(dep_xy[0], dep_xy[1], dst_xy[0], dst_xy[1])

            # Generoin rahtimäärän etäisyydestä riippuen (saa ylittää kapasiteetin)
            if dist_km < 500:
                payload = random.randint(max(1, capacity // 2), max(1, capacity * 3))
            elif dist_km < 1500:
                payload = random.randint(capacity, capacity * 4)
            else:
                payload = random.randint(capacity * 2, capacity * 6)

            # Kesto ja shuttle-lähtöjen määrä
            base_days = max(1, math.ceil(dist_km / speed_km_per_day))
            trips = max(1, math.ceil(payload / capacity))
            total_days = base_days * trips

            # Palkkio (sis. eco_multiplier): rahtipaino + etäisyys
            per_kg = 1.6
            per_km = 0.45
            raw_reward = (payload * per_kg + dist_km * per_km) * eco_mult
            reward = Decimal(str(round(raw_reward, 2)))
            penalty = (reward * Decimal("0.30")).quantize(Decimal("0.01"))

            # Deadline = kokonaiskesto + pufferi (puolikas trips, vähintään 1)
            buffer_days = max(1, trips // 2)
            deadline = self.current_day + total_days + buffer_days

            offers.append({
                "dest_ident": dest_ident,
                "dest_name": d.get("name"),
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

    # ---------- Aktiiviset tehtävät --------------

    def show_active_tasks(self):
        """
        Listaa aktiiviset tehtävät (contracts.status IN ('ACCEPTED','IN_PROGRESS')).
        Näyttää myös lennon arvion/saapumispäivän jos löytyy.
        """
        yhteys = get_connection()
        try:
            kursori = yhteys.cursor(dictionary=True)
        except TypeError:
            kursori = yhteys.cursor()
        try:
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
                print("\nEi aktiivisia tehtäviä.")
                input("\nPaina Enter jatkaaksesi...")
                return

            print("\n=== Aktiiviset tehtävät ===")
            for r in rows:
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
                left_days = (deadline - self.current_day) if deadline is not None else None
                late = left_days is not None and left_days < 0

                print(
                    f"- #{cid} -> {dest} | Kone: {reg or '-'} | Kuorma: {int(payload)} kg | Palkkio: {self._fmt_money(reward)} | "
                    f"DL: {deadline} ({'myöhässä' if late else f'{left_days} pv jäljellä'}) | "
                    f"Tila: {status}{f' / Lento: {fl_status}, ETA {arr_day}' if arr_day is not None else ''}")
            input("\nPaina Enter jatkaaksesi...")
        finally:
            try:
                kursori.close()
            except Exception:
                pass
            yhteys.close()

    # ---------- Aloita uusi tehtävä -------------

    def start_new_task(self):
        """
        Aloitan uuden tehtävän seuraavasti (opiskelijakommentit):
          1) Haen vapaat (IDLE) koneet ja pelaaja valitsee yhden.
          2) Generoin tälle koneelle tämän päivän hetkelliset tarjoukset (EI talleteta kantaan).
          3) Näytän tarjoukset, pelaaja valitsee ja vahvistaa.
          4) Vasta vahvistuksen jälkeen luon contracts + flights -rivit ja merkitsen koneen BUSY.
        Huomio:
          - Palkkio ottaa mukaan koneen eco_multiplierin.
          - Pelaajan rahaa EI päivitetä tässä, vaan vasta advance_to_next_day:ssa kun lento on saapunut.
        """
        from decimal import Decimal

        yhteys = get_connection()
        try:
            # Yritän dictionary-kurssoria (MySQL-tyyli), mutta fallback tarvittaessa
            try:
                kursori = yhteys.cursor(dictionary=True)
            except TypeError:
                kursori = yhteys.cursor()

            # 1) Vapaat koneet + tarvitut mallikentät (eco_multiplier mukaan)
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
                print("Ei vapaita (IDLE) koneita.")
                input("\nPaina Enter jatkaaksesi...")
                return

            print("\nValitse kone tehtävään:")
            for i, p in enumerate(planes, start=1):
                cap = int(p["base_cargo_kg"] if isinstance(p, dict) else 0)
                eco = float(p.get("eco_fee_multiplier", 1.0) if isinstance(p, dict) else 1.0)
                print(
                    f"{i}) {p['registration']} {p['model_name']} @ {p['current_airport_ident']} | Cargo {cap} kg | Eco x{eco}")

            sel = input("Valinta numerolla (tyhjä = peruuta): ").strip()
            if not sel:
                return
            try:
                idx = int(sel)
                if idx < 1 or idx > len(planes):
                    print("Virheellinen valinta.")
                    return
            except ValueError:
                print("Virheellinen valinta.")
                return

            plane = planes[idx - 1]

            # 2) Generoin juuri tälle koneelle tämän päivän tarjoukset (ei vielä DB-merkintöjä)
            offers = self._random_task_offers_for_plane(plane, count=5)
            if not offers:
                print("Ei tarjouksia saatavilla juuri nyt (koordinaattipuutteita tms.).")
                input("\nPaina Enter jatkaaksesi...")
                return

            print("\n=== Tarjolla olevat tehtävät (voimassa tänään) ===")
            for i, o in enumerate(offers, start=1):
                print(
                    f"{i}) {plane['current_airport_ident']} -> {o['dest_ident']} "
                    f"({o['dest_name'] or '-'}) | Rahti: {o['payload_kg']} kg | "
                    f"Etäisyys: {int(o['distance_km'])} km | Lähtöjä: {o['trips']} | "
                    f"Kesto: {o['total_days']} pv | Palkkio: {self._fmt_money(o['reward'])} | "
                    f"Sakko: {self._fmt_money(o['penalty'])} | DL: {o['deadline']}"
                )

            sel = input("Valitse tehtävä numerolla (tyhjä = peruuta): ").strip()
            if not sel:
                return
            try:
                oidx = int(sel)
                if oidx < 1 or oidx > len(offers):
                    print("Virheellinen valinta.")
                    return
            except ValueError:
                print("Virheellinen valinta.")
                return

            offer = offers[oidx - 1]

            # 3) Varmistan valinnan ennen tietokantakirjoituksia
            print("\nTehtäväyhteenveto:")
            print(
                f"Lähtö: {plane['current_airport_ident']} -> Kohde: {offer['dest_ident']} | "
                f"Rahti: {offer['payload_kg']} kg | Lähtöjä: {offer['trips']} | "
                f"Kesto: {offer['total_days']} pv | Palkkio: {self._fmt_money(offer['reward'])} | "
                f"Deadline: päivä {offer['deadline']}"
            )
            ok = input("Aloitetaanko tehtävä? (k/e): ").strip().lower()
            if ok != "k":
                print("Peruutettu.")
                return

            # 4) Teen transaktion: contract + flight + kone BUSY
            now_day = self.current_day
            total_dist = float(offer["distance_km"]) * offer["trips"]
            arr_day = now_day + offer["total_days"]

            try:
                yhteys.start_transaction()

                # Sopimus: IN_PROGRESS heti, koska aloitetaan nyt
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

                # Lento: aggregoitu “shuttle”-lento (distance_km = yksisuuntainen * trips)
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
                        0.0, Decimal("0.00"), plane["current_airport_ident"], offer["dest_ident"],
                        plane["aircraft_id"], self.save_id, contract_id
                    ),
                )

                # Kone varatuksi
                kursori.execute(
                    "UPDATE aircraft SET status = 'BUSY' WHERE aircraft_id = %s",
                    (plane["aircraft_id"],)
                )

                yhteys.commit()
                print(
                    f"Tehtävä #{contract_id} aloitettu. Arvioitu saapumispäivä: {arr_day} (lähtöjä {offer['trips']}).")
                print("Huom: Palkkio hyvitetään vasta, kun lento on saapunut (advance_to_next_day).")

            except Exception as e:
                yhteys.rollback()
                print(f"Tehtävän aloitus epäonnistui: {e}")
                return

            input("\nPaina Enter jatkaaksesi...")

        finally:
            try:
                kursori.close()
            except Exception:
                pass
            yhteys.close()


    # ---------- Seuraava päivä funktio -----------

    def advance_to_next_day(self):
        """
        Siirrän päivän eteenpäin ja prosessoin saapuneet lennot (opiskelijakommentit):
          - Flight ENROUTE -> ARRIVED
          - Aircraft BUSY -> IDLE (ja siirrän koneen saapumiskentälle)
          - Contract IN_PROGRESS -> COMPLETED tai COMPLETED_LATE (deadline tarkistus)
          - Pelaajan kassa päivitetään vasta tässä (summaan kaikki päivän ansiot)
        Käytän SQL:ssä muuttujia 'yhteys' ja 'kursori'.
        """
        from decimal import Decimal
        from datetime import datetime

        new_day = self.current_day + 1
        yhteys = get_connection()
        try:
            # Dictionary-kursori jos mahdollista
            try:
                kursori = yhteys.cursor(dictionary=True)
            except TypeError:
                kursori = yhteys.cursor()

            try:
                yhteys.start_transaction()

                # Päivän vaihto tallennukseen (pidän myös updated_at ajan tasalla)
                kursori.execute(
                    "UPDATE game_saves SET current_day = %s, updated_at = %s WHERE save_id = %s",
                    (new_day, datetime.utcnow(), self.save_id),
                )

                # Haen lennot, jotka ehtivät saapua uuteen päivään mennessä
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

                total_delta = Decimal("0.00")

                for r in arrivals:
                    rd = r if isinstance(r, dict) else None
                    flight_id = rd["flight_id"] if rd else r[0]
                    contract_id = rd["contract_id"] if rd else r[1]
                    aircraft_id = rd["aircraft_id"] if rd else r[2]
                    arr_ident = rd["arr_ident"] if rd else r[3]
                    deadline = int(rd["deadline_day"] if rd else r[5])
                    reward = Decimal(str(rd["reward"] if rd else r[6]))
                    penalty = Decimal(str(rd["penalty"] if rd else r[7]))

                    # 1) Lennon tila: ARRIVED
                    kursori.execute("UPDATE flights SET status = 'ARRIVED' WHERE flight_id = %s", (flight_id,))

                    # 2) Kone vapaaksi ja kenttä päivittyy saapumiskenttään
                    kursori.execute(
                        "UPDATE aircraft SET status = 'IDLE', current_airport_ident = %s WHERE aircraft_id = %s",
                        (arr_ident, aircraft_id),
                    )

                    # 3) Sopimus valmiiksi ja lasketaan, onko myöhässä
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

                # 4) Hyvitetään kaikki päivän ansiot yhdellä kertaa (lukitsen rivin varmuuden vuoksi)
                if total_delta != Decimal("0.00"):
                    kursori.execute("SELECT cash FROM game_saves WHERE save_id = %s FOR UPDATE", (self.save_id,))
                    row = kursori.fetchone()
                    cur_cash = Decimal(str(row["cash"] if isinstance(row, dict) else row[0]))
                    new_cash = (cur_cash + total_delta).quantize(Decimal("0.01"))
                    kursori.execute("UPDATE game_saves SET cash = %s WHERE save_id = %s", (new_cash, self.save_id))
                    self.cash = new_cash  # päivitän myös muistissa olevan arvon

                yhteys.commit()
                self.current_day = new_day

                gained = f", ansaittu {self._fmt_money(total_delta)}" if arrivals else ""
                print(f"Päivä siirtyi eteenpäin: {new_day}{gained}.")
                input("\nPaina Enter jatkaaksesi...")

            except Exception as e:
                yhteys.rollback()
                print(f"Seuraava päivä -käsittely epäonnistui: {e}")

        finally:
            try:
                kursori.close()
            except Exception:
                pass
            yhteys.close()

    # ---------- DB: tallennuksen lataus ----------

    def _refresh_save_state(self):
        """
        Täydennän puuttuvat kentät (nimi, kassa, päivä, status, rng_seed, difficulty) game_saves-taulusta.
        """
        need = any(v is None for v in (self.player_name, self.cash, self.current_day, self.status))
        if not need:
            return

        yhteys = get_connection()
        try:
            # Yritän dict-kursoria – helpottaa kenttien käsittelyä
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
                self.cash = Decimal(str(r["cash"]))
                self.difficulty = r.get("difficulty") or self.difficulty
                self.current_day = int(r["current_day"])
                self.status = r["status"]
                self.rng_seed = r.get("rng_seed")
            else:
                self.player_name = r[0]
                self.cash = Decimal(str(r[1]))
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

    # ---------- DB: mallit ja rajoitus tukikohdan tason mukaan ----------

    def _fetch_aircraft_models_by_base_progress(self) -> List[dict]:
        """
        Palautan listan myynnissä olevista konemalleista, rajattuna korkeimman
        tukikohdan upgradetason (SMALL..HUGE) mukaan. STARTER-kategoria jätetään pois.
        Toteutan rajoituksen SQL:ssä, jotta ei tarvitse suodattaa Pythonissa.
        """
        yhteys = get_connection()
        kursori = yhteys.cursor(dictionary=True)
        try:
            # teen MAX-tierin subquerynä – CASE muuntaa SMALL..HUGE -> 1..4
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
                WHERE
                  am.category <> 'STARTER' -- STARTER ei kuulu kauppaan
                  AND
                  CASE am.category
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

    # ---------- DB: tukikohdan luonti + SMALL-upgrade ----------

    def _create_owned_base_and_small_upgrade_tx(self, base_ident: str, base_name: str, purchase_cost: Decimal) -> int:
        """
        Luo owned_bases-rivin ja lisää base_upgrades-tauluun SMALL-rivin.
        Veloittaa hinnan kassasta. Palauttaa base_id:n.
        Kaikki tehdään yhdessä transaktiossa, jottei jää vajaita rivejä.
        """
        yhteys = get_connection()
        kursori = yhteys.cursor()
        try:
            # Lukitsen tallennuksen rivin – näin kassa ei muutu yllättäen
            kursori.execute("SELECT cash FROM game_saves WHERE save_id = %s FOR UPDATE", (self.save_id,))
            row = kursori.fetchone()
            if not row:
                raise ValueError("Tallennetta ei löytynyt tukikohtaa luodessa.")
            cur_cash = Decimal(str(row["cash"])) if isinstance(row, dict) else Decimal(str(row[0]))
            if cur_cash < purchase_cost:
                raise ValueError("Kassa ei riitä tukikohdan ostoon.")

            # Luon owned_bases-rivin
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
            base_id = kursori.lastrowid

            # Lisään SMALL-upgraden (historiarivi; kustannus 0 tässä kohtaa)
            kursori.execute(
                """
                INSERT INTO base_upgrades (base_id, upgrade_code, installed_day, upgrade_cost)
                VALUES (%s, %s, %s, %s)
                """,
                (base_id, "SMALL", self.current_day, Decimal("0.00")),
            )

            # Päivitän kassan ja aikaleiman
            new_cash = (cur_cash - purchase_cost).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
            kursori.execute(
                "UPDATE game_saves SET cash = %s, updated_at = %s WHERE save_id = %s",
                (new_cash, now, self.save_id),
            )

            yhteys.commit()
            self.cash = new_cash
            return int(base_id)
        except Exception:
            yhteys.rollback()
            raise
        finally:
            try:
                kursori.close()
            except Exception:
                pass
            yhteys.close()

    # ---------- DB: kassat ----------

    def _set_cash(self, new_cash: Decimal):
        """
        Päivitän kassan arvon game_saves-tauluun ja pidän oliotilan synkassa.
        """
        yhteys = get_connection()
        kursori = yhteys.cursor()
        try:
            kursori.execute(
                "UPDATE game_saves SET cash = %s, updated_at = %s WHERE save_id = %s",
                (Decimal(new_cash), datetime.utcnow(), self.save_id),
            )
            yhteys.commit()
            self.cash = Decimal(new_cash)
        except Exception:
            yhteys.rollback()
            raise
        finally:
            try:
                kursori.close()
            except Exception:
                pass
            yhteys.close()

    def _add_cash(self, delta: Decimal):
        """
        Lisään tai vähennän kassasta ja varmistan ettei mennä negatiiviseksi.
        """
        new_val = (self.cash + Decimal(delta)).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
        if new_val < Decimal("0"):
            raise ValueError("Kassa ei voi mennä negatiiviseksi.")
        self._set_cash(new_val)

    # ---------- DB: ostot ----------

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
        Ostotapahtuma atomisesti: lukitsen kassan, lisään koneen (linkitys base_id:hen, jos löytyy),
        veloitan hinnan ja päivitän aikaleiman.
        """
        yhteys = get_connection()
        kursori = yhteys.cursor()
        try:
            # Lukitsen save-rivin
            kursori.execute("SELECT cash FROM game_saves WHERE save_id = %s FOR UPDATE", (self.save_id,))
            row = kursori.fetchone()
            if not row:
                raise ValueError("Tallennetta ei löytynyt ostohetkellä.")
            cash_now = Decimal(str(row["cash"])) if isinstance(row, dict) else Decimal(str(row[0]))
            if cash_now < purchase_price:
                yhteys.rollback()
                return False

            # Lisään koneen
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
                    1,  # base_level
                    current_airport_ident,
                    registration,
                    nickname,
                    self.current_day,
                    purchase_price,
                    100,  # uutta vastaava
                    "IDLE",
                    0,
                    None,
                    None,
                    self.save_id,
                    base_id,  # linkitys omistettuun tukikohtaan, jos annettu
                ),
            )

            # Veloitan kassan
            new_cash = (cash_now - purchase_price).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
            kursori.execute(
                "UPDATE game_saves SET cash = %s, updated_at = %s WHERE save_id = %s",
                (new_cash, datetime.utcnow(), self.save_id),
            )

            yhteys.commit()
            self.cash = new_cash
            return True
        except Exception as e:
            print(f"Virhe ostossa: {e}")
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
    ):
        """
        Lisään lahjakoneen (STARTER: DC3FREE) turvallisesti transaktion sisällä.
        Ostohinta on 0. Linkitän koneen pelaajan omistamaan tukikohtaan (base_id).
        """
        # Teen lahjarekisterin muotoa GIFT-XX99
        registration = f"GIFT-{self._rand_letters(2)}{self._rand_digits(2)}"

        yhteys = get_connection()
        kursori = yhteys.cursor()
        try:
            # Lukitsen tallennuksen rivin varmuuden vuoksi
            kursori.execute("SELECT save_id FROM game_saves WHERE save_id = %s FOR UPDATE", (self.save_id,))
            r = kursori.fetchone()
            if not r:
                raise ValueError("Tallennetta ei löytynyt lahjakonetta lisättäessä.")

            # Lisään STARTER-lahjakoneen
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

            # Päivitän updated_at
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

    # ---------- DB: apurit tukikohtiin ----------

    def _get_primary_base(self) -> Optional[dict]:
        """
        Palautan ensimmäisen ostetun tukikohdan rivin dictinä tai None jos puuttuu.
        """
        yhteys = get_connection()
        # käytän dictionary-kurssoria selkeyden vuoksi
        try:
            kursori = yhteys.cursor(dictionary=True)
        except TypeError:
            kursori = yhteys.cursor()
        try:
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
        Palautan ensimmäisen ostetun tukikohdan ICAO-tunnuksen.
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

    # ---------- DB: koneupgrade-tasot ----------

    def _fetch_upgrade_levels(self, aircraft_ids: List[int]) -> Dict[int, int]:
        """
        Haen (aircraft_id -> upgrade-level) -mappauksen yhdellä kyselyllä.
        """
        if not aircraft_ids:
            return {}

        yhteys = get_connection()
        kursori = yhteys.cursor()
        try:
            placeholders = ",".join(["%s"] * len(aircraft_ids))
            kursori.execute(
                f"""
                SELECT aircraft_id, level
                FROM aircraft_upgrades
                WHERE upgrade_code = %s AND aircraft_id IN ({placeholders})
                """,
                tuple([UPGRADE_CODE] + aircraft_ids),
            )
            rows = kursori.fetchall() or []
            if rows and isinstance(rows[0], dict):
                return {int(r["aircraft_id"]): int(r["level"]) for r in rows}
            return {int(r[0]): int(r[1]) for r in rows}
        finally:
            try:
                kursori.close()
            except Exception:
                pass
            yhteys.close()

    # ---------- Logiikka: hinnat ja vaikutukset ----------

    def _calc_upgrade_cost(self, purchase_price: Decimal, new_level: int) -> Decimal:
        """
        Konepäivityksen hinta: ~30 % ostohinnasta, kasvaa +10 % per taso.
        Esim: lvl1: 30%, lvl2: 33%, lvl3: 36%, ...
        """
        base = (Decimal(purchase_price) * Decimal("0.30"))
        factor = (Decimal("1.0") + Decimal("0.10") * Decimal(max(0, new_level - 1)))
        cost = (base * factor).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
        return cost

    def _calc_profit_multiplier(self, level: int) -> Decimal:
        """
        Tuottavuuskerroin: 1.05^level; tulostukseen pyöristän neljään desimaaliin.
        """
        if level <= 0:
            return Decimal("1.00")
        mult = (Decimal("1.05") ** Decimal(level))
        return mult.quantize(Decimal("0.0001"), rounding=ROUND_HALF_UP)

    # ---------- Aputyökalut ----------

    def _generate_registration(self) -> str:
        """
        Teen nopean, simppelin rekisterin N-XXXX -muodossa.
        """
        letters = "".join(random.choices(string.ascii_uppercase, k=2))
        digits = "".join(random.choices(string.digits, k=2))
        return f"N-{letters}{digits}"

    def _rand_letters(self, n: int) -> str:
        """
        Pieni apuri lahjarekisteriä varten – satunnaiset isot kirjaimet.
        """
        return "".join(random.choices(string.ascii_uppercase, k=n))

    def _rand_digits(self, n: int) -> str:
        """
        Pieni apuri lahjarekisteriä varten – satunnaiset numerot.
        """
        return "".join(random.choices(string.digits, k=n))

    def _fmt_money(self, val) -> str:
        """
        Siisti rahamuotoilu kahdella desimaalilla.
        """
        d = Decimal(str(val)).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
        return f"{d} €"
