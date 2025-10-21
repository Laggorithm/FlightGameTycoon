import random

from utils import get_connection
conn = get_connection()
cursor = conn.cursor()
class FlightEvent:
    FlightEvents = {}
    currentFlightEvent = None
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
def RandomizeFlightEvent():
    query = 'SELECT event_name, chance_max FROM random_events'
    cursor.execute(query)
    events = cursor.fetchall()
    FlightEvent.Events = {name: chancesmax for name, chancesmax in events}
    eventName = random.choice(list(FlightEvent.Events.keys()))
    chance = random.randint(1, FlightEvent.Events[eventName])
    if chance == FlightEvent.Events[eventName]:
        query = f'select * from random_events where event_name = "{eventName}"'
    else:
        query = 'select * from random_events where event_name = "Normal Day"'
    cursor.execute(query)
    row = cursor.fetchone()
    FlightEvent.currentFlightEvent = FlightEvent(*row)
    return FlightEvent.currentFlightEvent


def EventChecker(flightORcountry):
    if flightORcountry == "flight":
        if FlightEvent.currentFlightEvent == None:
            RandomizeFlightEvent()
        else:
            if FlightEvent.currentFlightEvent != None and FlightEvent.currentFlightEvent.duration > 0:
                FlightEvent.currentFlightEvent.duration -= 1
            if FlightEvent.currentFlightEvent.duration == 0:
                RandomizeFlightEvent()
            elif FlightEvent.currentFlightEvent == None or FlightEvent.currentFlightEvent.days < 0:
                print("bruh2: bruh strikes back, RESULTING IN EVENT SYSTEM ERRORS!!!!!")
                print(FlightEvent.currentFlightEvent.duration)
                print(FlightEvent.currentFlightEvent)
                FlightEvent.currentFlightEvent.duration = 0

FlightEvents = []
def InitEvents(days):
    for day in range(days):
        EventChecker("flight")
        FlightEvents.append(FlightEvent.currentFlightEvent)

InitEvents(666)
while True:
    DayEvent = int(input("todays day?: "))
    print(FlightEvents[DayEvent - 1].name)
