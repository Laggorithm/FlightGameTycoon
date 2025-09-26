# upgrade_config.py
# -----------------
# Keskitetty konfiguraatio/vakiot.
# - Pidetään talous- ja upgrade-vakiot yhdessä, jotta importoinnit ovat selkeitä,
#   eikä koodi kaadu puuttuvien symbolien takia (NameError).
# - Käytetään Decimaliä rahaan, jotta vältetään float-pyöristysvirheet.

from decimal import Decimal

# ---------- ECO-upgrade (lentokoneiden ympäristökerroin) ----------

# Yhdenmukainen koodi ECO-upgradelle aircraft_upgrades-taulussa
UPGRADE_CODE: str = "ECO"

# ECO-päivityksen oletusparametrit (talletetaan joka riville turvaan)
DEFAULT_ECO_FACTOR_PER_LEVEL: Decimal = Decimal("0.1")  # -10 % per taso (korottaa kannattavuutta vähentämällä veroja/fee-maksuja)
DEFAULT_ECO_FLOOR: Decimal = Decimal("0.50")             # Ekokerroin ei nostaa 0.5 yli, niin ettei pelajaa saa liikaa bonustaa

# Hinnastokonfiguraatio ECO-upgradeihin (suositus; voidaan muuttaa balansoimiseksi):
# STARTER-koneille (lahja) oma skaala, muille ostohintaan sidottu pohja.
STARTER_BASE_COST: Decimal = Decimal("100000")    # Ensimmäisen tason lähtöhinta STARTERille
STARTER_GROWTH: Decimal = Decimal("1.25")         # STARTER-hinnan kasvukerroin per taso

NON_STARTER_BASE_PCT: Decimal = Decimal("0.10")   # 10 % koneen ostohinnasta pohjaksi
NON_STARTER_MIN_BASE: Decimal = Decimal("100000") # Vähintään 100k pohjahinta
NON_STARTER_GROWTH: Decimal = Decimal("1.20")     # Hinnan kasvukerroin per taso

# ---------- Talous: kuukausilaskut (joka 30. päivä) ----------

# HQ (pääkonttori) kuukausittainen kiinteä maksu
HQ_MONTHLY_FEE: Decimal = Decimal("25000.00")

# Konekohtainen huoltomaksu per 30 päivää (aktiiviset, ei myydyt koneet)
MAINT_PER_AIRCRAFT: Decimal = Decimal("5000.00")

# Joillekin STARTER-lahjakoneille voit halutessasi antaa alennusta:
STARTER_MAINT_DISCOUNT: Decimal = Decimal("1.00")  # 1.00 = ei alennusta; esim. 0.50 = -50 %

# ---------- Pelin tavoite ----------

# Selviämistavoite (päivien määrä)
SURVIVAL_TARGET_DAYS: int = 666
