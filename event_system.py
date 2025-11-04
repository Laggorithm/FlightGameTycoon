"""Lentotapahtumien (random_events) hallinta ja integraatiopinta GameSessionille."""

from __future__ import annotations

import logging
import random
from dataclasses import dataclass
from typing import List, Optional, Sequence, Set, Tuple

from utils import get_connection
from play_sound import event_playsound


logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class FlightEvent:
    """Tietorakenne random_events-taulun yhdelle riville."""

    event_id: int
    name: str
    description: Optional[str]
    chance_max: int
    package_multiplier: float
    plane_damage: int
    days: float
    duration: int
    sound_file: Optional[str]

    @staticmethod
    def from_row(row: Sequence) -> "FlightEvent":
        """Muuttaa joko tuple- tai dict-tyyppisen rivin FlightEventiksi."""

        if isinstance(row, dict):
            return FlightEvent(
                event_id=int(row["event_id"]),
                name=row["event_name"],
                description=row.get("description"),
                chance_max=int(row["chance_max"]),
                package_multiplier=float(row["package_multiplier"]),
                plane_damage=int(row["plane_damage"]),
                days=float(row["days"]),
                duration=int(row["duration"] or 1),
                sound_file=row.get("sound_file"),
            )

        (
            event_id,
            event_name,
            description,
            chance_max,
            package_multiplier,
            plane_damage,
            days,
            duration,
            sound_file,
        ) = row
        return FlightEvent(
            event_id=int(event_id),
            name=str(event_name),
            description=str(description) if description is not None else None,
            chance_max=int(chance_max),
            package_multiplier=float(package_multiplier or 1.0),
            plane_damage=int(plane_damage or 0),
            days=float(days or 0),
            duration=int(duration or 1),
            sound_file=str(sound_file) if sound_file is not None else None,
        )


_current_flight_event: Optional[FlightEvent] = None
_current_duration_left: int = 0
# Muistetaan mille (seed, päivä) -yhdistelmille ääni on jo soitettu,
# jotta sama efekti ei toistu joka kyselyllä.
_played_event_sounds: Set[Tuple[int, int]] = set()


def _fetch_event_definitions(cursor) -> List[FlightEvent]:
    """Noutaa kaikki random_events-rivit muistiin."""

    try:
        cursor.execute(
            """
            SELECT event_id, event_name, description, chance_max,
                   package_multiplier, plane_damage, days, duration, sound_file
            FROM random_events
            """
        )
        rows = cursor.fetchall() or []
    except Exception as exc:  # pragma: no cover - yhteysvirheet riippuvat DB:stä
        logger.exception("random_events-taulun nouto epäonnistui")
        raise RuntimeError("Tapahtumien noutaminen tietokannasta epäonnistui") from exc
    return [FlightEvent.from_row(row) for row in rows]


def _randomize_flight_event(cursor) -> FlightEvent:
    """Valitsee tapahtuman chance_max-arvojen perusteella."""

    events = _fetch_event_definitions(cursor)
    if not events:
        logger.error("random_events-taulu on tyhjä, arvontaa ei voi suorittaa")
        raise RuntimeError("random_events-taulu on tyhjä – tapahtumia ei voida luoda")

    event_map = {evt.name: evt for evt in events}
    candidate_name = random.choice(list(event_map.keys()))
    candidate = event_map[candidate_name]
    roll = random.randint(1, max(1, candidate.chance_max))

    # Arvontamekaniikka: chance_max toimii ylärajana, ja osuma laukaisee erikoistapahtuman.
    if roll == candidate.chance_max:
        return candidate

    normal = event_map.get("Normal Day")
    # Jos oletustapahtumaa ei ole määritelty, palautetaan arvottu ehdokas sellaisenaan.
    if normal is None:
        return candidate
    return normal


def _event_for_next_day(cursor) -> FlightEvent:
    """Palauttaa seuraavan päivän tapahtuman ja päivittää kestolaskurin."""

    global _current_flight_event, _current_duration_left

    # Kun edellinen tapahtuma on päättynyt tai puuttuu, arvotaan uusi tapahtuma.
    if _current_flight_event is None or _current_duration_left <= 0:
        _current_flight_event = _randomize_flight_event(cursor)
        _current_duration_left = max(1, _current_flight_event.duration)

    # Kestolaskuri pienenee joka päivä; sama tapahtuma jatkuu, kunnes duration laskee nollaan.
    event = _current_flight_event
    _current_duration_left -= 1
    return event


def _load_event_by_name(cursor, event_name: str) -> Optional[FlightEvent]:
    """Hakee tapahtuman nimen perusteella random_events-taulusta."""

    try:
        cursor.execute(
            """
            SELECT event_id, event_name, description, chance_max,
                   package_multiplier, plane_damage, days, duration, sound_file
            FROM random_events
            WHERE event_name = %s
            LIMIT 1
            """,
            (event_name,),
        )
        row = cursor.fetchone()
    except Exception as exc:  # pragma: no cover - DB-virheet riippuvat konfiguraatiosta
        logger.exception("Tapahtuman haku epäonnistui nimellä %s", event_name)
        raise RuntimeError("Tapahtuman haku tietokannasta epäonnistui") from exc
    return FlightEvent.from_row(row) if row else None


