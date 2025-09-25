from utils import get_connection

def get_aircrafts_for_save(save_id):
    """
    Palauttaa kaikki pelaajan omistamat koneet tietokannasta.
    Liittää mukaan mallin nimen ja tukikohdan koodin.
    """
    yhteys = get_connection()
    kursori = yhteys.cursor(dictionary=True)

    query = """
        SELECT a.aircraft_id, a.nickname, a.registration, a.status,
               m.model_name, m.manufacturer,
               b.base_name, a.current_airport_ident
        FROM aircraft a
        JOIN aircraft_models m ON a.model_code = m.model_code
        JOIN owned_bases b ON a.base_id = b.base_id
        WHERE a.save_id = %s
    """
    kursori.execute(query, (save_id,))
    rows = kursori.fetchall()

    kursori.close()
    yhteys.close()
    return rows
