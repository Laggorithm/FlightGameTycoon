from utils import get_connection

from playsound3 import playsound

def event_playsound(event_name):
    sql = f"SELECT sound_file FROM random_events WHERE event_name= {event_name}"
    yhteys = get_connection()
    kursori = yhteys.cursor()
    kursori.execute(sql)
    result = kursori.fetchall()
    sound_file = result
    playsound(sound_file)

event_playsound(event_name)
