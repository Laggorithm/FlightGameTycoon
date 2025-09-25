from decimal import Decimal, ROUND_HALF_UP
from datetime import datetime
from utils import get_connection

def save_progress(player_name, current_day, cash, difficulty, status, rng_seed, save_id=None):
    """
    Luo uuden tallennuksen tai päivittää olemassaolevaa game_saves-taulussa.
    Palauttaa save_id:n.
    """
    yhteys = get_connection()
    try:
        kursori = yhteys.cursor()
        now = datetime.utcnow().strftime("%Y-%m-%d %H:%M:%S")

        cash_dec = (cash if isinstance(cash, Decimal) else Decimal(str(cash))).quantize(
            Decimal("0.01"), rounding=ROUND_HALF_UP)

        if save_id is None:
            sql = """
                INSERT INTO game_saves (player_name, current_day, cash, difficulty, status, rng_seed, created_at, updated_at)
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
            """
            kursori.execute(sql, (player_name, current_day, cash_dec, difficulty, status, rng_seed, now, now))
            yhteys.commit()  # TÄRKEÄ
            save_id = kursori.lastrowid
        else:
            sql = """
                UPDATE game_saves
                SET player_name=%s, current_day=%s, cash=%s, difficulty=%s, status=%s, rng_seed=%s, updated_at=%s
                WHERE save_id=%s
            """
            kursori.execute(sql, (player_name, current_day, cash_dec, difficulty, status, rng_seed, now, save_id))
            yhteys.commit()  # TÄRKEÄ
        kursori.close()
        return save_id
    finally:
        yhteys.close()
