"""Helper utilities extracted from game_session module."""

from .common import _to_dec, _icon_title
from .aircraft import (
    fetch_player_aircrafts_with_model_info,
    get_current_aircraft_upgrade_state,
    compute_effective_eco_multiplier,
    calc_aircraft_upgrade_cost,
    apply_aircraft_upgrade,
    get_effective_eco_for_aircraft,
)
from .bases import (
    fetch_owned_bases,
    fetch_base_current_level_map,
    insert_base_upgrade,
)

__all__ = [
    "_to_dec",
    "_icon_title",
    "fetch_player_aircrafts_with_model_info",
    "get_current_aircraft_upgrade_state",
    "compute_effective_eco_multiplier",
    "calc_aircraft_upgrade_cost",
    "apply_aircraft_upgrade",
    "get_effective_eco_for_aircraft",
    "fetch_owned_bases",
    "fetch_base_current_level_map",
    "insert_base_upgrade",
]
