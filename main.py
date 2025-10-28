# main.py
# -------
# - Sovelluksen käynnistyspiste ja CLI.
# - Käytetään yhtenäisiä yhteysmuuttujia: 'yhteys' ja 'kursori' (kursori = yhteys.cursor(...)).
# - Valikot: lisätty ikonit "kivan näköisiksi".
# - Uuden pelin alussa GameSession huolehtii tarinasta ja aloituspaketista.

from typing import Optional
from datetime import datetime
import sys
import random
from game_session import GameSession
from utils import get_connection


def _icon_title(title: str) -> None:
    """
    Pieni visuaalinen apu valikko-otsikoille.
    """
    bar = "═" * (len(title) + 2)
    print(f"\n╔{bar}╗")
    print(f"║ {title} ║")
    print(f"╚{bar}╝")

def list_recent_saves(limit: int = 20):
    """
    Listaa viimeisimmät tallennukset – nopea katsaus latausvalikkoon.
    """
    yhteys = get_connection()
    try:
        try:
            kursori = yhteys.cursor(dictionary=True)
        except TypeError:
            kursori = yhteys.cursor()

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
            print("ℹ️  Ei tallennuksia.")
            return

        _icon_title("Tallennukset")
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
            print(f"💾 ID {save_id:>3} | 👤 {name:<16} | 📅 Päivä {day:<4} | 💶 {cash} € | 🎚️ {diff:<6} | 🏷️ {status:<10} | ⏱️ {updated_str}")

    except Exception as e:
        print(f"❌ Virhe listattaessa tallennuksia: {e}")
    finally:
        try:
            kursori.close()
        except Exception:
            pass
        yhteys.close()


def prompt_nonempty(prompt: str, default: Optional[str] = None) -> str:
    """
    Apufunktio: varmista että käyttäjä antaa ei-tyhjän merkkijonon, tai käytetään oletusta.
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
    Uuden pelin aloitusvirta.
    - Kysytään nimi, aloituskassa (oletus 300000), optio RNG-siemen.
    - GameSession.new_game hoitaa intron (tarinan), ensimmäisen tukikohdan ja lahjakoneen.
    """
    _icon_title("Uusi peli")
    name = prompt_nonempty("👤 Pelaajan nimi")
    # Kassalle fiksu oletus; käyttäjä voi syöttää oman arvon
    try:
        cash_in = input("💶 Aloituskassa [300000]: ").strip()
        cash = float(cash_in) if cash_in else 300000.0
    except ValueError:
        print("⚠️  Virheellinen kassa, käytän oletusta 300000.")
        cash = 300000.0

    # ===== RNG-SIEMENEN KYSYMINEN =====
    print("\n🎲 RNG-siemen (satunnaislukugeneraattori):")
    print("   • Tyhjä = Normaali satunnainen peli")
    print("   • Numero (esim. 42) = Deterministinen peli")
    print("   • Sama siemen tuottaa AINA samat tapahtumat")
    print("   • Hyödyllinen testaukseen ja kilpailuihin\n")


    rng_in = input("Syötä siemen (tyhjä = satunnainen): ").strip()

    # Jos käyttäjä syötti numeron, käytä sitä. Muuten generoi satunnainen.
    if rng_in:
        try:
            rng_seed = int(rng_in)
            print(f"✅ Siemen {rng_seed} asetettu - Peli on nyt deterministinen!")
        except ValueError:
            print("⚠️ Virheellinen siemen, generoidaan satunnainen...")
            # Generate a random seed (e.g., between 1 and a large number)
            rng_seed = random.randint(1, 2**32 - 1)
            print(f"✅ Satunnainen siemen {rng_seed} generoitu.")
    else:
        # Generate a random seed if input is empty
        rng_seed = random.randint(1, 2**32 - 1)
        print(f"✅ Satunnainen siemen {rng_seed} generoitu.")

    try:
        gs = GameSession.new_game(
            name=name,
            cash=cash,
            show_intro=True,
            rng_seed=rng_seed,
            status="ACTIVE",
            default_difficulty="NORMAL",
        )
        gs.main_menu()
    except Exception as e:
        print(f"❌ Uuden pelin käynnistys epäonnistui: {e}")


def load_game():
    """
    Lataa aiemman tallennuksen ID:llä ja siirry päävalikkoon.
    """
    _icon_title("Lataa peli")
    list_recent_saves(limit=20)
    sel = input("\nSyötä ladattavan tallennuksen ID (tyhjä = peruuta): ").strip()
    if not sel:
        return
    try:
        save_id = int(sel)
    except ValueError:
        print("⚠️  Virheellinen ID.")
        return

    try:
        gs = GameSession.load(save_id)
        print(f"✅ Ladattiin tallennus #{gs.save_id} pelaajalle {gs.player_name}.")
        gs.main_menu()
    except Exception as e:
        print(f"❌ Lataus epäonnistui: {e}")


def main():
    """
    Päävalikko loopissa.
    """
    while True:
        print("\n" + "✈️  Air Freight Company 666".center(50, " "))
        print("━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━")
        print("1) 🌟 Uusi peli")
        print("2) 💾 Lataa peli")
        print("0) 🚪 Poistu")
        choice = input("Valinta: ").strip()
        if choice == "1":
            start_new_game()
        elif choice == "2":
            load_game()
        elif choice == "0":
            print("👋 Heippa!")
            break
        else:
            print("⚠️  Virheellinen valinta.")


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        print("\n⛔ Keskeytetty.")
        sys.exit(0)