# main.py
# -------
# - Sovelluksen käynnistyspiste ja yksinkertainen CLI.
# - STARTER-kone (DC3FREE) tulee vain uuden pelin alussa (toteutus game_sessionissa).
# - Kauppa suodattaa konemallit tukikohdan upgradetason mukaan (toteutus game_sessionissa).
# - Yhteysmuuttujat 'yhteys' ja 'kursori' pidetään yhdenmukaisina.

from typing import Optional
from datetime import datetime
import sys

from game_session import GameSession
from utils import get_connection


def list_recent_saves(limit: int = 20):
    """
    Listaan viimeisimmät tallennukset – nopea katsaus latausvalikkoon.
    """
    yhteys = get_connection()
    # Yritän dict-kurssoria, mutta varaudun myös tuple-riveihin
    try:
        kursori = yhteys.cursor(dictionary=True)
    except TypeError:
        kursori = yhteys.cursor()
    try:
        kursori.execute(
            """
            SELECT save_id, player_name, current_day, cash, difficulty, status, updated_at, created_at
            FROM game_saves
            ORDER BY COALESCE(updated_at, created_at) DESC
            LIMIT %s
            """,
            (limit,),
        )
        rivit = kursori.fetchall() or []
        if not rivit:
            print("Ei tallennuksia.")
            return

        print("\nViimeisimmät tallennukset:")
        for r in rivit:
            if isinstance(r, dict):
                save_id = r["save_id"]
                name = r["player_name"]
                day = r["current_day"]
                cash = r["cash"]
                diff = r["difficulty"]
                status = r["status"]
                updated = r["updated_at"] or r["created_at"]
            else:
                save_id, name, day, cash, diff, status, updated, created = r
                updated = updated or created
            updated_str = updated.strftime("%Y-%m-%d %H:%M") if isinstance(updated, datetime) else str(updated)
            print(f"- ID {save_id}: {name} | Päivä {day} | Kassa {cash} € | {diff} | {status} | {updated_str}")
    except Exception as e:
        print(f"Virhe listattaessa tallennuksia: {e}")
    finally:
        try:
            kursori.close()
        except Exception:
            pass
        yhteys.close()


def prompt_nonempty(prompt: str, default: Optional[str] = None) -> str:
    """
    Pieni apufunktio: varmistan ettei käyttäjä paina vain Enteriä jos arvo on pakollinen.
    """
    while True:
        val = input(f"{prompt}{f' [{default}]' if default else ''}: ").strip()
        if val:
            return val
        if default is not None:
            return default
        print("Arvo ei voi olla tyhjä.")


def start_new_game():
    """
    Uuden pelin aloitus.
    - En kysele vaikeusastetta (ei ole käytössä UI:ssa).
    - Tukikohta ostetaan ja STARTER-lahjakone lisätään game_session.new_game:n sisällä.
    """
    print("\n=== Uusi peli ===")
    name = prompt_nonempty("Pelaajan nimi")
    # Kassalle käytän fiksua oletusta; halutessaan käyttäjä voi syöttää oman
    try:
        cash_in = input("Aloituskassa [300000]: ").strip()
        cash = float(cash_in) if cash_in else 300000.0
    except ValueError:
        print("Virheellinen kassa, käytän oletusta 300000.")
        cash = 300000.0

    # RNG-siemen on vapaaehtoinen
    rng_in = input("RNG siemen (tyhjä = satunnainen/None): ").strip()
    rng_seed = int(rng_in) if rng_in else None

    try:
        gs = GameSession.new_game(
            name=name,
            cash=cash,
            show_intro=True,
            rng_seed=rng_seed,
            status="ACTIVE",
            default_difficulty="NORMAL",  # tallennetaan kantaan, UI ei käytä
        )
        # Siirrytään päävalikkoon
        gs.main_menu()
    except Exception as e:
        print(f"Uuden pelin käynnistys epäonnistui: {e}")


def load_game():
    """
    Lataan aiemman tallennuksen ID:llä ja siirryn päävalikkoon.
    """
    print("\n=== Lataa peli ===")
    list_recent_saves(limit=20)
    sel = input("\nSyötä ladattavan tallennuksen ID (tyhjä = peruuta): ").strip()
    if not sel:
        return
    try:
        save_id = int(sel)
    except ValueError:
        print("Virheellinen ID.")
        return

    try:
        gs = GameSession.load(save_id)
        print(f"Ladattiin tallennus #{gs.save_id} pelaajalle {gs.player_name}.")
        gs.main_menu()
    except Exception as e:
        print(f"Lataus epäonnistui: {e}")


def main():
    """
    Yksinkertainen pääsilmukka: luo uusi peli, lataa peli tai poistu.
    """
    while True:
        print("\n=== Flight Game Tycoon ===")
        print("1) Uusi peli")
        print("2) Lataa peli")
        print("0) Poistu")
        choice = input("Valinta: ").strip()
        if choice == "1":
            start_new_game()
        elif choice == "2":
            load_game()
        elif choice == "0":
            print("Heippa!")
            break
        else:
            print("Virheellinen valinta.")


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        print("\nKeskeytetty.")
        sys.exit(0)