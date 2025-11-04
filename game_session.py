# game_session.py
# ----------------
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

"""
===== RNG-SIEMENEN TESTAAMINEN =====

Näin voit testata että RNG-siemen toimii oikein:

1. Käynnistä peli kahdesti SAMALLA siemenellä (esim. 42):

   Peli 1:
   - Nimi: "Testi1"
   - Siemen: 42
   - Valitse EFHK
   - Aloita tehtävä DC-3:lla
   - Katso mitä tehtäviä tarjotaan

   Peli 2:
   - Nimi: "Testi2"  (nimi voi olla eri!)
   - Siemen: 42      (TÄMÄ ON TÄRKEÄ - sama numero!)
   - Valitse EFHK
   - Aloita tehtävä DC-3:lla
   - Katso mitä tehtäviä tarjotaan

   TULOS: Tehtävät ovat IDENTTISIÄ molemmissa peleissä!
   (määränpäät, rahtimäärät, palkkiot - kaikki sama)

2. Käynnistä peli ILMAN siementä (tyhjä):

   Peli 3:
   - Nimi: "Testi3"
   - Siemen: [tyhjä - paina vain Enter]
   - Valitse EFHK
   - Aloita tehtävä DC-3:lla

   TULOS: Tehtävät ovat ERILAISET kuin peleissä 1 ja 2!

3. Testaa pikakelaus:

   Peli 4 ja 5 - molemmat siemenellä 42:
   - Etene 10 päivää pikakelaamalla
   - Katso mitä tapahtui (saapumiset, ansiot)

   TULOS: Molemmat pelit antavat IDENTTISET tulokset!

"""

import logging
import math
import random
import string
import time
from typing import List, Optional, Dict, Set
from decimal import Decimal, ROUND_HALF_UP, getcontext
from datetime import datetime
from utils import get_connection
from airplane import init_airplanes, upgrade_airplane as db_upgrade_airplane
from event_system import init_events_for_seed, get_event_for_day, FlightEvent
from session_helpers import (
    _to_dec,
    _icon_title,
    fetch_player_aircrafts_with_model_info,
    get_current_aircraft_upgrade_state,
    compute_effective_eco_multiplier,
    calc_aircraft_upgrade_cost,
    apply_aircraft_upgrade,
    get_effective_eco_for_aircraft,
    fetch_owned_bases,
    fetch_base_current_level_map,
    insert_base_upgrade,
)

# Konfiguraatiot yhdessä paikassa
from upgrade_config import (
    UPGRADE_CODE,
    HQ_MONTHLY_FEE,
    MAINT_PER_AIRCRAFT,
    BILL_GROWTH_RATE,
    STARTER_MAINT_DISCOUNT,
    REPAIR_COST_PER_PERCENT,
    SURVIVAL_TARGET_DAYS,
)

# Decimal-laskennan tarkkuus – rahalaskennassa on hyvä varata skaalaa
getcontext().prec = 28

