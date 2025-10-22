import random
from utils import get_connection
conn = get_connection()
cursor = conn.cursor()
FlightEvents = []
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
def InitEvents(seed):
    CurrentDay = seed * 1000
    query = f'select * from player_fate where day = "{CurrentDay + 1}"'
    cursor.execute(query)
    row = cursor.fetchall()
    thisDay = CurrentDay
    if not row:
        for day in range(666):
            EventChecker("flight")
            FlightEvents.append(FlightEvent.currentFlightEvent)
        for event in FlightEvents:
            thisDay += 1
            query = f"""INSERT INTO player_fate (day, event_name) VALUES ({thisDay}, '{event.name}')"""
            cursor.execute(query)
    else:
        print("already exists")
def SelectEvent(seed, type, day):
    Date = seed * 1000 + day
    if type != None:
        if type == "flight":
            query = f'select event_name from player_fate where day = "{Date}"'
            cursor.execute(query)
            rows = cursor.fetchall()
            for row in rows:
                if row:
                    query = f'select * from random_events where event_name = "{row[0]}"'
                    cursor.execute(query)
                    row = cursor.fetchone()
                    FlightEvent.currentFlightEvent = FlightEvent(*row)
                    print(FlightEvent.currentFlightEvent)
                    print(FlightEvent.currentFlightEvent.name)
    return FlightEvent.currentFlightEvent
while True:
    DayEvent = int(input("todays day?: "))
    Seed = int(input("seed?: "))
    InitEvents(Seed)
    SelectEvent(Seed, "flight", DayEvent)
