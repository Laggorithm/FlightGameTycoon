import random

from utils import get_connection
conn = get_connection()
cursor = conn.cursor()
class Event:
    Events = {}
    def __init__(self, Cmax, Pmult, dmg, days, duration, sfx):
        self.Cmax = Cmax
        self.Pmult = Pmult
        self.dmg = dmg
        self.days = days
        self.duration = duration
        self.sfx = sfx
def RandomizeEvent():
    query = 'SELECT event_name, chance_max FROM events'
    cursor.execute(query)
    events = cursor.fetchall()
    Event.Events = {name: chancesmax for name, chancesmax in events}
    eventName = random.choice(list(Event.Events.keys()))
    chance = random.randint(1, Event.Events[eventName])

    if chance == Event.Events[eventName]:
        query = 'select * from events where event_name = f"{eventName}"'
    else:
        query = 'select * from events where event_name = "Normal_Day"'
    cursor.execute(query)
    row = cursor.fetchone()
    if row:
        ActiveEvent = Event(*row)
    if not row:
        ActiveEvent = "None"
        print("Nothing found, huh?")
    return ActiveEvent






