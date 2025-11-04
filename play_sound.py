"""Satunnaistapahtumien ääniefektien soitto."""

from __future__ import annotations

from pathlib import Path
from typing import Optional

from playsound3 import playsound

from utils import get_connection


# SFX-kansiota käytetään oletuspolkuna, jos tietokannasta tulee suhteellinen polku.
_MODULE_ROOT = Path(__file__).resolve().parent
_SFX_ROOT = _MODULE_ROOT / "sfx"


def event_playsound(event_name: str) -> bool:
    """Soittaa tapahtuman äänitiedoston, jos se on määritelty.

    Palauttaa True jos ääni toistettiin, muuten False. Mahdolliset virheet
    logitetaan käyttäjälle, mutta ne eivät pysäytä peliä.
    """

    if not event_name:
        return False

    sound_path: Optional[str] = None
    with get_connection() as yhteys:
        try:
            kursori = yhteys.cursor(dictionary=True)
        except TypeError:
            kursori = yhteys.cursor()

        try:
            kursori.execute(
                "SELECT sound_file FROM random_events WHERE event_name = %s LIMIT 1",
                (event_name,),
            )
            row = kursori.fetchone()
            if not row:
                return False

            sound_path = row["sound_file"] if isinstance(row, dict) else row[0]
        finally:
            try:
                kursori.close()
            except Exception:
                pass

    if not sound_path:
        return False

    file_path = Path(sound_path)
    if not file_path.is_absolute():
        if file_path.parts and file_path.parts[0] == "sfx":
            file_path = _MODULE_ROOT / file_path
        else:
            file_path = _SFX_ROOT / file_path

    if not file_path.exists():
        print(f"⚠️  Äänitiedostoa ei löytynyt: {file_path}")
        return False

    try:
        playsound(str(file_path))
        return True
    except Exception as err:
        print(f"⚠️  Äänen toisto epäonnistui ({event_name}): {err}")
        return False
