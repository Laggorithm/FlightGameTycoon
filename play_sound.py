from utils import get_connection

from playsound3 import playsound

def event_playsound(event_id):
    sql = f"SELECT sfx FROM random_events WHERE event_id= {event_id}"
    yhteys = get_connection()
    kursori = yhteys.cursor()
    kursori.execute(sql)
    result = kursori.fetchall()
    sound_file = result
    playsound(sound_file)

event_playsound(event_id)