def _load_event_by_id(cursor, event_id: int) -> Optional[FlightEvent]:
    """Hakee tapahtuman pääavaimen perusteella."""

    try:
        cursor.execute(
            """
            SELECT event_id, event_name, description, chance_max,
                   package_multiplier, plane_damage, days, duration, sound_file
            FROM random_events
            WHERE event_id = %s
            LIMIT 1
            """,
            (event_id,),
        )
        row = cursor.fetchone()
    except Exception as exc:  # pragma: no cover - DB-virheet riippuvat konfiguraatiosta
        logger.exception("Tapahtuman haku epäonnistui ID:llä %s", event_id)
        raise RuntimeError("Tapahtuman haku tietokannasta epäonnistui") from exc
    return FlightEvent.from_row(row) if row else None


def init_events_for_seed(seed: int, total_days: int) -> bool:
    """Generoi player_fate-tauluun siemenkohtaiset tapahtumat.

    Palauttaa True jos uusia rivejä lisättiin. -> Jos data on
    olemassa, funktio ei tee mitään ja palauttaa False.
    """

    if seed is None:
        raise ValueError("Seed ei voi olla None tapahtumien alustuksessa")

    global _current_flight_event, _current_duration_left
    _current_flight_event = None
    _current_duration_left = 0

    with get_connection() as conn:
        try:
            # mysql-connector saattaa yrittää palauttaa dict-kursoria; fallback tuplille.
            cursor = conn.cursor()
        except TypeError:
            cursor = conn.cursor()

        try:
            cursor.execute(
                "SELECT 1 FROM player_fate WHERE seed = %s LIMIT 1",
                (seed,),
            )
            if cursor.fetchone():
                return False

            entries = []
            for day in range(1, total_days + 1):
                # Arvotaan päivän tapahtuma ja puskuroidaan INSERT:ia varten.
                event = _event_for_next_day(cursor)
                entries.append((seed, day, event.name))

            cursor.executemany(
                "INSERT INTO player_fate (seed, day, event_name) VALUES (%s, %s, %s)",
                entries,
            )
            conn.commit()
            return True
        except Exception as exc:  # pragma: no cover - DB-virheet riippuvat konfiguraatiosta
            logger.exception(
                "Tapahtumien alustaminen epäonnistui seedille %s (päiviä %s)",
                seed,
                total_days,
            )
            try:
                conn.rollback()
            except Exception:  # pragma: no cover - rollback-virheitä harvoin testataan
                logger.warning("Rollback epäonnistui seedin %s alustuksessa", seed)
            raise RuntimeError("Tapahtumien alustaminen tietokantaan epäonnistui") from exc
        finally:
            try:
                cursor.close()
            except Exception:
                pass


def get_event_for_day(
        seed: int,
        day: int,
        event_type: str = "flight",
        play_sound: bool = True,
) -> Optional[FlightEvent]:
    """Hakee tietyn päivän tapahtuman. Nykyisin tuetaan vain "flight"-tyyppiä.

    play_sound-parametrilla voidaan estää ääniefektin toisto, jos kutsu tehdään
    pelkän simulaation vuoksi (esim. kestoarvion laskenta valikossa).
    """

    if seed is None or day <= 0 or event_type != "flight":
        return None

    with get_connection() as conn:
        try:
            # mysql-connector saattaa yrittää palauttaa dict-kursoria; fallback tuplille.
            cursor = conn.cursor()
        except TypeError:
            cursor = conn.cursor()

        try:
            cursor.execute(
                "SELECT event_name FROM player_fate WHERE seed = %s AND day = %s LIMIT 1",
                (seed, day),
            )
            row = cursor.fetchone()
            if not row:
                return None

            event_name = row[0] if not isinstance(row, dict) else row["event_name"]
            event = _load_event_by_name(cursor, event_name)

            # 🎧 Soitetaan ääniefekti kerran per siemen/päivä, jos sellainen on asetettu.
            sound_key = (seed, day)
            if (
                play_sound
                and event is not None
                and event.sound_file
                and sound_key not in _played_event_sounds
            ):
                try:
                    if event_playsound(event.name):
                        _played_event_sounds.add(sound_key)
                except Exception as exc:  # pragma: no cover - ääniominaisuus riippuu ympäristöstä
                    logger.warning(
                        "Ääniefektin toisto epäonnistui tapahtumalle %s (seed %s, päivä %s)",
                        event.name,
                        seed,
                        day,
                    )
                    logger.debug("Äänivirheen taustat", exc_info=exc)

            return event
        except Exception as exc:  # pragma: no cover - DB-virheet riippuvat konfiguraatiosta
            logger.exception(
                "Päivän tapahtuman haku epäonnistui seed=%s, day=%s", seed, day
            )
            raise RuntimeError("Päivän tapahtuman haku tietokannasta epäonnistui") from exc
        finally:
            try:
                cursor.close()
            except Exception:
                pass


def get_event_by_id(event_id: Optional[int]) -> Optional[FlightEvent]:
    """Julkinen apuri tapahtumien noutamiseen suoraan ID:llä."""

    if event_id is None:
        return None

    with get_connection() as conn:
        try:
            # mysql-connector saattaa yrittää palauttaa dict-kursoria; fallback tuplille.
            cursor = conn.cursor()
        except TypeError:
            cursor = conn.cursor()

        try:
            return _load_event_by_id(cursor, int(event_id))
        except Exception as exc:  # pragma: no cover - DB-virheet riippuvat konfiguraatiosta
            logger.exception("Tapahtuman haku epäonnistui ID:llä %s", event_id)
            raise RuntimeError("Tapahtuman haku tietokannasta epäonnistui") from exc
        finally:
            try:
                cursor.close()
            except Exception:
                pass


__all__ = ["FlightEvent", "init_events_for_seed", "get_event_for_day", "get_event_by_id"]

