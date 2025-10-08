import random

from utils import get_connection
conn = get_connection()
cursor = conn.cursor()
class Event:
    Events = {}
    def __init__(self, id, name, description, Cmax, Pmult, dmg, days, duration, sfx):
        self.id = id
        self.name = name
        self.description = description
        self.Cmax = Cmax
        self.Pmult = Pmult
        self.dmg = dmg
        self.days = days
        self.duration = duration
        self.sfx = sfx
def RandomizeEvent():
    query = 'SELECT event_name, chance_max FROM random_events'
    cursor.execute(query)
    events = cursor.fetchall()
    Event.Events = {name: chancesmax for name, chancesmax in events}
    eventName = random.choice(list(Event.Events.keys()))
    chance = random.randint(1, Event.Events[eventName])
    if chance == Event.Events[eventName]:
        query = f'select * from random_events where event_name = "{eventName}"'
    else:
        query = 'select * from random_events where event_name = "Normal Day"'
    cursor.execute(query)
    row = cursor.fetchone()
    print(row)
    ActiveEvent = Event(*row)
    return ActiveEvent

event = RandomizeEvent()
print(event)
print(f"name {event.name}")
print(f"dmg {event.dmg}")
print(f"days {event.days}")




