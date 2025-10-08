# Keskitetty konfiguraatio/vakiot.
# - Pidetään talous- ja upgrade-vakiot yhdessä, jotta importoinnit pysyvät selkeinä
#   eikä koodi kaadu puuttuvien symbolien takia.
# - Käytetään Decimaliä rahaan, jotta vältetään float-pyöristysvirheet ja varmistetaan
#   deterministinen rahalaskenta.

from decimal import Decimal

# --------- Palkkion muodostus ------------------------------------
# Perusmalli pitää palkkion riippuvuuden selkeänä: lineaarinen painon ja etäisyyden suhteen.
# Pienin palkkio estää mitättömät keikat; sakko sidotaan suoraan palkkioon.
TASK_REWARD_PER_KG: Decimal = Decimal("2.50")   # €/kg
TASK_REWARD_PER_KM: Decimal = Decimal("1.90")    # €/km
TASK_MIN_REWARD: Decimal = Decimal("250.00")     # alin sallittu palkkio
TASK_PENALTY_RATIO: Decimal = Decimal("0.30")    # sakko-osuus palkkiosta

# ---------- ECO-upgrade (lentokoneiden ympäristökerroin) ----------
# Tavoite on mallintaa ympäristötehokkuuden vaikutusta (vero/fee/tehokkuus) yhteen kertoimeen,
# jota voidaan käyttää palkkion tai kustannusten modifiointiin. Delta (muutos) muunnetaan
# kertoimeksi muodossa (1 + delta), ja lopuksi rajataan turvarajoilla.
#
# Esimerkki: delta = +0.05 -> kerroin x1.05, delta = -0.30 -> kerroin x0.70.

# Yhdenmukainen koodi ECO-upgradelle aircraft_upgrades-taulussa
UPGRADE_CODE: str = "ECO"

# Oletusparametrit päivitystason vaikutukselle ja delta-alarajalle
# DEFAULT_ECO_FACTOR_PER_LEVEL kuvaa per-taso vaikutusta deltalukuna (esim. 0.05 = +5 %).
# DEFAULT_ECO_FLOOR on delta-alaraja: kokonaisdelta ei laske tätä alemmaksi.
DEFAULT_ECO_FACTOR_PER_LEVEL: Decimal = Decimal("0.05")  # 5 % per taso
DEFAULT_ECO_FLOOR: Decimal = Decimal("-0.50")            # delta-alaraja: -50 %

# Turvarajat valmiiksi muunnetulle kertoimelle (multiplikatiivinen kerroin)
ECO_MULT_MIN: Decimal = Decimal("0.10")  # vähintään x0.10 (estää nollan ja negatiiviset)
ECO_MULT_MAX: Decimal = Decimal("5.00")  # enintään x5.00 (estää ylisuuret arvot)

# Luokkakohtaiset säännöt. Näillä voidaan hienosäätää deltaa koneluokittain:
# - delta: perusmuutos (lisätään kokonaisdeltaan ennen kertoimeksi muuntoa)
# - min: alaraja deltaluvulle tälle luokalle
# - max: yläraja deltaluvulle tälle luokalle
# Arvot deltoina (esim. -0.20 = -20 %, +0.50 = +50 %). Tietoisesti pidetty yksiköinä (float),
# jotta pelitasapainoa voi säätää helposti ilman rahalaskennan Decimaliä.
ECO_CLASS_RULES: dict = {
    "A": {"delta": 0.00, "min": -0.20, "max": 0.50},  # Valmiiksi tehokas
    "B": {"delta": 0.02, "min": -0.30, "max": 0.50},
    "C": {"delta": 0.03, "min": -0.40, "max": 0.50},
    "D": {"delta": 0.04, "min": -0.50, "max": 0.50},
    "E": {"delta": 0.05, "min": -0.60, "max": 0.50},  # Heikoin alussa → suurin hyöty päivityksistä
    "DEFAULT": {"delta": 0.03, "min": -0.50, "max": 0.50},
}

# ---------- Upgrade-kustannukset ----------
# Kaksitasoinen malli: STARTER-koneille oma kiinteä perusta, muille ostohintaan sidottu.
# Hinnat kasvavat geometrisesti tasojen mukana, mikä pitää skaalauksen hallittavana.
STARTER_BASE_COST: Decimal = Decimal("100000")   # 1. tason lähtöhinta STARTERille
STARTER_GROWTH: Decimal = Decimal("1.25")        # kasvukerroin per taso STARTERille

NON_STARTER_BASE_PCT: Decimal = Decimal("0.10")  # 10 % koneen ostohinnasta pohjaksi
NON_STARTER_MIN_BASE: Decimal = Decimal("100000")# absoluuttinen minimi pohjahinnalle
NON_STARTER_GROWTH: Decimal = Decimal("1.20")    # kasvukerroin per taso muille kuin STARTER

# ---------- Talous: kuukausilaskut (joka 30. päivä) ----------
# Kiinteät kulut luovat jatkuvan tarpeen lentää. Huollon alennuksella voidaan
# pehmentää aloitusta ilman mikromanagerointia.
HQ_MONTHLY_FEE: Decimal = Decimal("125000.00")    # pääkonttorin kuukausimaksu
REPAIR_COST_PER_PERCENT: Decimal = Decimal("3000.00")
MAINT_PER_AIRCRAFT: Decimal = Decimal("15000.00") # huoltomaksu per kone per 30 pv
STARTER_MAINT_DISCOUNT: Decimal = Decimal("1.00")# 1.00 = ei alennusta; esim. 0.50 = -50 %
# Kuukausilaskujen kasvu (korkoa korolle)
# Tämä kerroin astuu voimaan 60. päivästä alkaen. Oletus: 0.05 = 5% kasvu per 30 pv.
BILL_GROWTH_RATE: Decimal = Decimal("0.05")

# ---------- Pelin tavoite ----------
# Suuntaa-antava tavoite tasapainolle: kuinka monen päivän yli pitäisi kyetä
# selviämään tyypillisellä pelillä ilman konkurssia.
SURVIVAL_TARGET_DAYS: int = 666