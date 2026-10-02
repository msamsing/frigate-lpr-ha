"""Native plate selector for dashboard detail views."""

from __future__ import annotations

from typing import Any

from homeassistant.components.select import SelectEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.dispatcher import async_dispatcher_connect
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .const import DOMAIN, SIGNAL_UPDATE
from .manager import LPRManager


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up the native plate selector."""
    async_add_entities([LPRPlateSelect(entry.runtime_data, entry.entry_id)])


class LPRPlateSelect(SelectEntity):
    """Select one observed plate and expose its detail attributes."""

    _attr_has_entity_name = True
    _attr_name = "Valgt nummerplade"
    _attr_icon = "mdi:card-account-details"
    _attr_suggested_object_id = "frigate_lpr_selected_plate"

    def __init__(self, manager: LPRManager, entry_id: str) -> None:
        self.manager = manager
        self.entry_id = entry_id
        self._attr_unique_id = f"{entry_id}_selected_plate"
        self._current_option: str | None = None
        self._attr_device_info = {
            "identifiers": {(DOMAIN, entry_id)},
            "name": "Frigate LPR Registry",
            "manufacturer": "Frigate",
            "model": "LPR Registry",
        }

    @property
    def options(self) -> list[str]:
        """Return all plates, most recently seen first."""
        return sorted(
            self.manager.registry.plates,
            key=lambda plate: self.manager.registry.plates[plate].get("last_seen") or "",
            reverse=True,
        )

    @property
    def current_option(self) -> str | None:
        if self._current_option in self.manager.registry.plates:
            return self._current_option
        return self.options[0] if self.options else None

    async def async_select_option(self, option: str) -> None:
        """Select a plate for the native detail panel."""
        if option not in self.manager.registry.plates:
            raise ValueError(f"Unknown plate: {option}")
        self._current_option = option
        self.async_write_ha_state()

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        base = {
            "frigate_lpr_view": "selected_plate",
            "motorapi_enabled": bool(
                self.manager.motorapi_enabled and self.manager.motorapi_key
            ),
            "speed_enabled": self.manager.speed_enabled,
            "speed_limit": self.manager.speed_limit,
        }
        plate = self.current_option
        if not plate:
            return base
        view = self.manager.registry.plate_view(plate)
        return {
            **base,
            "plate": plate,
            "name": view["name"] or view["frigate_name"],
            "user_category": view["category"],
            "classification": view["classification"],
            "first_seen": view["first_seen"],
            "last_seen": view["last_seen"],
            "observations_count": view["count"],
            "different_days": view["different_days"],
            "average_interval_hours": view["average_interval_hours"],
            "time_stats": view["time_stats"],
            "pattern": view["pattern"],
            "speed_stats": view["speed_stats"],
            "observations": view["observations"][-20:],
            "vehicle": view.get("vehicle"),
            "vehicle_source": view.get("vehicle_source"),
            "vehicle_lookup_status": (view.get("vehicle_lookup") or {}).get("status", "not_attempted"),
            "notes": view.get("notes", ""),
            "snapshot": view.get("snapshot"),
            "ignored": view.get("ignored", False),
        }

    async def async_added_to_hass(self) -> None:
        self.async_on_remove(
            async_dispatcher_connect(
                self.hass,
                f"{SIGNAL_UPDATE}_{self.entry_id}",
                self._handle_update,
            )
        )

    @callback
    def _handle_update(self) -> None:
        self.async_write_ha_state()
