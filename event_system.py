
import random
from utils import get_connection

conn = get_connection()
cursor = conn.cursor()
FlightEvents = []
BorderEvents = []
#Object of flight event that will be containing all data and multipliers
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
#Unused yet, tbd
class BorderEvent:
    BorderEvents = {}
    currentBorderEvent = None
    def __init__(self, name, type, dangerLevel, duration, countries: tuple):
        self.name = name
        self.type = type
        self.dangerLevel = dangerLevel
        self.duration = duration
        self.countries = countries
#Used to get seed of world based on player_name data from game_saves db
def GetUserSeed(nickname):
    query = f'select rng_seed from game_saves where player_name = "{nickname}"'
    cursor.execute(query)
    row = cursor.fetchone()
    seed = row[0]
    return seed
#Name speaks for itself, doesn't it?
#Chooses and randomizes event for certain day, used in InitEvents
#Randomizes based on data from random_events that is being saved in dictionary FlightEvent.Events{Name of event: max chance of occurence}
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

#Checks for current event
#Used in this program, has no need to be used separately (I assume so)
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

#Must be called ONLY and RIGHT AFTER generation of seed
#Code creates pre-randomized list of events for player.
#Dates are calculated via seed * 1000, then adding + 1 for each of 666 days.
#Example of date: seed -- 123. Date needed is 13th day. Wil look like this: 123013 where 123 -- seed x1000 and 001-666 are days
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

#Used to select event for certain day, can be called during start of every flight.
#Code returns object with the needed multipliers that should be added then to the calculations in the main code
def SelectEvent(type, day, seed):
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
                    print(FlightEvent.currentFlightEvent.name)
    return FlightEvent.currentFlightEvent

#Test program, unnecessary for work of the events