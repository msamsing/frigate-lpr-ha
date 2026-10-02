"""Sensor entities for Frigate LPR Registry."""

from __future__ import annotations

from typing import Any

from homeassistant.components.sensor import SensorEntity, SensorStateClass
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.dispatcher import async_dispatcher_connect
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.util import dt as dt_util

from .const import DOMAIN, SIGNAL_NEW_PLATE, SIGNAL_UPDATE
from .manager import LPRManager


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry, async_add_entities: AddEntitiesCallback) -> None:
    manager: LPRManager = entry.runtime_data
    async_add_entities([
        LPRSummarySensor(manager, entry.entry_id, "unique_today", "Unikke plader i dag"),
        LPRSummarySensor(manager, entry.entry_id, "observations_today", "Observationer i dag"),
        LPRSummarySensor(manager, entry.entry_id, "total_unique", "Unikke plader i alt"),
        LPRListSensor(manager, entry.entry_id, "recent", "Seneste nummerplade"),
        LPRListSensor(manager, entry.entry_id, "frequent", "Hyppigste nummerplader"),
        LPRListSensor(manager, entry.entry_id, "one_time", "Nye og engangsbesøgende"),
        LPRListSensor(manager, entry.entry_id, "known", "Kendte nummerplader"),
        LPRListSensor(manager, entry.entry_id, "own", "Egne nummerplader"),
        LPRListSensor(manager, entry.entry_id, "known_local", "Kendte lokale nummerplader"),
        LPRListSensor(manager, entry.entry_id, "frequent_class", "Hyppige nummerplader"),
        LPRListSensor(manager, entry.entry_id, "rare", "Sjældne nummerplader"),
        LPRTrafficSensor(manager, entry.entry_id),
    ])
    known_entities = set(manager.registry.plates)
    async_add_entities([LPRPlateSensor(manager, entry.entry_id, plate) for plate in known_entities])

    @callback
    def add_plate(plate: str) -> None:
        if plate not in known_entities:
            known_entities.add(plate)
            async_add_entities([LPRPlateSensor(manager, entry.entry_id, plate)])

    entry.async_on_unload(async_dispatcher_connect(hass, f"{SIGNAL_NEW_PLATE}_{entry.entry_id}", add_plate))


class LPRBaseSensor(SensorEntity):
    _attr_has_entity_name = True

    def __init__(self, manager: LPRManager, entry_id: str) -> None:
        self.manager = manager
        self.entry_id = entry_id
        self._attr_device_info = {
            "identifiers": {(DOMAIN, entry_id)},
            "name": "Frigate LPR Registry",
            "manufacturer": "Frigate",
            "model": "LPR Registry",
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


class LPRSummarySensor(LPRBaseSensor):
    _attr_native_unit_of_measurement = "registreringer"
    _attr_state_class = SensorStateClass.TOTAL

    def __init__(self, manager: LPRManager, entry_id: str, key: str, name: str) -> None:
        super().__init__(manager, entry_id)
        self.key = key
        self._attr_name = name
        self._attr_unique_id = f"{entry_id}_{key}"
        self._attr_suggested_object_id = f"frigate_lpr_{key}"

    @property
    def native_value(self) -> int:
        return self.manager.registry.summary(dt_util.now().date().isoformat())[self.key]

    @property
    def extra_state_attributes(self) -> dict[str, str]:
        return {"frigate_lpr_view": self.key}


class LPRListSensor(LPRBaseSensor):
    def __init__(self, manager: LPRManager, entry_id: str, key: str, name: str) -> None:
        super().__init__(manager, entry_id)
        self.key = key
        self._attr_name = name
        self._attr_unique_id = f"{entry_id}_{key}"
        self._attr_suggested_object_id = f"frigate_lpr_{key}"

    @property
    def native_value(self) -> str:
        items = self.manager.registry.summary(dt_util.now().date().isoformat())[self.key]
        if not items:
            return "Ingen"
        return items[0]["plate"]

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        summary = self.manager.registry.summary(dt_util.now().date().isoformat())
        return {
            "frigate_lpr_view": self.key,
            "items": summary[self.key],
            "classifications": summary["classifications"],
        }


class LPRPlateSensor(LPRBaseSensor):
    def __init__(self, manager: LPRManager, entry_id: str, plate: str) -> None:
        super().__init__(manager, entry_id)
        self.plate = plate
        self._attr_name = plate
        self._attr_unique_id = f"{entry_id}_plate_{plate}"
        self._attr_suggested_object_id = f"frigate_lpr_plate_{plate.lower()}"

    @property
    def native_value(self) -> int:
        return self.manager.registry.plates[self.plate]["count"]

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        view = self.manager.registry.plate_view(self.plate)
        return {
            "frigate_lpr_view": "plate",
            "plate": self.plate,
            "name": view["name"] or view["frigate_name"],
            "user_category": view["category"],
            "classification": view["classification"],
            "first_seen": view["first_seen"],
            "last_seen": view["last_seen"],
            "different_days": view["different_days"],
            "intervals_seconds": view["intervals_seconds"][-50:],
            "average_interval_hours": view["average_interval_hours"],
            "time_stats": view["time_stats"],
            "pattern": view["pattern"],
            "speed_stats": view["speed_stats"],
            "observations": view["observations"][-50:],
            "shown_observations": min(50, view["count"]),
            "stored_observations": view["count"],
            "vehicle": view.get("vehicle"),
            "vehicle_source": view.get("vehicle_source"),
            "vehicle_lookup_status": (view.get("vehicle_lookup") or {}).get("status", "not_attempted"),
            "notes": view.get("notes", ""),
            "snapshot": view.get("snapshot"),
            "ignored": view.get("ignored", False),
        }


class LPRTrafficSensor(LPRBaseSensor):
    """Expose aggregate traffic statistics for the dashboard."""

    _attr_name = "Trafikstatistik"
    _attr_icon = "mdi:chart-bar"

    def __init__(self, manager: LPRManager, entry_id: str) -> None:
        super().__init__(manager, entry_id)
        self._attr_unique_id = f"{entry_id}_traffic_stats"
        self._attr_suggested_object_id = "frigate_lpr_traffic_stats"

    @property
    def native_value(self) -> int:
        return self.manager.registry.summary(dt_util.now().date().isoformat())["traffic_stats"]["total_passages"]

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        traffic = self.manager.registry.summary(
            dt_util.now().date().isoformat()
        )["traffic_stats"]
        speed = dict(traffic["speed"])
        speed["over_limit"] = sum(
            1
            for record in self.manager.registry.plates.values()
            if not record.get("ignored")
            for observation in record["observations"]
            if observation.get("speed_kmh") is not None
            and float(observation["speed_kmh"]) > self.manager.speed_limit
        )
        return {
            "frigate_lpr_view": "traffic_stats",
            "speed_enabled": self.manager.speed_enabled,
            "speed_limit": self.manager.speed_limit,
            **traffic,
            "speed": speed,
        }
