import random
class Event:
    #Event list, can be freely expandable, but keep the "Normal Day" at index 10, for the sake of your every day not being "abducted by aliens"
    Events = {"Volcano": (1,50),
              "Aliens": (1,100),
              "Freezing Cold": (1,10),
              "Storm Clouds": (1,5),
              "Hurricane": (1,15),
              "Meteor": (1,70),
              "Worker Strikes": (1,6),
              "Sunny Sky": (1,3),
              "Favorable Winds": (1,7),
              "Best Day Ever": (1,15),
              "Normal Day": (0,0)}
    negativeEvents = {"Volcano": (1,0),
              "Aliens": (0.7,0.9),
              "Freezing Cold": (0.6,0.5),
              "Storm Clouds": (1,5),
              "Hurricane": (1,15),
              "Meteor": (1,70),
              "Worker Strikes": (1,6)}
    positiveEvents = {"Sunny Sky": (1,0.8),
              "Favorable Winds": (1,0.7),
              "Best Day Ever": (1,0.5),
              "Normal Day": (1,1)}
    keyChain = list(Events.keys()) #to search though id's like in normal list. F the dictionary
    def __init__(self, name, probability, id,):
        self.name = name
        self.probability = probability
        self.id = id
def apply_damage(event_name):
    negative = Event.negativeEvents[event_name]
    return negative
def apply_bonus(event_name):
    bonus = Event.positiveEvents[event_name]
    return bonus

    #Randomizing event in range of
def randomize_event():
    event_name = random.choice(list(Event.Events.keys()))
    print(event_name)
    min_val, max_val = Event.Events[event_name]
    randomizeEvent = random.randint(min_val, max_val)
    if randomizeEvent == max_val or randomizeEvent == min_val:
        currentEvent = event_name
    else:
        currentEvent = Event.keyChain[10]
        if currentEvent in Event.negativeEvents:
            apply_damage(currentEvent)
        elif currentEvent in Event.positiveEvents:
            apply_damage(currentEvent)
    return
