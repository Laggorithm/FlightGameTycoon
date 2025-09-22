#Error Codes:
#1 -- wrong input during upgrading (upgrade level possibly wasn't an int)
#2 -- error in connecting to sql database or fetching data from it
#3 -- error in list checker (problem with adding or checking for airplanes)
#4 -- list of airplanes is empty. Either initialization went wrong or append didn't work properly

import mysql.connector
class airplane:
    def __init__(self, aircraft_id, model_code, base_level, current_airport_ident, registration, nickname, acquired_day, purchase_price, condition_percent, status, hours_flown, sold_day, sale_price, speed_day, save_id, base_id, ident):
        self.aircraft_id = aircraft_id
        self.model_code = model_code
        self.base_level = base_level
        self.current_airport_ident = current_airport_ident
        self.registration = registration
        self.nickname = nickname
        self.acquired_day = acquired_day
        self.purchase_price = purchase_price
        self.condition_percent = condition_percent
        self.status = status
        self.hours_flown = hours_flown
        self.sold_day = sold_day
        self.sale_price = sale_price
        self.speed_day = speed_day
        self.save_id = save_id
        self.base_id = base_id
        self.ident = ident
class aircraft_Model(airplane):
    def __init__(self, model_code, manufacturer, model_name, purchase_price, base_cargo_kg, range_km, cruise_speed_kts, category, upkeep_price, efficiency_score, co2_kg_per_km, eco_class, eco_free_multiplier):
        self.model_code = model_code
        self.manufacturer = manufacturer
        self.model_name = model_name
        self.purchase_price = purchase_price
        self.base_cargo_kg = base_cargo_kg
        self.range_km = range_km
        self.cruise_speed_kts = cruise_speed_kts
        self.category = category
        self.upkeep_price = upkeep_price
        self.efficiency_score = efficiency_score
        self.co2_kg_per_km = co2_kg_per_km
        self.eco_class = eco_class
        self.eco_free_multiplier = eco_free_multiplier
        super().__init__(model_code, purchase_price)
class aircraft_upgrade(airplane):
    def __init__(self, aircraft_upgrade_id, aircraft_id, upgrade_code, level, installed_day,):
        self.aircraft_id = aircraft_id
        self.upgrade_code = upgrade_code
        self.level = level
        self.installed_day = installed_day
        super().__init__(aircraft_id, aircraft_upgrade_id)
def upgrade_airplane(id, level):
    try:
        for airplane in Aircrafts:
            if airplane.aircraft_id == id:
                airplane.upgrade_level += level
    except ValueError:
        print("Error code 1")
    return
def init_airplanes():
    try:
        connection = mysql.connector.connect(
            host='localhost',
            port=3306,
            database='airway666',
            user='Laggorithm',
            password='CupOfLiberTea',
            autocommit=True)
        cursor = connection.cursor()
        count = f"select count(*) from airplane group by aircraft_id order by aircraft_id asc;"
        cursor.execute(count)
        count = cursor.fetchall()
        total = sum(row[0] for row in count)
        for i in range(total):
            query = "SELECT aircraft_id, model_code, base_level, current_airport_ident, registration, nickname, acquired_day, purchase_price, condition_percent, status, hours_flown, sold_day, sale_price, speed_day, save_id, base_id, ident FROM airplane;"
            cursor = connection.cursor()
            cursor.execute(query)
            rows = cursor.fetchall()
            Aircrafts = []

            for row in rows:
                plane = aircraft_Model
                (
                    plane.aircraft_id,
                    plane.model_code,
                    plane.base_level,
                    plane.current_airport_ident,
                    plane.registration,
                    plane.nickname,
                    plane.acquired_day,
                    plane.purchase_price,
                    plane.condition_percent,
                    plane.status,
                    plane.hours_flown,
                    plane.sold_day,
                    plane.sale_price,
                    plane.speed_day,
                    plane.save_id,
                    plane.base_id,
                    plane.ident
                ) = row

                Aircrafts.append(plane)
        print_aircrafts()
    except mysql.connector.Error as err:
        print(err)
        print("Error code: 2")
    return
def print_aircrafts():
    try:
        if not Aircrafts:
            print("Error code 4.")
            return

        for i, plane in enumerate(Aircrafts, start=1):
            print(f"\n✈Plane id: #{i}")
            print(f"  aircraft_id: {plane.aircraft_id}")
            print(f"  model_code: {plane.model_code}")
            print(f"  base_level: {plane.base_level}")
            print(f"  current_airport_ident: {plane.current_airport_ident}")
            print(f"  registration: {plane.registration}")
            print(f"  nickname: {plane.nickname}")
            print(f"  acquired_day: {plane.acquired_day}")
            print(f"  purchase_price: {plane.purchase_price}")
            print(f"  condition_percent: {plane.condition_percent}")
            print(f"  status: {plane.status}")
            print(f"  hours_flown: {plane.hours_flown}")
            print(f"  sold_day: {plane.sold_day}")
            print(f"  sale_price: {plane.sale_price}")
            print(f"  speed_day: {plane.speed_day}")
            print(f"  save_id: {plane.save_id}")
            print(f"  base_id: {plane.base_id}")
            print(f"  ident: {plane.ident}")
    except ValueError:
        print("Error code 3.")
#PROGRAMMMMMMMMMMMMMM
Aircrafts: list[airplane] = []

init_airplanes()