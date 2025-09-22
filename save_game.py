import mysql.connector
from datetime import datetime
from decimal import Decimal, ROUND_HALF_UP

def save_progress(player_name, current_day, cash, difficulty, status, rng_seed, save_id=None):
    """
    Luo uuden tallennuksen tai päivittää olemassaolevaa game_saves-taulussa.

    Args:
        player_name (str): Pelaajan nimi
        current_day (int): Pelipäivä
        cash (Decimal): Pelaajan rahat
        difficulty (str): Pelin vaikeustaso
        status (str): Tallennuksen status (esim. 'ACTIVE', 'LOST', 'WON')
        rng_seed (int): Satunnaisuuden siemen placeholder
        save_id (int|None): Jos None → luodaan uusi save. Jos annettu → päivitetään olemassaolevaa.

    Returns:
        save_id (int): Tallennuksen ID (AUTO_INCREMENT)
    """
    yhteys = mysql.connector.connect(
        host="localhost",
        user="golda",
        password="GoldaKoodaa",
        database="airway666"
    )
    kursori = yhteys.cursor()

    now = datetime.utcnow().strftime("%Y-%m-%d %H:%M:%S")

    cash_dec = (cash if isinstance(cash, Decimal) else Decimal(str(cash))).quantize(
        Decimal("0.01"), rounding=ROUND_HALF_UP)

    if save_id is None:
        # Luo uusi tallennus
        sql = """
            INSERT INTO game_saves (player_name, current_day, cash, difficulty, status, rng_seed, created_at, updated_at)
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
        """
        kursori.execute(sql, (player_name, current_day, cash_dec, difficulty, status, rng_seed, now, now))
        save_id = kursori.lastrowid
    else:
        # Päivitä olemassaoleva tallennus
        sql = """
            UPDATE game_saves
            SET player_name=%s, current_day=%s, cash=%s, difficulty=%s, status=%s, rng_seed=%s, updated_at=%s
            WHERE save_id=%s
        """
        kursori.execute(sql, (player_name, current_day, cash_dec, difficulty, status, rng_seed, now, save_id))

    kursori.close()
    yhteys.close()
    return save_id

# Uuden save-tallennuksen luonti
# save_id = save_progress(
    player_name="Goldaron",
    current_day=1,
    cash=50000.00,
    difficulty="NORMAL",
    status="ACTIVE",
    rng_seed=12345
#)
#print("Tallennuksen ID:", save_id)

# Progression päivittäminen olemassaolevaan tallennukseen
# save_progress(
    player_name="Goldaron",
    current_day=42,
    cash=250000.00,
    difficulty="NORMAL",
    status="ACTIVE",
    rng_seed=12345,
    save_id=save_id
#)
#print("Peli tallennettu.", save_id)