logger = logging.getLogger(__name__)

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
        if self.rng_seed is not None:
            random.seed(self.rng_seed)

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

        # 🎲 Tapahtumakalenteri talteen heti alussa, jotta kaikki päivät
        # pysyvät samassa synkassa riippumatta siitä millä käyttöliittymällä
        # peliä pelataan.
        if session.rng_seed is not None:
            try:
                init_events_for_seed(session.rng_seed, SURVIVAL_TARGET_DAYS)
            except Exception as err:
                # Ei haluta pysäyttää peliä – logiikka toimii ilman tapahtumiakin.
                print(f"⚠️  Satunnaistapahtumien alustus epäonnistui: {err}")

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
        print("🎁 Iso-isä lahjoitti sinulle Douglas DC-3 -koneen ja velkansa. 🫣\nOnnea matkaan, tarvitset sitä!")
        input("↩︎ Enter jatkaa...")

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
            print("2) 🛒 Kauppapaikka")
            print("3) ♻️ Päivitykset")
            print("4) 📦 Aktiiviset tehtävät")
            print("5) ➕ Aloita uusi tehtävä")
            print("6) ⏭️ Seuraava päivä")
            print("7) 🎯 Etene kunnes ensimmäinen kone palaa")
            print("8) 🔧 Koneiden huolto")
            print("9) 📜 Näytä lokimerkinnät (20 uusinta)")
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
                    self.show_end_game_stats()
                    break
                if self.current_day >= SURVIVAL_TARGET_DAYS and self.status == "ACTIVE":
                    print(f"🏆 Onnea! Selvisit {SURVIVAL_TARGET_DAYS} päivää. Voitit pelin!")
                    self._set_status("VICTORY")
                    self.show_end_game_stats()
                    break

            elif choice == "7":
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

            elif choice == "8":
                # Huolto
                self.maintenance_menu()

            elif choice == "9":
                self.show_recent_event_log()

            elif choice == "666":
                # Shh, avaa salaisen Kas..Kerhohuoneen!
                self.clubhouse_menu()

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
            cond = getattr(p, "condition_percent", None)
            cond = int(cond if cond is not None else 0)
            broken_flag = " (RIKKI)" if cond < 100 else ""
            lvl = upgrade_levels.get(p.aircraft_id, 0)
            eco_now = get_effective_eco_for_aircraft(p.aircraft_id)
            print(f"\n#{i:>2} ✈️  {(getattr(p, 'model_name', None) or p.model_code)} ({p.registration}) @ {p.current_airport_ident}")
            print(f"   💶 Ostohinta: {self._fmt_money(p.purchase_price)} | 🔧 Kunto: {cond}%{broken_flag} | 🧭 Status: {p.status}")
            print(f"   ⏱️ Tunnit: {p.hours_flown} h | 📅 Hankittu päivä: {p.acquired_day}")
            print(f"   ♻️ ECO-taso: {lvl} | Efektiivinen eco-kerroin: x{eco_now:.2f}")

        input("\n↩︎ Enter jatkaaksesi...")

    def show_recent_event_log(self, limit: int = 20) -> None:
        """Tulosta viimeisimmät lokimerkinnät save_event_log-taulusta."""

        limit = max(1, int(limit))
        rows = []
        yhteys = get_connection()
        try:
            try:
                kursori = yhteys.cursor(dictionary=True)
            except TypeError:
                kursori = yhteys.cursor()

            try:
                kursori.execute(
                    """
                    SELECT log_id, event_day, event_type, payload, created_at
                    FROM save_event_log
                    WHERE save_id = %s
                    ORDER BY log_id DESC
                    LIMIT %s
                    """,
                    (self.save_id, limit),
                )
                rows = kursori.fetchall() or []
            finally:
                kursori.close()
        finally:
            yhteys.close()

        if not rows:
            print("ℹ️  Lokissa ei ole vielä merkintöjä.")
            input("\n↩︎ Enter jatkaaksesi...")
            return

        rows.reverse()

        _icon_title("Lokimerkinnät")
        for row in rows:
            if isinstance(row, dict):
                event_day = row.get("event_day")
                event_type = row.get("event_type")
                payload = row.get("payload")
                created_at = row.get("created_at")
            else:
                event_day, event_type, payload, created_at = row[1], row[2], row[3], row[4]

            if isinstance(created_at, datetime):
                created_str = created_at.strftime("%Y-%m-%d %H:%M:%S")
            else:
                created_str = str(created_at) if created_at is not None else "-"

            print(f"{created_str} | Päivä {event_day:>4} | {event_type:<16} | {payload or '-'}")

        input("\n↩︎ Enter jatkaaksesi...")

    # ---------- Kauppapaikka ----------

    def shop_menu(self) -> None:
        """Päävalikko kaupalle, josta voi valita uuden tai käytetyn koneen oston."""
        _icon_title("Kauppapaikka")
        print("1) 🏭 Osta uusi kone tehtaalta")
        print("2) 💸 Selaa käytettyjen markkinoita")
        print("0) 🚪 Poistu")

        choice = input("Valinta: ").strip()

        if choice == "1":
            self.buy_new_aircraft_menu()  # Entinen shop_menu, uudelleennimetty
        elif choice == "2":
            self.market_menu()  # Uusi valikko käytetyille koneille
        elif choice == "0":
            return
        else:
            print("⚠️  Virheellinen valinta.")

    #---------- Tehtaalta tulevat lentokoneet --------------

    def buy_new_aircraft_menu(self) -> None:
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

    #---------- Lentori kauppapaikka  --------------

    def market_menu(self) -> None:
        """Käytettyjen koneiden markkinapaikan käyttöliittymä parannetulla formatoinnilla."""
        self._refresh_market_aircraft()

        _icon_title("Käytettyjen markkinat")

        with get_connection() as yhteys:
            kursori = yhteys.cursor(dictionary=True)
            kursori.execute("""
                            SELECT m.*, am.model_name, am.manufacturer
                            FROM market_aircraft m
                                     JOIN aircraft_models am ON m.model_code = am.model_code
                            ORDER BY m.purchase_price ASC
                            """)
            market_planes = kursori.fetchall() or []

        if not market_planes:
            print("ℹ️  Markkinoilla ei ole juuri nyt yhtään konetta. Yritä myöhemmin uudelleen.");
            input("\n↩︎ Enter jatkaaksesi...");
            return

        # Määritetään sarakkeiden leveydet
        ID_W, NAME_W, PRICE_W, COND_W, HOURS_W, AGE_W, NOTES_W = 3, 28, 13, 7, 8, 10, 40

        # Tulostetaan otsikkorivi
        print(
            f"{'ID':<{ID_W}} {'Kone (Malli)':<{NAME_W}} {'Hinta':>{PRICE_W}} {'Kunto':>{COND_W}} {'Tunnit':>{HOURS_W}} {'Ikä (pv)':>{AGE_W}} {'Huomiot':<{NOTES_W}}")
        print(
            f"{'-' * ID_W} {'-' * NAME_W} {'-' * PRICE_W} {'-' * COND_W} {'-' * HOURS_W} {'-' * AGE_W} {'-' * NOTES_W}")

        for plane in market_planes:
            # Katkaistaan pitkät nimet ja huomiot siististi
            name_str = f"{plane['manufacturer']} {plane['model_name']}"
            if len(name_str) > NAME_W - 1:
                name_str = name_str[:NAME_W - 4] + "..."

            notes = plane['market_notes'] or "-"
            if len(notes) > NOTES_W - 1:
                notes = notes[:NOTES_W - 4] + "..."

            # Formatoidaan rivin tulostus määriteltyjen leveyksien mukaan
            print(
                f"{str(plane['market_id']):<{ID_W}} "
                f"{name_str:<{NAME_W}} "
                f"{self._fmt_money(plane['purchase_price']):>{PRICE_W}} "
                f"{str(plane['condition_percent']) + '%':>{COND_W}} "
                f"{str(plane['hours_flown']) + 'h':>{HOURS_W}} "
                f"{str(self.current_day - plane['manufactured_day']):>{AGE_W}} "
                f"{notes:<{NOTES_W}}"
            )

        choice = input("\nSyötä ostettavan koneen ID (tyhjä = peruuta): ").strip()
        if not choice: return
        try:
            sel_id = int(choice)
            selected_plane = next((p for p in market_planes if p['market_id'] == sel_id), None)
            if not selected_plane:
                print("⚠️  Virheellinen ID.");
                return
        except ValueError:
            print("⚠️  Virheellinen ID.");
            return

        price = Decimal(selected_plane['purchase_price'])
        if self.cash < price:
            print(f"❌ Kassa ei riitä. Tarvitset {self._fmt_money(price)}, sinulla on {self._fmt_money(self.cash)}.");
            input("\n↩︎ Enter jatkaaksesi...");
            return

        print(f"\nOlet ostamassa: {selected_plane['manufacturer']} {selected_plane['model_name']}")
        print(
            f"Hinta: {self._fmt_money(price)}, Kunto: {selected_plane['condition_percent']}%, Tunnit: {selected_plane['hours_flown']}h")
        if selected_plane['market_notes']: print(f"Myyjän huomiot: {selected_plane['market_notes']}")

        confirm = input("Vahvista osto (k/e): ").strip().lower()
        if confirm != 'k':
            print("❎ Peruutettu.");
            return

        # Suoritetaan osto transaktiona
        success = self._purchase_market_aircraft_tx(selected_plane)
        if success:
            print("✅ Kaupat tehty! Kone lisätty laivastoosi.")
        else:
            print("❌ Osto epäonnistui.")
        input("\n↩︎ Enter jatkaaksesi...")

    def _refresh_market_aircraft(self):
        """
        Päivittää markkinoiden tarjonnan. Poistaa vanhat ja lisää uusia koneita.
        Ajetaan joka kerta, kun pelaaja avaa markkinat.
        """
        with get_connection() as yhteys:
            kursori = yhteys.cursor(dictionary=True)
            # 1. Poista vanhat ilmoitukset (yli 10 päivää vanhat)
            kursori.execute("DELETE FROM market_aircraft WHERE listed_day < %s", (self.current_day - 10,))

            # 2. Tarkista, montako ilmoitusta on jäljellä
            kursori.execute("SELECT COUNT(*) as cnt FROM market_aircraft")
            current_listings = kursori.fetchone()['cnt']

            # 3. Lisää uusia koneita, kunnes markkinoilla on 5-10 konetta
            num_to_add = random.randint(5, 10) - current_listings
            if num_to_add <= 0:
                return

            # Haetaan kaikki mahdolliset konemallit, joita voidaan lisätä
            kursori.execute("SELECT model_code, purchase_price FROM aircraft_models WHERE category != 'STARTER'")
            all_models = kursori.fetchall() or []
            if not all_models: return

            for _ in range(num_to_add):
                model = random.choice(all_models)

                # Arvotaan koneelle ominaisuudet
                age = random.randint(10, 500)
                hours = age * random.randint(1, 5)
                condition = random.randint(20, 95)

                # Hinta perustuu uuteen hintaan, mutta sitä muokataan iän, tuntien ja kunnon mukaan
                price_modifier = (Decimal(condition) / 100) - (Decimal(hours) / 20000) - (Decimal(age) / 5000)
                price_modifier = max(Decimal('0.1'), min(price_modifier, Decimal('0.9')))  # 10-90% uudesta hinnasta
                price = (Decimal(model['purchase_price']) * price_modifier).quantize(Decimal("0.01"))

                # Satunnainen huomio
                notes_options = [
                    None,
                    "Edellinen omistaja oli todella varovainen.",
                    "Rungossa on muutamia pieniä naarmuja.",
                    "Moottori saattaa kaivata huoltoa pian.",
                    "Tällä on lennetty vain lyhyitä matkoja.",
                    "Sisusta on kuin uusi.",
                    None, None
                ]
                notes = random.choice(notes_options)

                kursori.execute(
                    "INSERT INTO market_aircraft (model_code, purchase_price, condition_percent, hours_flown, manufactured_day, market_notes, listed_day) VALUES (%s, %s, %s, %s, %s, %s, %s)",
                    (model['model_code'], price, condition, hours, self.current_day - age, notes, self.current_day)
                )

    def _purchase_market_aircraft_tx(self, plane_data: dict) -> bool:
        """Suorittaa käytetyn koneen oston atomisena transaktiona."""
        with get_connection() as yhteys:
            kursori = yhteys.cursor()
            try:
                # 1. Varmista kassa ja lukitse pelaajan tallennus
                kursori.execute("SELECT cash FROM game_saves WHERE save_id = %s FOR UPDATE", (self.save_id,))
                cash_now = Decimal(kursori.fetchone()[0])
                price = Decimal(plane_data['purchase_price'])
                if cash_now < price:
                    return False

                # 2. Poista ilmoitus markkinoilta
                kursori.execute("DELETE FROM market_aircraft WHERE market_id = %s", (plane_data['market_id'],))
                if kursori.rowcount == 0:
                    print("⚠️  Joku ehti ostaa koneen ennen sinua!");
                    return False

                # 3. Lisää kone pelaajan laivastoon
                registration = self._generate_registration()
                kursori.execute(
                    """
                    INSERT INTO aircraft (model_code, current_airport_ident, registration, acquired_day, purchase_price,
                                          condition_percent, hours_flown, status, save_id)
                    VALUES (%s, %s, %s, %s, %s, %s, %s, 'IDLE', %s)
                    """,
                    (
                        plane_data['model_code'],
                        self._get_primary_base_ident() or 'EFHK',  # Sijoitetaan oletuksena pääkonttorille
                        registration,
                        self.current_day,
                        price,
                        plane_data['condition_percent'],
                        plane_data['hours_flown'],
                        self.save_id
                    )
                )

                # 4. Päivitä pelaajan kassa
                new_cash = (cash_now - price).quantize(Decimal("0.01"))
                kursori.execute("UPDATE game_saves SET cash = %s, updated_at = %s WHERE save_id = %s",
                                (new_cash, datetime.utcnow(), self.save_id))

                yhteys.commit()
                self.cash = new_cash
                return True
            except Exception as e:
                yhteys.rollback()
                print(f"❌ Virhe ostotapahtumassa: {e}");
                return False

    # ---------- Päivitykset: ECO ----------

    def upgrade_aircraft_menu(self) -> None:
        """
        Interaktiivinen valikko ECO-päivityksille, joka näyttää oikeat ennusteet.
        """
        aircrafts = fetch_player_aircrafts_with_model_info(self.save_id)
        if not aircrafts:
            print("ℹ️  Sinulla ei ole vielä koneita.");
            input("\n↩︎ Enter jatkaaksesi...");
            return

        _icon_title("ECO-päivitykset")
        menu_rows = []
        for idx, row in enumerate(aircrafts, start=1):
            aircraft_id = row["aircraft_id"]
            state = get_current_aircraft_upgrade_state(aircraft_id)
            cur_level = int(state["level"])
            next_level = cur_level + 1

            # Lasketaan nykyinen ja tuleva kerroin KORJATULLA logiikalla
            base_eco = float(row.get("eco_fee_multiplier") or 1.0)
            current_eco = compute_effective_eco_multiplier(aircraft_id, base_eco)

            # Ennustetaan tuleva kerroin simuloimalla yhtä lisätasoa
            factor_per_level = Decimal("1.05")
            next_level_multiplier = Decimal(str(base_eco)) * (factor_per_level ** next_level)
            new_eco = float(max(Decimal("0.50"), min(next_level_multiplier, Decimal("5.00"))))

            cost = calc_aircraft_upgrade_cost(row, next_level)

            print(
                f"{idx:>2}) ♻️ {row['model_name']} ({row['registration']}) | Taso: {cur_level} → {next_level} | Eco: {current_eco:.2f} → {new_eco:.2f} | 💶 {self._fmt_money(cost)}")
            menu_rows.append((row, cur_level, next_level, cost))

        choice = input("Valinta numerolla (tyhjä = peruuta): ").strip()
        if not choice: return
        try:
            sel = int(choice)
            if not (1 <= sel <= len(menu_rows)):
                print("⚠️  Virheellinen valinta.");
                return
        except ValueError:
            print("⚠️  Virheellinen valinta.");
            return

        row, cur_level, next_level, cost = menu_rows[sel - 1]
        aircraft_id = row["aircraft_id"]

        if self.cash < cost:
            print(f"❌ Kassa ei riitä. Tarvitset {self._fmt_money(cost)}, sinulla on {self._fmt_money(self.cash)}.");
            input("\n↩︎ Enter jatkaaksesi...");
            return

        # Vahvistusdialogi näyttää myös oikeat, päivitetyt arvot
        print(f"\nPäivitetään {row['model_name']} ({row['registration']}) tasolle {next_level}")
        print(f"💶 Hinta: {self._fmt_money(cost)}")
        confirm = input("Vahvista (k/e): ").strip().lower()
        if confirm != "k":
            print("❎ Peruutettu.");
            return

        try:
            # Kutsutaan yksinkertaistettua funktiota ilman turhia parametreja
            apply_aircraft_upgrade(aircraft_id=aircraft_id, installed_day=self.current_day)
            self._add_cash(-cost, context="AIRCRAFT_ECO_UPGRADE")
            self._log_event(
                "AIRCRAFT_UPGRADE",
                f"aircraft_id={aircraft_id}; cost={cost}; new_level={next_level}",
                event_day=self.current_day,
            )
            print("✅ Päivitys tehty.")
        except Exception as e:
            print(f"❌ Päivitys epäonnistui: {e}")
        input("\n↩︎ Enter jatkaaksesi...")


    # ---------- Lentokoneiden korjaus ----------

    def _fetch_broken_planes(self) -> List[dict]:
        """
        Hae kaikki koneet joiden kunto on alle 100%.

        Palauttaa:
            List[dict] jossa jokaisessa:
            - aircraft_id: koneen ID
            - registration: rekisteritunnus
            - status: koneen tila (IDLE/BUSY)
            - condition_percent: kunnon prosentti (0-100)
            - model_name: mallin nimi näyttöä varten
            - model_code: mallin koodi

        Käytetään huoltovalikossa listaamaan korjattavat koneet.
        """
        sql = """
              SELECT a.aircraft_id, \
                     a.registration, \
                     a.status, \
                     a.condition_percent, \
                     am.model_name, \
                     am.model_code
              FROM aircraft a
                       JOIN aircraft_models am ON am.model_code = a.model_code
              WHERE a.save_id = %s
                AND (a.sold_day IS NULL OR a.sold_day = 0)
                AND a.condition_percent IS NOT NULL
                AND a.condition_percent < 100
              ORDER BY a.aircraft_id \
              """

        with get_connection() as yhteys:
            kursori = yhteys.cursor(dictionary=True)
            kursori.execute(sql, (self.save_id,))
            return kursori.fetchall() or []

    # Yhden koneen korjaus täyteen kuntoon
    # Prosessi
    # Ensin haetaan kone, (lukitus/FOR UPDATE)
    # Lasketaan puuttuva kunto (100 - condition_percent)
    # Lasketaan korjaukselle hinta (REPAIR_COST_PER_PERCENT configin mukaan)
    # Lukitaan kassa (SELECT / FOR UPDATE), tarkistetaan riittävyys
    # Päivitetään koneeseen condition_percent = 100, status = "IDLE"
    # Hinta kassasta yhdellä UPDATE:lla näin pidetään self.cash synkassa
    #
    # Palauttaa
    # True, jos korjaus onnistui
    # False, jos kassa ei riittänyt tai kone on "BUSY"

    def _repair_aircraft_to_full_tx(self, aircraft_id: int) -> bool:
        yhteys = get_connection()
        try:
            kursori = yhteys.cursor(dictionary=True)
            yhteys.start_transaction()

            # Lukitaan kone
            kursori.execute(
                "SELECT condition_percent, status FROM aircraft WHERE aircraft_id = %s FOR UPDATE", (aircraft_id,),
            )

            result = kursori.fetchone()
            if not result:
                yhteys.rollback()
                print("❌ Konetta ei löytynyt.")
                return False

            cond = int(result.get("condition_percent") or 0)
            status_now = (result.get("status") or "IDLE").upper()

            # Ei voida huoltaa jos kone on lennolla
            if status_now == "BUSY":
                yhteys.rollback()
                print("❌ Kone on lennolla, sitä ei voi korjata nyt.")
                return False

            # Ei tarvitse huoltaa
            if cond >= 100:
                yhteys.rollback()
                print("✔️ Kone on jo täydessä kunnossa.")
                return True

            # Lasketaan puuttuva kunto
            missing = 100 - cond
            repair_cost = (Decimal(missing) * REPAIR_COST_PER_PERCENT).quantize(Decimal("0.01"))


            # Lukitaan kassa ja tarkistetaan rahojen riittävyys
            kursori.execute("SELECT cash FROM game_saves WHERE save_id = %s FOR UPDATE", (self.save_id,))
            cash_result = kursori.fetchone()
            cash_now = _to_dec(cash_result["cash"] if cash_result and "cash" in cash_result else 0)

            if cash_now < repair_cost:
                yhteys.rollback()
                print("❌ Kassa ei riitä.")
                return False

            kursori.execute(
                "UPDATE aircraft SET condition_percent = 100, status = 'IDLE' WHERE aircraft_id = %s", (aircraft_id,),
            )

            # Lasketaan uusi kassa
            new_cash = (cash_now - repair_cost).quantize(Decimal("0.01"),rounding=ROUND_HALF_UP)
            kursori.execute(
                "UPDATE game_saves SET cash = %s, updated_at = %s WHERE save_id = %s",
                (new_cash, datetime.utcnow(), self.save_id),
            )

            self._log_event(
                "AIRCRAFT_REPAIR",
                f"aircraft_id={aircraft_id}; cost={repair_cost}",
                event_day=self.current_day,
                cursor=kursori,
            )

            yhteys.commit()

            self.cash = new_cash
            print(f"Kone {aircraft_id} on korjattu täyteen kuntoon. Se maksoi {self._fmt_money(repair_cost)}.")
            return True
        except Exception as err:
            yhteys.rollback()
            print(f"❌ Korjaus epäonnistui: {err}")
            return False
        finally:
            try:
                kursori.close()
            except Exception:
                pass
            try:
                yhteys.close()
            except Exception:
                pass

    def _repair_many_to_full_tx(self, aircraft_ids: List[int]) -> bool:
        """
        Korjaa useita koneita kerralla täyteen kuntoon.

        Prosessi:
        1. Lukitaan kaikki annetut koneet yhdellä kyselyllä (SELECT ... IN(...) FOR UPDATE)
        2. Lasketaan yhteenlaskettu kustannus vain niille koneille jotka:
           - Ovat alle 100% kunnossa
           - Eivät ole lennolla (BUSY)
        3. Lukitaan kassa ja tarkistetaan riittävyys
        4. Päivitetään kaikki korjattavat koneet kerralla
        5. Veloitetaan kokonaiskustannus kertaotteella
        6. Tulostetaan yhteenveto

        Args:
            aircraft_ids: Lista koneiden ID:itä jotka halutaan korjata

        Returns:
            True jos korjaus onnistui (tai ei ollut mitään korjattavaa)
            False jos kassa ei riitä

        Huom:
        - Jos yhtään korjattavaa ei löydy, palauttaa True (ei virhe)
        - Lennolla olevat koneet ohitetaan automaattisesti
        - Käyttää transaktiota (atominen operaatio)
        """
        if not aircraft_ids:
            print("ℹ️ Ei valittuja koneita.")
            return True

        yhteys = get_connection()
        try:
            kursori = yhteys.cursor(dictionary=True)
            yhteys.start_transaction()

            # 1. Lukitaan kaikki annetut koneet ja haetaan niiden tiedot
            placeholders = ",".join(["%s"] * len(aircraft_ids))
            kursori.execute(
                f"""
                    SELECT aircraft_id, condition_percent, status 
                    FROM aircraft 
                    WHERE aircraft_id IN ({placeholders})
                    FOR UPDATE
                    """,
                tuple(aircraft_ids),
            )
            rows = kursori.fetchall() or []

            # 2. Lasketaan korjaustarve ja kokonaiskustannus
            total_cost = Decimal("0.00")
            repair_ids: List[int] = []

            for r in rows:
                aid = int(r["aircraft_id"])
                cond = int(r.get("condition_percent") or 0)  # KORJATTU: oli .get["..."]
                status_now = (r.get("status") or "IDLE").upper()

                # Hypätään yli jos kone on lennolla (ei voi korjata)
                if status_now == "BUSY":
                    continue

                # Hypätään yli jos kone on jo täydessä kunnossa
                if cond >= 100:
                    continue

                # Lasketaan tämän koneen korjauskustannus
                need = 100 - cond
                total_cost += (Decimal(need) * REPAIR_COST_PER_PERCENT)
                repair_ids.append(aid)

            # Pyöristetään kokonaiskustannus
            total_cost = total_cost.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)

            # 3. Jos ei ole mitään korjattavaa, lopetetaan tähän
            if not repair_ids:
                yhteys.rollback()
                print("ℹ️ Ei korjattavaa (koneet jo kunnossa tai lennolla).")
                return True

            # 4. Lukitaan kassa ja tarkistetaan riittävyys
            kursori.execute(
                "SELECT cash FROM game_saves WHERE save_id = %s FOR UPDATE",
                (self.save_id,)
            )
            cr = kursori.fetchone()
            cash_now = _to_dec(cr["cash"] if cr and "cash" in cr else 0)

            if cash_now < total_cost:
                yhteys.rollback()
                print(
                    f"❌ Kassa ei riitä kaikkien korjaamiseen. Tarvitaan {self._fmt_money(total_cost)}, kassassa {self._fmt_money(cash_now)}.")
                return False

            # 5. Päivitetään kaikki korjattavat koneet kerralla
            placeholders2 = ",".join(["%s"] * len(repair_ids))
            kursori.execute(
                f"UPDATE aircraft SET condition_percent = 100, status = 'IDLE' WHERE aircraft_id IN ({placeholders2})",
                # KORJATTU: oli "conditon_percent" (kirjoitusvirhe)
                tuple(repair_ids),
            )

            # 6. Veloitetaan kokonaiskustannus kassasta
            new_cash = (cash_now - total_cost).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
            kursori.execute(
                "UPDATE game_saves SET cash = %s, updated_at = %s WHERE save_id = %s",
                (new_cash, datetime.utcnow(), self.save_id),
            )

            self._log_event(
                "AIRCRAFT_REPAIR_BULK",
                f"aircraft_ids={','.join(map(str, repair_ids))}; cost={total_cost}",
                event_day=self.current_day,
                cursor=kursori,
            )

            # 7. Commitoidaan kaikki muutokset
            yhteys.commit()

            # 8. Päivitetään session kassa-arvo ja tulostetaan yhteenveto
            self.cash = new_cash
            print(f"✅ Korjattu {len(repair_ids)} konetta. Kokonaishinta: {self._fmt_money(total_cost)}.")
            return True

        except Exception as e:
            yhteys.rollback()
            print(f"❌ Massakorjaus epäonnistui: {e}")
            return False

        finally:
            try:
                kursori.close()
            except Exception:
                pass
            try:
                yhteys.close()
            except Exception:
                pass

    def maintenance_menu(self) -> None:
        """
        Interaktiivinen huoltovalikko koneiden korjaamiseen.

        Prosessi:
        1. Haetaan kaikki rikkinäiset koneet (_fetch_broken_planes)
        2. Näytetään lista koneista ja niiden korjauskustannuksista
        3. Käyttäjä voi valita:
           - Yksittäisen koneen korjauksen (numero 1-N)
           - Kaikkien koneiden korjauksen kerralla (0)
           - Peruutuksen (tyhjä syöte)
        4. Kutsutaan joko _repair_aircraft_to_full_tx tai _repair_many_to_full_tx

        Huom: Näyttää myös arvion korjauskustannuksesta jokaiselle koneelle
        """
        # 1. Haetaan rikkinäiset koneet
        broken = self._fetch_broken_planes()

        if not broken:
            print("ℹ️ Yhtään rikki olevaa konetta ei löytynyt.")
            input("\n↩️ Enter jatkaaksesi...")
            return

        # 2. Näytetään huoltovalikko
        _icon_title("Huoltovalikko")

        for i, r in enumerate(broken, start=1):
            # Lasketaan kunnon puute ja korjauskustannusarvio
            cond = int(r.get("condition_percent") or 0)
            miss = max(0, 100 - cond)
            est = (Decimal(miss) * REPAIR_COST_PER_PERCENT).quantize(Decimal("0.01"))

            # Haetaan näyttöön tarvittavat tiedot
            name = r.get("model_name") or r.get("model_code") or "Unknown"
            reg = r.get("registration") or "???"  # KORJATTU: oli "registeration" (kirjoitusvirhe)
            st = r.get("status") or "IDLE"

            # Tulostetaan rivi
            print(
                f"{i:>2}) ✈️ {name} ({reg}) | "
                f"Kunto: {cond}% | Status: {st} | "
                f"Arvio: {self._fmt_money(est)}"  # KORJATTU: oli self.fmt_money (ilman alaviivaa)
            )

        # 3. Lisätään "korjaa kaikki" -vaihtoehto
        print("\n0) 🔧 Korjaa kaikki listalla")

        # 4. Kysytään käyttäjän valinta
        sel = input("\nValitse numero (tyhjä = peruuta): ").strip()

        if not sel:
            return

        # 5. Käsitellään valinta
        if sel == "0":
            # Korjataan kaikki
            ids = [int(r["aircraft_id"]) for r in broken]  # KORJATTU: oli "aircaft_id" (kirjoitusvirhe)
            self._repair_many_to_full_tx(ids)
            input("\n↩️ Enter jatkaaksesi...")
            return

        # 6. Korjataan yksittäinen kone
        try:
            idx = int(sel)  # KORJATTU: oli int(self) - täysin väärä!
            if not (1 <= idx <= len(broken)):
                print("⚠️  Virheellinen valinta.")
                input("\n↩️ Enter jatkaaksesi...")  # LISÄTTY: puuttui
                return
        except ValueError:
            print("⚠️  Virheellinen valinta.")
            input("\n↩️ Enter jatkaaksesi...")  # LISÄTTY: puuttui
            return

        # 7. Suoritetaan yksittäisen koneen korjaus
        r = broken[idx - 1]
        ok = self._repair_aircraft_to_full_tx(int(r["aircraft_id"]))

        if ok:
            print("✅ Korjaus valmis.")

        input("\n↩️ Enter jatkaaksesi...")





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
            self._add_cash(-_to_dec(cost), context="BASE_UPGRADE")
            self._log_event(
                "BASE_UPGRADE",
                f"base_id={b['base_id']}; from={current}; to={nxt}; cost={cost}",
                event_day=self.current_day,
            )
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

        HUOM: Determinismiä varten käytetään Pythonin random-moduulia,
        ei MySQL:n RAND()-funktiota. Haemme KAIKKI sopivat kentät ja
        valitsemme niistä satunnaisesti Pythonilla.
        """
        yhteys = get_connection()
        try:
            try:
                kursori = yhteys.cursor(dictionary=True)
            except TypeError:
                kursori = yhteys.cursor()

            # Haetaan KAIKKI sopivat kentät ilman satunnaisuutta
            # (Poistetaan ORDER BY RAND() jotta determinismi toimii)
            # Haetaan KAIKKI sopivat kentät joilla on koordinaatit
            kursori.execute(
                """
                SELECT ident, name
                FROM airport
                WHERE ident <> %s
                  AND type IN ('small_airport', 'medium_airport', 'large_airport')
                  AND latitude_deg IS NOT NULL
                  AND longitude_deg IS NOT NULL
                """,
                (exclude_ident,),
            )

            rows = kursori.fetchall() or []

            # Jos kenttiä on vähemmän kuin pyydetty, palautetaan kaikki
            if len(rows) <= n:
                kohteet = []
                for r in rows:
                    if isinstance(r, dict):
                        kohteet.append({"ident": r["ident"], "name": r.get("name")})
                    else:
                        kohteet.append({"ident": r[0], "name": r[1] if len(r) > 1 else None})
                return kohteet

            # Valitaan satunnaisesti n kenttää Pythonin random-moduulilla
            # Tämä käyttää asetettua RNG-siementä!
            selected_rows = random.sample(rows, n)

            kohteet = []
            for r in selected_rows:
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

    def _random_task_offers_for_plane(self, plane, count: int = 5):
        """
        Generoi 'count' kpl tämän päivän rahtitarjouksia annetulle koneelle.
        - Etäisyyteen suhteutettu rahtimäärä (voi ylittää kapasiteetin → useita reissuja).
        - Kesto lasketaan matkan ja nopeuden perusteella; yli-kapasiteetti kasvattaa total_days.
        - Palkkio: (payload * PER_KG + distance * PER_KM) * effective_eco
          ja lattia varmistaa ettei palkkio mene negatiiviseksi/turhan pieneksi.
        - Sakko on osuus palkkiosta, mutta ei koskaan negatiivinen.
        Muokkaa: PER_KG, PER_KM, MIN_TASK_REWARD, ECO_MIN/ECO_MAX.
        """

        # Muokattavat palkkioparametrit
        PER_KG = Decimal("10.10")  # €/kg
        PER_KM = Decimal("6.90")  # €/km
        MIN_TASK_REWARD = Decimal("250.00")  # alin sallittu palkkio
        ECO_MIN = Decimal("0.10")  # eco-kerroin ei alle tämän
        ECO_MAX = Decimal("5.00")  # eikä yli tämän
        dep_ident = plane["current_airport_ident"]
        speed_kts = float(plane.get("cruise_speed_kts") or 200.0)
        speed_km_per_day = max(1.0, speed_kts * 1.852 * 24.0 * 2.0)
        capacity = int(plane.get("base_cargo_kg") or 0) or 1

        # Yritä käyttää tehokasta eco-kerrointa (malli + upgradet); fallback: plane.eco_fee_multiplier
        try:
            eff_eco_val = get_effective_eco_for_aircraft(
                plane["aircraft_id"])  # oletetaan funktion olevan käytettävissä
            eff_eco = Decimal(str(eff_eco_val))
        except Exception:
            eff_eco = Decimal(str(plane.get("eco_fee_multiplier") or 1.0))
        # Rajaa eco kohtuullisiin rajoihin
        eff_eco = max(ECO_MIN, min(ECO_MAX, eff_eco))

        # Haetaan hieman ylimääräisiä kohteita siltä varalta, että osa karsiutuu
        dests = self._pick_random_destinations(count * 2, dep_ident)
        offers = []

        for d in dests:
            if len(offers) >= count:
                break

            dest_ident = d["ident"]
            dep_xy = self._get_airport_coords(dep_ident)
            dst_xy = self._get_airport_coords(dest_ident)
            if not (dep_xy and dst_xy):
                # Jos koordinaatit puuttuvat, ohitetaan
                continue

            # Etäisyys (km)
            dist_km = self._haversine_km(dep_xy[0], dep_xy[1], dst_xy[0], dst_xy[1])

            # Rahti skaalataan etäisyyden mukaan; sallitaan yli-kapasiteetti (→ useita reissuja)
            if dist_km < 500:
                base_payload = random.randint(max(1, capacity // 2), max(1, capacity * 3))
            elif dist_km < 1500:
                base_payload = random.randint(capacity, capacity * 4)
            else:
                base_payload = random.randint(capacity * 2, capacity * 6)

            # Päivän tapahtuma ei enää vaikuta etukäteen lastiin; käytetään perusrahtia.
            payload = max(1, int(base_payload))

            # Peruskesto (päivinä) matkan mukaan; yli-kapasiteetti lisää reissujen määrää ja kokonaiskestoa
            base_days = max(1, math.ceil(dist_km / speed_km_per_day))
            trips = max(1, math.ceil(payload / capacity))
            total_days = base_days * trips

            # Palkkion laskenta (lattia varmistaa ettei negatiivinen)
            base_reward = (Decimal(payload) * PER_KG) + (Decimal(dist_km) * PER_KM)
            reward = (base_reward * eff_eco).quantize(Decimal("0.01"))
            if reward < MIN_TASK_REWARD:
                reward = MIN_TASK_REWARD

            # Sakko osuutena; ei koskaan negatiivinen
            penalty = (reward * Decimal("0.30")).quantize(Decimal("0.01"))
            if penalty < Decimal("0.00"):
                penalty = Decimal("0.00")

            # Deadline: kokonaiskesto + puskuri
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

    def show_active_tasks(self) -> None:
        """
        Listaa aktiiviset tehtävät.
        """
        yhteys = get_connection()
        try:
            try:
                kursori = yhteys.cursor(dictionary=True)
            except TypeError:
                kursori = yhteys.cursor()

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
                       f.schedule_delay_min,
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
                delay_min = rd["schedule_delay_min"] if rd else r[12]
                fl_status = rd["flight_status"] if rd else r[13]
                display_eta = None
                if arr_day is not None:
                    try:
                        arr_day_val = int(arr_day)
                        delay_minutes_val = int(delay_min) if delay_min is not None else 0
                        if delay_minutes_val != 0:
                            delta_days = delay_minutes_val / (24 * 60)
                            baseline_eta = arr_day_val - int(round(delta_days))
                            display_eta = baseline_eta
                        else:
                            display_eta = arr_day_val
                    except (ValueError, TypeError):
                        display_eta = arr_day
                left_days = (deadline - self.current_day) if deadline is not None else None
                late = left_days is not None and left_days < 0

                print(
                    f"📦 #{cid} -> {dest} | ✈️ {reg or '-'} | 🧱 {int(payload)} kg | 💶 {self._fmt_money(reward)} | "
                    f"DL: {deadline} ({'myöhässä' if late else f'{left_days} pv jäljellä'}) | "
                    f"🧭 Tila: {status}{f' / Lento: {fl_status}, ETA {display_eta if display_eta is not None else arr_day}' if arr_day is not None else ''}"
                )
            input("\n↩︎ Enter jatkaaksesi...")
        finally:
            try:
                kursori.close()
            except Exception:
                pass
            yhteys.close()

    def start_new_task(self) -> None:
        """
        Aloita uusi tehtävä: valitse IDLE-kone, generoi tarjoukset, vahvista, luo contract+flight.
        """
        yhteys = get_connection()
        try:
            try:
                kursori = yhteys.cursor(dictionary=True)
            except TypeError:
                kursori = yhteys.cursor()

            # Vapaat koneet
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
                  AND a.condition_percent >= 100
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
            for i, p in enumerate(planes, start=1):
                cap = int(p["base_cargo_kg"] if isinstance(p, dict) else 0)
                eco = float(p.get("eco_fee_multiplier", 1.0) if isinstance(p, dict) else 1.0)
                print(f"{i:>2}) ✈️ {p['registration']} {p['model_name']} @ {p['current_airport_ident']} | 📦 {cap} kg | ♻️ x{eco}")

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

            now_day = self.current_day
            base_total_days = int(offer["total_days"])
            baseline_arr_day = now_day + base_total_days
            flight_days = base_total_days
            duration_factor = 1.0
            departure_event: Optional[FlightEvent] = None
            if self.rng_seed is not None:
                event_candidate = get_event_for_day(self.rng_seed, now_day, "flight", play_sound=False)
                if event_candidate is not None:
                    departure_event = event_candidate
                    try:
                        raw_factor = float(event_candidate.days if event_candidate.days is not None else 1.0)
                    except (TypeError, ValueError):
                        raw_factor = 1.0
                    if raw_factor <= 0:
                        raw_factor = 1.0
                    duration_factor = raw_factor
                    if raw_factor < 1.0:
                        flight_days = max(1, math.floor(base_total_days * raw_factor))
                    elif raw_factor > 1.0:
                        flight_days = math.ceil(base_total_days * raw_factor)

            arr_day = now_day + flight_days
            delay_minutes = int((flight_days - base_total_days) * 24 * 60)

            print("\nTehtäväyhteenveto:")
            print(
                f"🛫 {plane['current_airport_ident']} → 🛬 {offer['dest_ident']} | "
                f"📦 {offer['payload_kg']} kg | 🔁 {offer['trips']} | "
                f"🕒 {base_total_days} pv | 💶 {self._fmt_money(offer['reward'])} | DL: päivä {offer['deadline']}"
            )
            ok = input("Aloitetaanko tehtävä? (k/e): ").strip().lower()
            if ok != "k":
                print("❎ Peruutettu.")
                return

            total_dist = float(offer["distance_km"]) * offer["trips"]

            try:
                yhteys.start_transaction()

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

                kursori.execute(
                    """
                    INSERT INTO flights (created_day, dep_day, arrival_day, status, distance_km, schedule_delay_min,
                                         emission_kg_co2, eco_fee, dep_ident, arr_ident, aircraft_id, save_id,
                                         contract_id)
                    VALUES (%s, %s, %s, %s, %s, %s,
                            %s, %s, %s, %s, %s, %s, %s)
                    """,
                    (
                        now_day, now_day, arr_day, "ENROUTE", total_dist, delay_minutes,
                        0.0, Decimal("0.00"), plane["current_airport_ident"], offer["dest_ident"],
                        plane["aircraft_id"], self.save_id, contract_id
                    ),
                )

                kursori.execute(
                    "UPDATE aircraft SET status = 'BUSY' WHERE aircraft_id = %s",
                    (plane["aircraft_id"],)
                )

                log_parts = [
                    f"contract_id={contract_id}",
                    f"dest={offer['dest_ident']}",
                    f"payload={offer['payload_kg']}",
                    f"eta_day={arr_day}",
                    f"duration_days={flight_days}",
                ]
                if delay_minutes != 0:
                    log_parts.append(f"delay_min={delay_minutes}")
                if departure_event is not None:
                    log_parts.append(f"event={departure_event.name}")
                    log_parts.append(f"duration_factor={duration_factor:.2f}")
                self._log_event(
                    "CONTRACT_STARTED",
                    "; ".join(log_parts),
                    event_day=now_day,
                    cursor=kursori,
                )

                yhteys.commit()
                print(f"✅ Tehtävä #{contract_id} aloitettu. ETA: {baseline_arr_day} (lähtöjä {offer['trips']}).")
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
        Tarkistaa myös, onko joutilaita koneita väärillä kentillä ja lähettää ne kotiin.
        """
        # --- LÄHETÄ KONEET KOTIIN (RTB) ---------------------------------
        # Ajetaan tämä vain joka 3. päivä suorituskyvyn säästämiseksi pikakelauksessa
        if self.current_day % 3 == 0:
            self._initiate_return_flights_for_idle_aircraft(silent=silent)

        new_day = self.current_day + 1
        arrivals_count = 0
        total_delta = Decimal("0.00") # Sopimuksista ansaittu raha
        db_timestamp = datetime.utcnow()
        arrival_details: List[str] = []

        yhteys = get_connection()
        try:
            # Käytetään dictionary=True, jotta sarakkeisiin voi viitata nimillä
            kursori = yhteys.cursor(dictionary=True)
            try:
                yhteys.start_transaction()

                # Päivitä pelin päivä tietokantaan
                kursori.execute(
                    "UPDATE game_saves SET current_day = %s, updated_at = %s WHERE save_id = %s",
                    (new_day, db_timestamp, self.save_id),
                )

                # Hae SAAPUVAT lennot (sekä sopimuslennot että paluulennot)
                kursori.execute(
                    """
                    SELECT f.flight_id, f.contract_id, f.aircraft_id,
                           f.arr_ident, f.arrival_day, f.dep_day, f.status AS flight_status,
                           c.deadline_day, c.reward, c.penalty, c.payload_kg
                    FROM flights f
                    -- LEFT JOIN, jotta paluulennot (ei sopimusta) tulevat mukaan
                    LEFT JOIN contracts c ON c.contractId = f.contract_id
                    WHERE f.save_id = %s
                    -- KÄSITTELE SEKÄ ENROUTE ETTÄ ENROUTE_RTB TILAT --
                    AND f.status IN ('ENROUTE', 'ENROUTE_RTB')
                    AND f.arrival_day <= %s
                    """,
                    (self.save_id, new_day),
                )
                arrivals = kursori.fetchall() or []
                arrivals_count = len(arrivals)
                daily_events: List[dict] = []

                for flight_data in arrivals:
                    flight_id = flight_data["flight_id"]
                    aircraft_id = flight_data["aircraft_id"]
                    arr_ident = flight_data["arr_ident"]
                    arr_day = int(flight_data["arrival_day"])
                    dep_day = int(flight_data["dep_day"])
                    current_flight_status = flight_data["flight_status"]

                    # --- Laske ja lisää lentotunnit ---
                    flight_duration_days = arr_day - dep_day
                    hours_to_add = max(0, flight_duration_days) * 24
                    if hours_to_add > 0:
                        kursori.execute(
                            "UPDATE aircraft SET hours_flown = hours_flown + %s WHERE aircraft_id = %s",
                            (hours_to_add, aircraft_id),
                        )

                    # --- Päivitä lennon tila ---
                    # Käytä erillistä tilaa saapuneille paluulennoille, jos tarpeen
                    new_flight_status = 'ARRIVED_RTB' if current_flight_status == 'ENROUTE_RTB' else 'ARRIVED'
                    kursori.execute("UPDATE flights SET status = %s WHERE flight_id = %s", (new_flight_status, flight_id,))

                    # --- Päivitä lentokoneen tila ja sijainti ---
                    # Koneesta tulee IDLE saapumiskentälle
                    kursori.execute(
                        "UPDATE aircraft SET status = 'IDLE', current_airport_ident = %s WHERE aircraft_id = %s",
                        (arr_ident, aircraft_id),
                    )

                    # --- Käsittele sopimus (Vain jos kyseessä sopimuslento, EI RTB) ---
                    contract_id = flight_data["contract_id"]
                    # Tarkista, ettei contract_id ole NULL ja että status oli 'ENROUTE'
                    if contract_id is not None and current_flight_status == 'ENROUTE':
                        deadline = int(flight_data["deadline_day"])
                        reward = _to_dec(flight_data["reward"])
                        penalty = _to_dec(flight_data["penalty"])
                        payload_val = flight_data.get("payload_kg") if isinstance(flight_data, dict) else None
                        payload_kg = int(payload_val) if payload_val is not None else 0

                        arrival_event: Optional[FlightEvent] = None
                        event_multiplier = Decimal("1.0")
                        event_damage = 0
                        base_contract_reward = reward
                        if self.rng_seed is not None:
                            arrival_event = get_event_for_day(self.rng_seed, arr_day, "flight")
                            if arrival_event is not None:
                                try:
                                    event_multiplier = Decimal(str(arrival_event.package_multiplier or 1.0))
                                except (ArithmeticError, ValueError):
                                    event_multiplier = Decimal("1.0")
                                if event_multiplier < Decimal("0.0"):
                                    event_multiplier = Decimal("0.0")
                                event_damage = max(0, int(arrival_event.plane_damage or 0))

                        # ✈️🛠️ Tapahtuma voi vahingoittaa koneen kuntoa saapuessa.
                        if event_damage > 0:
                            kursori.execute(
                                "UPDATE aircraft SET condition_percent = GREATEST(0, condition_percent - %s) "
                                "WHERE aircraft_id = %s",
                                (event_damage, aircraft_id),
                            )

                        # Määritä sopimuksen lopputulos ja palkkio ennen tapahtumaa
                        if new_day <= deadline:
                            base_reward = reward
                            new_contract_status = "COMPLETED"
                        else:
                            base_reward = max(Decimal("0.00"), reward - penalty)
                            new_contract_status = "COMPLETED_LATE"

                        final_reward = (base_reward * event_multiplier).quantize(
                            Decimal("0.01"), rounding=ROUND_HALF_UP
                        )
                        if final_reward < Decimal("0.00"):
                            final_reward = Decimal("0.00")

                        event_adjustment = (base_contract_reward - final_reward).quantize(
                            Decimal("0.01")
                        )

                        delivered_payload = Decimal(payload_kg)
                        lost_packages = 0
                        if arrival_event is not None:
                            if event_multiplier >= Decimal("1.0"):
                                delivered_payload = Decimal(payload_kg)
                            else:
                                delivered_payload = (Decimal(payload_kg) * event_multiplier).quantize(
                                    Decimal("1"), rounding=ROUND_HALF_UP
                                )
                                if delivered_payload < Decimal("0"):
                                    delivered_payload = Decimal("0")
                            lost_packages = max(0, int(Decimal(payload_kg) - delivered_payload))
                        delivered_count = int(delivered_payload)

                        kursori.execute(
                            "UPDATE contracts SET status = %s, completed_day = %s, event_id = %s, lost_packages = %s, "
                            "damaged_packages = %s, final_reward = %s, event_adjustment = %s WHERE contractId = %s",
                            (
                                new_contract_status,
                                new_day,
                                arrival_event.event_id if arrival_event is not None else None,
                                lost_packages,
                                event_damage,
                                final_reward,
                                event_adjustment,
                                contract_id,
                            ),
                        )

                        total_delta += final_reward

                        # Kerää raportointia varten lisätiedot myöhempää tulostusta varten
                        summary_bits = [
                            f"✈️ #{contract_id} palasi {arr_ident}",
                            f"palkkio {self._fmt_money(final_reward)}",
                            f"toimitus {delivered_count}/{payload_kg} kg",
                        ]
                        if arrival_event is not None:
                            summary_bits.append(f"tapahtuma: {arrival_event.name}")
                            if event_multiplier != Decimal("1.0"):
                                summary_bits.append(f"kerroin x{float(event_multiplier):.2f}")
                            if lost_packages > 0:
                                summary_bits.append(f"paketteja hukassa {lost_packages} kg")
                        if new_day > deadline:
                            summary_bits.append("myöhäinen toimitus")
                        if event_adjustment != Decimal("0.00"):
                            summary_bits.append(
                                f"tapahtumasta vähennettiin {self._fmt_money(event_adjustment)}"
                            )
                        arrival_details.append(" | ".join(summary_bits))

                        log_parts = [
                            f"contract_id={contract_id}",
                            f"arrival={arr_ident}",
                            f"reward={final_reward}",
                            f"reward_base={base_contract_reward}",
                            f"delivered={delivered_count}",
                            f"ordered={payload_kg}",
                        ]
                        if arrival_event is not None:
                            log_parts.append(f"event={arrival_event.name}")
                            if event_multiplier != Decimal("1.0"):
                                log_parts.append(f"multiplier={event_multiplier}")
                            if event_damage > 0:
                                log_parts.append(f"damage={event_damage}")
                            if event_adjustment != Decimal("0.00"):
                                log_parts.append(f"event_delta={event_adjustment}")
                        if lost_packages > 0:
                            log_parts.append(f"lost={lost_packages}")
                        if new_day > deadline:
                            log_parts.append("status=late")
                        self._log_event(
                            "CONTRACT_COMPLETED",
                            "; ".join(log_parts),
                            event_day=new_day,
                            cursor=kursori,
                        )

                        if arrival_event is not None:
                            daily_events.append(
                                {
                                    "name": arrival_event.name,
                                    "description": arrival_event.description,
                                    "multiplier": float(event_multiplier),
                                    "damage": event_damage,
                                    "reward_delta": event_adjustment,
                                    "lost_packages": lost_packages,
                                }
                            )

                # --- Päivitä kassa (jos sopimuksia valmistui) ---
                if total_delta != Decimal("0.00"):
                    # Lukitse pelaajan tallennus päivitystä varten
                    kursori.execute("SELECT cash FROM game_saves WHERE save_id = %s FOR UPDATE", (self.save_id,))
                    cur_cash = _to_dec(kursori.fetchone()["cash"])
                    new_cash = (cur_cash + total_delta).quantize(Decimal("0.01"))
                    # Päivitä kassa tietokantaan
                    kursori.execute("UPDATE game_saves SET cash = %s WHERE save_id = %s", (new_cash, self.save_id))
                    # Päivitä kassa myös sessio-olioon heti
                    self.cash = new_cash

                self._log_event(
                    "DAY_ADVANCE",
                    f"new_day={new_day}; arrivals={arrivals_count}; earned={total_delta}",
                    event_day=new_day,
                    cursor=kursori,
                )

                # Hyväksy kaikki muutokset tietokantaan
                yhteys.commit()
                # Päivitä päivä sessio-olioon vasta onnistuneen commitin jälkeen
                self.current_day = new_day

            except Exception as e:
                # Peru muutokset, jos jokin meni pieleen
                yhteys.rollback()
                if not silent:
                    print(f"❌ Seuraava päivä -käsittely epäonnistui: {e}")
                # Varmista, että päivä ei päivity, jos transaktio epäonnistuu
                self._refresh_save_state() # Lataa tila uudelleen tietokannasta
                return {
                    "day": self.current_day,
                    "arrivals": 0,
                    "earned": Decimal("0.00"),
                    "arrival_details": [],
                    "events": [],
                    "bills": [],
                }
            finally:
                # Sulje kursori ja yhteys siististi
                try:
                    kursori.close()
                except Exception:
                    pass
                try:
                    yhteys.close()
                except Exception:
                    pass

            # --- Käsittele kuukausilaskut ---
            # Tarkista, onko laskutuspäivä (joka 30. päivä) ja onko peli aktiivinen
            bill_records: List[dict] = []
            if self.current_day % 30 == 0 and self.status == "ACTIVE":
                bill_info = self._process_monthly_bills(silent=silent)
                if bill_info:
                    bill_records.append(bill_info)

            # --- Tulosta yhteenveto käyttäjälle (jos ei hiljainen tila) ---
            if not silent:
                if arrival_details:
                    for detail in arrival_details:
                        print(detail)
                # Näytä ansaittu raha vain, jos sitä tuli
                gained_str = f", ansaittu {self._fmt_money(total_delta)}" if total_delta > 0 else ""
                print(f"⏭️ Päivä siirtyi: {self.current_day}. Saapuneita lentoja: {arrivals_count}{gained_str}.")
                # Voit poistaa tämän input()-kutsun, jos haluat nopeamman etenemisen
                input("\n↩︎ Enter jatkaaksesi...")

            # --- Tarkista pelin päättymisehdot (tulostetaan main_menu-loopissa) ---
            if self.status == "BANKRUPT":
                # Konkurssiviesti tulostetaan main_menu:ssa
                pass
            elif self.current_day >= SURVIVAL_TARGET_DAYS and self.status == "ACTIVE":
                # Voittoviesti tulostetaan main_menu:ssa tai pikakelauksen yhteydessä
                # Status päivitetään VICTORYksi tarvittaessa siellä
                pass

            # Palauta yhteenveto saapumisista ja ansioista
            return {
                "day": self.current_day,
                "arrivals": arrivals_count,
                "earned": total_delta,
                "arrival_details": arrival_details,
                "events": daily_events,
                "bills": bill_records,
            }
        # Virheenkäsittely yhteyden tasolla
        except Exception as e:
            if not silent:
                print(f"❌ Seuraava päivä -käsittely epäonnistui: {e}")
            return {
                "day": self.current_day,
                "arrivals": 0,
                "earned": Decimal("0.00"),
                "arrival_details": [],
                "events": [],
                "bills": [],
            }

    # ------------ VEROTTAJA TULEE, KUU VAIHTUU --------------

    def _process_monthly_bills(self, silent: bool = False) -> None:
        """
        Veloittaa kuukausittaiset kulut.
        - HQ_MONTHLY_FEE
        - MAINT_PER_AIRCRAFT per aktiivinen kone
        - STARTER-koneille alennus (STARTER_MAINT_DISCOUNT)
        - 60. päivästä alkaen kulut kasvavat korkoa korolle BILL_GROWTH_RATE-kertoimella.
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
                pass  # [cite: 449]

        # Lasketaan ensin laskun perussumma ilman korkoja
        maint_starter = (MAINT_PER_AIRCRAFT * STARTER_MAINT_DISCOUNT) * starter_planes
        maint_nonstarter = MAINT_PER_AIRCRAFT * max(0, total_planes - starter_planes)
        base_bill = (HQ_MONTHLY_FEE + maint_starter + maint_nonstarter).quantize(Decimal("0.01"))  #

        # UUSI OSA: Laske "korkoa korolle" 60. päivästä alkaen
        total_bill = base_bill
        growth_multiplier = Decimal("1.00")
        if self.current_day >= 60:
            # Lasketaan, monesko korollinen laskutuskausi on menossa.
            # Päivä 60 = 1. kausi, Päivä 90 = 2. kausi jne.
            growth_periods = (self.current_day // 30) - 1

            # Sovelletaan korkoa korolle -kaavaa peruslaskuun
            # Kaava: Loppusumma = Perussumma * (1 + korko)^kaudet
            growth_multiplier = Decimal((1 + BILL_GROWTH_RATE) ** growth_periods)
            total_bill = (base_bill * growth_multiplier).quantize(Decimal("0.01"))

        if not silent:
            print("\n💸 Kuukausilaskut erääntyivät!")
            print(f"   🏢Lainat, Vuokrat ja Huollot (perussumma): {self._fmt_money(base_bill)}")
            if self.current_day >= 60:
                print(f"   📈 Inflaatiokorotus: +{((total_bill / base_bill - 1) * 100):.1f}%")
            print(f"   ➖ Yhteensä maksettavaa: {self._fmt_money(total_bill)}")

        # Maksu tai konkurssi
        if self.cash < total_bill:
            if not silent:
                print("💀 Rahat eivät riitä laskuihin. Yritys menee konkurssiin.")
            self._set_status("BANKRUPT")
            self._log_event(
                "BILLS_DEFAULT",
                f"day={self.current_day}; amount={total_bill}; reason=insufficient_funds",
                event_day=self.current_day,
            )
            return {
                "status": "BANKRUPT",
                "amount": total_bill,
                "base": base_bill,
                "growth_multiplier": float(growth_multiplier),
                "total_planes": total_planes,
            }

        try:
            self._add_cash(-total_bill, context="MONTHLY_BILL")
            self._log_event(
                "BILLS_PAID",
                f"day={self.current_day}; amount={total_bill}; total_planes={total_planes}",
                event_day=self.current_day,
            )
            if not silent:
                print("✅ Laskut maksettu.")
            return {
                "status": "PAID",
                "amount": total_bill,
                "base": base_bill,
                "growth_multiplier": float(growth_multiplier),
                "total_planes": total_planes,
            }
        except Exception as e:
            if not silent:
                print(f"❌ Laskujen veloitus epäonnistui: {e}")
            self._log_event(
                "BILLS_ERROR",
                f"day={self.current_day}; amount={total_bill}; error={e}",
                event_day=self.current_day,
            )
            return {
                "status": "ERROR",
                "amount": total_bill,
                "base": base_bill,
                "growth_multiplier": float(growth_multiplier),
                "total_planes": total_planes,
                "error": str(e),
            }

    # ---------- Eksyneet koneet kotikentille ------------

    def _initiate_return_flights_for_idle_aircraft(self, silent: bool = False):
        """
        Tarkistaa kaikki IDLE-tilassa olevat koneet. Jos kone on vieraalla kentällä,
        se luo sille automaattisen paluulennon lähimpään omistettuun tukikohtaan.
        """
        owned_bases = {b['base_ident']: b for b in fetch_owned_bases(self.save_id)}
        if not owned_bases:
            return  # Ei tukikohtia, ei voida palata kotiin

        sql = """
            SELECT a.aircraft_id, a.current_airport_ident, am.cruise_speed_kts, am.co2_kg_per_km
            FROM aircraft a JOIN aircraft_models am ON a.model_code = am.model_code
            WHERE a.save_id = %s AND a.status = 'IDLE' 
              AND a.current_airport_ident NOT IN ({})
        """.format(','.join(['%s'] * len(owned_bases)))

        params = [self.save_id] + list(owned_bases.keys())

        with get_connection() as yhteys:
            kursori = yhteys.cursor(dictionary=True)
            kursori.execute(sql, tuple(params))
            stranded_planes = kursori.fetchall() or []

            if not stranded_planes:
                return

            if not silent:
                print("ℹ️ Havaittu joutilaita koneita vierailla kentillä, aloitetaan paluulennot...")

            for plane in stranded_planes:
                current_coords = self._get_airport_coords(plane['current_airport_ident'])
                if not current_coords:
                    continue

                # Etsi lähin oma tukikohta
                closest_base_ident = None
                min_dist = float('inf')

                for base_ident in owned_bases:
                    base_coords = self._get_airport_coords(base_ident)
                    if base_coords:
                        dist = self._haversine_km(current_coords[0], current_coords[1], base_coords[0],
                                                  base_coords[1])
                        if dist < min_dist:
                            min_dist = dist
                            closest_base_ident = base_ident

                if closest_base_ident:
                    # Luo paluulento
                    speed_kts = float(plane.get("cruise_speed_kts") or 200.0)
                    speed_km_per_day = speed_kts * 1.852 * 24.0 * 2.0  # Tuplataan nopeus
                    duration_days = max(1, math.ceil(min_dist / speed_km_per_day))
                    arrival_day = self.current_day + duration_days
                    co2_per_km = Decimal(str(plane.get("co2_kg_per_km") or 0.2))
                    emissions = float((Decimal(min_dist) * co2_per_km).quantize(Decimal("0.01")))

                    try:
                        kursori.execute(
                            "INSERT INTO flights (created_day, dep_day, arrival_day, status, distance_km, emission_kg_co2, dep_ident, arr_ident, aircraft_id, save_id, contract_id) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, NULL)",
                            (self.current_day, self.current_day, arrival_day, "ENROUTE_RTB", min_dist, emissions,
                             plane['current_airport_ident'], closest_base_ident, plane['aircraft_id'], self.save_id)
                        )
                        kursori.execute(
                            "UPDATE aircraft SET status = 'BUSY_RTB' WHERE aircraft_id = %s",
                            (plane['aircraft_id'],)
                        )
                        self._log_event(
                            "FLIGHT_RTB_CREATED",
                            f"aircraft_id={plane['aircraft_id']}; from={plane['current_airport_ident']}; to={closest_base_ident}; eta_day={arrival_day}",
                            event_day=self.current_day,
                            cursor=kursori,
                        )
                        if not silent:
                            print(
                                f"  ✈️  Kone {plane['aircraft_id']} palaa kentältä {plane['current_airport_ident']} kotiin ({closest_base_ident}). ETA: päivä {arrival_day}.")
                    except Exception as e:
                        if not silent:
                            print(f"  ❌ Paluulennon luonti koneelle {plane['aircraft_id']} epäonnistui: {e}")

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

        day_summaries: List[dict] = []

        for _ in range(max_days):
            summary = self.advance_to_next_day(silent=True)
            days_advanced += 1
            earned_total += _to_dec(summary.get("earned", 0))
            day_summaries.append(summary)

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

        if day_summaries:
            print("\n📅 Päiväkohtaiset tapahtumat:")
            for item in day_summaries:
                day_idx = item.get("day", "?")
                arrivals = int(item.get("arrivals", 0))
                earned = self._fmt_money(_to_dec(item.get("earned", 0)))
                events = item.get("events", [])
                bills = item.get("bills", [])
                details = item.get("arrival_details", [])

                print(f"  Päivä {day_idx}: ✈️ saapumiset {arrivals}, 💶 ansiot {earned}")

                if details:
                    for detail in details:
                        print(f"    • {detail}")

                if events:
                    for ev in events:
                        if isinstance(ev, dict):
                            ev_name = ev.get("name", "Tapahtuma")
                            ev_desc = ev.get("description")
                            line = f"    • Tapahtuma: {ev_name}"
                            if ev_desc:
                                line += f" – {ev_desc}"
                            print(line)

                            meta_bits = []
                            mult_val = ev.get("multiplier")
                            if mult_val is not None:
                                try:
                                    mult_float = float(mult_val)
                                    if abs(mult_float - 1.0) > 1e-6:
                                        meta_bits.append(f"kerroin x{mult_float:.2f}")
                                except (TypeError, ValueError):
                                    pass
                            delta_val = ev.get("reward_delta")
                            if delta_val is not None:
                                delta_dec = _to_dec(delta_val)
                                if delta_dec != Decimal("0.00"):
                                    meta_bits.append(f"muutos {self._fmt_money(delta_dec)}")
                            damage_val = ev.get("damage")
                            if damage_val:
                                meta_bits.append(f"vahinko {damage_val}%")
                            lost_val = ev.get("lost_packages")
                            if lost_val:
                                meta_bits.append(f"hukattiin {lost_val} kg")
                            if meta_bits:
                                print(f"      ◦ {', '.join(meta_bits)}")
                        else:
                            print(f"    • Tapahtuma: {ev}")

                if bills:
                    for bill in bills:
                        amount = self._fmt_money(_to_dec(bill.get("amount", 0)))
                        base_amt = self._fmt_money(_to_dec(bill.get("base", bill.get("amount", 0))))
                        status = (bill.get("status") or "PAID").upper()
                        growth_multiplier = bill.get("growth_multiplier")
                        growth_note = ""
                        try:
                            growth_float = float(growth_multiplier) if growth_multiplier is not None else 1.0
                            if abs(growth_float - 1.0) > 1e-6:
                                growth_note = f" (kasvu x{growth_float:.2f})"
                        except (TypeError, ValueError):
                            pass

                        if status == "PAID":
                            info = f"Kuukausilasku maksettu {amount} (perus {base_amt}){growth_note}"
                        elif status == "BANKRUPT":
                            info = f"Kuukausilasku {amount} jäi maksamatta → konkurssi"
                        elif status == "ERROR":
                            err_msg = bill.get("error")
                            info = f"Kuukausilasku {amount} epäonnistui{growth_note}{f' ({err_msg})' if err_msg else ''}"
                        else:
                            info = f"Kuukausilasku {amount}{growth_note}"

                        print(f"    • {info}")

        input("\n↩︎ Enter jatkaaksesi...")

    # ---------- DB: apurit ----------

    def _log_event(
            self,
            event_type: str,
            message: str,
            event_day: Optional[int] = None,
            cursor=None,
    ) -> None:
        """Kirjaa tapahtuman save_event_log-tauluun ilman että peli pysähtyy."""

        day_value = int(event_day if event_day is not None else self.current_day)
        type_value = (event_type or "UNKNOWN")[:40]
        payload_value = message or ""
        timestamp = datetime.utcnow()

        try:
            if cursor is not None:
                cursor.execute(
                    """
                    INSERT INTO save_event_log (save_id, event_day, event_type, payload, created_at)
                    VALUES (%s, %s, %s, %s, %s)
                    """,
                    (self.save_id, day_value, type_value, payload_value, timestamp),
                )
                return

            with get_connection() as yhteys:
                try:
                    cur = yhteys.cursor()
                except TypeError:
                    cur = yhteys.cursor()

                try:
                    cur.execute(
                        """
                        INSERT INTO save_event_log (save_id, event_day, event_type, payload, created_at)
                        VALUES (%s, %s, %s, %s, %s)
                        """,
                        (self.save_id, day_value, type_value, payload_value, timestamp),
                    )
                    yhteys.commit()
                finally:
                    try:
                        cur.close()
                    except Exception:
                        pass
        except Exception as exc:  # pragma: no cover - logitus ei saa pysäyttää peliä
            logger.debug("Lokimerkinnän tallennus epäonnistui (%s): %s", type_value, exc)

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

    def _add_cash(self, delta: Decimal, context: Optional[str] = None) -> None:
        """Lisää tai vähennä kassaa ja kirjaa muutos lokiin."""
        new_val = (self.cash + _to_dec(delta)).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
        if new_val < Decimal("0"):
            raise ValueError("Kassa ei voi mennä negatiiviseksi.")
        self._set_cash(new_val)
        if context:
            self._log_event(
                "CASH_CHANGE",
                f"delta={delta}; new_cash={new_val}; context={context}",
                event_day=self.current_day,
            )

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
            self._log_event(
                "STATUS_UPDATE",
                f"status={new_status}",
                event_day=self.current_day,
            )
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

            self._log_event(
                "AIRCRAFT_PURCHASE",
                f"model={model_code}; registration={registration}; price={purchase_price}; base_id={base_id}",
                event_day=self.current_day,
                cursor=kursori,
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

    # -------------------------------------------------
    # SALAINEN KERHOHUONE (SIIS TOSI TOSI SALAINEN)
    # -------------------------------------------------
    def clubhouse_menu(self):
        """Salaisen Kerhohuoneen päävalikko."""
        while True:
            _icon_title("Kerhohuone 666")
            print(f"Tervetuloa Kerhohuoneelle, {self.player_name}!")
            print(f"Kassasi saldo: {self._fmt_money(self.cash)}")
            print("\nMitä haluat pelata?")
            print("1) 🪙 Kruuna vai Klaava")
            print("2) 🎲 Suurempi vai Pienempi")
            print("3) 🎰 Yksikätinen Rosvo")
            print("0) 🚪 Poistu takaisin toimistolle")

            choice = input("Valinta: ").strip()

            if choice == "1":
                self._clubhouse_coin_flip()
            elif choice == "2":
                self._clubhouse_high_low()
            elif choice == "3":
                self._clubhouse_slot_machine()
            elif choice == "0":
                print("Näkemiin ja tervetuloa uudelleen!")
                break
            else:
                print("⚠️ Tuntematon peli.")

            if self.cash <= 0:
                print("\n💀 Rahat loppuivat! Kerhohuoneen ovet sulkeutuvat osaltasi.")
                self._set_status("BANKRUPT")
                break
            input("\n↩︎ Paina Enter jatkaaksesi...")

    def _clubhouse_coin_flip(self):
        """Peli 1: Kruuna vai Klaava."""
        _icon_title("Kruuna vai Klaava")
        print(f"Saldo: {self._fmt_money(self.cash)}")
        try:
            panos = Decimal(input("Aseta panos (0 = peruuta): ").strip())
        except Exception:
            print("⚠️ Virheellinen panos.");
            return
        if panos <= 0: return
        if panos > self.cash: print("❌ Ei riittävästi rahaa!"); return

        valinta = input("Valitse kruuna (kr) vai klaava (kl): ").strip().lower()
        if valinta not in ["kr", "kl"]: print("⚠️ Valitse 'kr' tai 'kl'."); return

        voittoheitto = random.choices(["kr", "kl"], weights=[49, 51], k=1)[0]
        print("\nHeitetään kolikkoa...");
        time.sleep(1)

        if valinta == voittoheitto:
            print(f"🎉 Tulos oli '{voittoheitto}'! Voitit {self._fmt_money(panos)}!")
            self._add_cash(panos, context="CLUB_COIN_WIN")
        else:
            print(f"💸 Tulos oli '{voittoheitto}'. Hävisit {self._fmt_money(panos)}.")
            self._add_cash(-panos, context="CLUB_COIN_LOSS")

    def _clubhouse_high_low(self):
        """Peli 2: Suurempi vai Pienempi."""
        _icon_title("Suurempi vai Pienempi")
        print(f"Saldo: {self._fmt_money(self.cash)}")
        try:
            panos = Decimal(input("Aseta panos (0 = peruuta): ").strip())
        except Exception:
            print("⚠️ Virheellinen panos.");
            return
        if panos <= 0: return
        if panos > self.cash: print("❌ Ei riittävästi rahaa!"); return

        noppa1, noppa2 = random.randint(1, 6), random.randint(1, 6)
        print(f"\nEnsimmäinen noppa heitti: {noppa1}")
        valinta = input("Onko seuraava noppa suurempi (s) vai pienempi (p)? ").strip().lower()
        if valinta not in ["s", "p"]: print("⚠️ Valitse 's' tai 'p'."); return

        print(f"Toinen noppa heitti: {noppa2}");
        time.sleep(1)

        tulos_oikein = (valinta == "s" and noppa2 > noppa1) or \
                       (valinta == "p" and noppa2 < noppa1)

        if noppa1 == noppa2:
            print("💸 Tasapeli! Talo voittaa aina. Hävisit panoksesi.")
            self._add_cash(-panos, context="CLUB_HILO_PUSH")
        elif tulos_oikein:
            print(f"🎉 Oikein! Voitit {self._fmt_money(panos)}!")
            self._add_cash(panos, context="CLUB_HILO_WIN")
        else:
            print(f"💸 Väärin! Hävisit {self._fmt_money(panos)}.")
            self._add_cash(-panos, context="CLUB_HILO_LOSS")

    def _clubhouse_slot_machine(self):
        """Peli 3: Yksikätinen Rosvo."""
        _icon_title("Yksikätinen Rosvo")
        print(f"Saldo: {self._fmt_money(self.cash)}")
        try:
            panos = Decimal(input("Aseta panos (0 = peruuta): ").strip())
        except Exception:
            print("⚠️ Virheellinen panos.");
            return
        if panos <= 0: return
        if panos > self.cash: print("❌ Ei riittävästi rahaa!"); return

        self._add_cash(-panos, context="CLUB_SLOT_BET")
        print(f"Panos {self._fmt_money(panos)} asetettu. Onnea peliin!")

        symbols = ['🍒', '🍋', '🔔', '💎', '💰'];
        weights = [40, 30, 20, 9, 1]
        reels = random.choices(symbols, weights=weights, k=3)
        print("\nKiekot pyörivät...");
        time.sleep(1)
        print(f"| {reels[0]} | {reels[1]} | {reels[2]} |")

        voitto = Decimal("0")
        if reels[0] == '💰' and reels[1] == '💰' and reels[2] == '💰':
            print("✨ JÄTTIPOTTI! ✨");
            voitto = panos * 50
        elif reels[0] == '💎' and reels[1] == '💎' and reels[2] == '💎':
            print("💎 Timanttivoitto!");
            voitto = panos * 20
        elif reels[0] == '🔔' and reels[1] == '🔔' and reels[2] == '🔔':
            print("🔔 Kellot soivat!");
            voitto = panos * 10
        elif reels[0] == '🍋' and reels[1] == '🍋' and reels[2] == '🍋':
            print("🍋 Sitruunavoitto!");
            voitto = panos * 5
        elif reels[0] == '🍒' and reels[1] == '🍒' and reels[2] == '🍒':
            print("🍒 Kirsikkavoitto!");
            voitto = panos * 3
        elif reels[0] == '🍒' and reels[1] == '🍒':
            print("🍒 Pieni kirsikkavoitto!");
            voitto = panos * 2

        if voitto > 0:
            print(f"🎉 Voitit {self._fmt_money(voitto)}!")
            self._add_cash(voitto, context="CLUB_SLOT_WIN")
        else:
            print("💸 Ei voittoa tällä kertaa.")

    # -------------------------------------------------
    # SALAINEN KERHOHUONE (TOSI TOSI SALAINEN)
    # -------------------------------------------------


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

            self._log_event(
                "AIRCRAFT_GIFT",
                f"model={model_code}; registration={registration}; base_id={base_id}",
                event_day=self.current_day,
                cursor=kursori,
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

    # Good Game, tässä vähän tilastoja

    def show_end_game_stats(self):
        """Hakee ja tulostaa yhteenvedon pelin statistiikoista."""
        _icon_title("Pelin yhteenveto")
        print(f"Pelaaja: {self.player_name} | Lopputulos: {self.status}")

        sql_stats = """
                    SELECT (SELECT SUM(hours_flown) FROM aircraft WHERE save_id = gs.save_id)    AS total_hours, \
                           (SELECT SUM(emission_kg_co2) FROM flights WHERE save_id = gs.save_id) AS total_emissions, \
                           (SELECT COUNT(*) FROM aircraft WHERE save_id = gs.save_id)            AS total_aircraft
                    FROM game_saves gs
                    WHERE gs.save_id = %s; \
                    """
        with get_connection() as yhteys:
            kursori = yhteys.cursor(dictionary=True)
            kursori.execute(sql_stats, (self.save_id,))
            stats = kursori.fetchone()

        if stats:
            total_hours = int(stats.get("total_hours") or 0)
            total_emissions_kg = float(stats.get("total_emissions") or 0.0)
            total_aircraft = int(stats.get("total_aircraft") or 0)

            print("\n--- Tilastot ---")
            print(f"✈️  Koneita laivastossa: {total_aircraft} kpl")
            print(f"⏱️  Lentotunteja yhteensä: {total_hours} h")
            print(f"☁️  CO2-päästöjä yhteensä: {total_emissions_kg:,.0f} kg".replace(",", " "))

        print("\nKiitos kun pelasit!")