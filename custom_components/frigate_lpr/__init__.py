"""Frigate LPR Registry integration."""

from __future__ import annotations

import logging
from pathlib import Path

from aiohttp import web
import voluptuous as vol

from homeassistant.components import frontend
from homeassistant.components.http import KEY_HASS, HomeAssistantView, StaticPathConfig
from homeassistant.components.lovelace.const import LOVELACE_DATA, MODE_STORAGE
from homeassistant.components.lovelace.resources import ResourceStorageCollection
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import CONF_NAME
from homeassistant.core import HomeAssistant, ServiceCall
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers import config_validation as cv
from homeassistant.util import dt as dt_util

from .const import (
    CARD_RESOURCE_PATH,
    CARD_URL,
    CONF_CAMERA,
    CONF_FREQUENT_DAYS,
    CONF_FREQUENT_OBSERVATIONS,
    CONF_MOTORAPI_ENABLED,
    CONF_MOTORAPI_KEY,
    CONF_SNAPSHOTS_ENABLED,
    CONF_SNAPSHOT_ENTITY,
    CONF_SPEED_ENABLED,
    CONF_EVENTS_TOPIC,
    CONF_SPEED_LIMIT,
    CONF_SPEED_UNIT,
    CONF_NOTIFY_SERVICE_1,
    CONF_NOTIFY_SERVICE_2,
    CONF_NOTIFY_CRITICAL,
    CONF_TOPIC,
    DEFAULT_FREQUENT_DAYS,
    DEFAULT_FREQUENT_OBSERVATIONS,
    DEFAULT_MOTORAPI_ENABLED,
    DEFAULT_SNAPSHOTS_ENABLED,
    DEFAULT_SPEED_ENABLED,
    DEFAULT_EVENTS_TOPIC,
    DEFAULT_SPEED_LIMIT,
    DEFAULT_SPEED_UNIT,
    DEFAULT_NOTIFY_CRITICAL,
    DOMAIN,
    PLATFORMS,
    SERVICE_REMOVE_PLATE_METADATA,
    SERVICE_LOOKUP_VEHICLE,
    SERVICE_REMOVE_OBSERVATION,
    SERVICE_REMOVE_SNAPSHOT,
    SERVICE_SET_PLATE,
    SERVICE_UPDATE_OBSERVATION,
    SNAPSHOT_API_PATH,
    STATIC_URL_PATH,
)
from .manager import LPRManager
from .migration import async_remove_legacy_dashboard

_LOGGER = logging.getLogger(__name__)
_FRONTEND_REGISTERED = f"{DOMAIN}_frontend_registered"
_SNAPSHOT_VIEW_REGISTERED = f"{DOMAIN}_snapshot_view_registered"

FrigateLPRConfigEntry = ConfigEntry[LPRManager]

SET_PLATE_SCHEMA = vol.Schema(
    {
        vol.Required("plate"): cv.string,
        vol.Required(CONF_NAME): cv.string,
        vol.Required("category"): vol.In(["own", "known", "unknown", "unwanted"]),
        vol.Optional("notes"): cv.string,
        vol.Optional("make"): cv.string,
        vol.Optional("model"): cv.string,
        vol.Optional("variant"): cv.string,
        vol.Optional("model_type"): cv.string,
        vol.Optional("model_year"): vol.Coerce(int),
        vol.Optional("color"): cv.string,
        vol.Optional("chassis_type"): cv.string,
        vol.Optional("fuel_type"): cv.string,
        vol.Optional("vehicle_type"): cv.string,
        vol.Optional("ignored"): cv.boolean,
        vol.Optional("notify_on_passage"): cv.boolean,
        vol.Optional("notify_on_speed"): cv.boolean,
    }
)
REMOVE_SCHEMA = vol.Schema({vol.Required("plate"): cv.string})
OBSERVATION_SCHEMA = vol.Schema(
    {
        vol.Required("plate"): cv.string,
        vol.Required("event_id"): cv.string,
        vol.Required("timestamp"): cv.string,
        vol.Optional("camera", default=""): cv.string,
        vol.Optional("score"): vol.Coerce(float),
        vol.Optional("speed_kmh"): vol.Coerce(float),
    }
)
REMOVE_OBSERVATION_SCHEMA = vol.Schema(
    {vol.Required("plate"): cv.string, vol.Required("event_id"): cv.string}
)


async def async_setup_entry(hass: HomeAssistant, entry: FrigateLPRConfigEntry) -> bool:
    await async_remove_legacy_dashboard(hass)
    await _async_register_card(hass)
    manager = LPRManager(
        hass,
        entry.entry_id,
        entry.data[CONF_TOPIC],
        entry.data[CONF_CAMERA],
        entry.options.get(CONF_FREQUENT_OBSERVATIONS, DEFAULT_FREQUENT_OBSERVATIONS),
        entry.options.get(CONF_FREQUENT_DAYS, DEFAULT_FREQUENT_DAYS),
        entry.options.get(CONF_MOTORAPI_ENABLED, DEFAULT_MOTORAPI_ENABLED),
        entry.options.get(CONF_MOTORAPI_KEY, ""),
        entry.options.get(CONF_SNAPSHOTS_ENABLED, DEFAULT_SNAPSHOTS_ENABLED),
        entry.options.get(CONF_SNAPSHOT_ENTITY, ""),
        entry.options.get(CONF_SPEED_ENABLED, DEFAULT_SPEED_ENABLED),
        entry.options.get(CONF_EVENTS_TOPIC, DEFAULT_EVENTS_TOPIC),
        entry.options.get(CONF_SPEED_UNIT, DEFAULT_SPEED_UNIT),
        entry.options.get(CONF_SPEED_LIMIT, DEFAULT_SPEED_LIMIT),
        tuple(
            service
            for service in (
                entry.options.get(CONF_NOTIFY_SERVICE_1, ""),
                entry.options.get(CONF_NOTIFY_SERVICE_2, ""),
            )
            if service
        ),
        entry.options.get(CONF_NOTIFY_CRITICAL, DEFAULT_NOTIFY_CRITICAL),
    )
    await manager.async_setup()
    entry.runtime_data = manager
    hass.data.setdefault(DOMAIN, {})["manager"] = manager
    if not hass.data.get(_SNAPSHOT_VIEW_REGISTERED):
        hass.http.register_view(LPRSnapshotView())
        hass.data[_SNAPSHOT_VIEW_REGISTERED] = True

    async def set_plate(call: ServiceCall) -> None:
        vehicle_field_map = {
            "make": "make",
            "model": "model",
            "variant": "variant",
            "model_type": "model_type",
            "model_year": "model_year",
            "color": "color",
            "chassis_type": "chassis_type",
            "fuel_type": "fuel_type",
            "vehicle_type": "type",
        }
        vehicle = {
            target: call.data[source]
            for source, target in vehicle_field_map.items()
            if source in call.data
        }
        await manager.async_set_metadata(
            call.data["plate"],
            call.data[CONF_NAME],
            call.data["category"],
            notes=call.data.get("notes"),
            vehicle=vehicle or None,
            ignored=call.data.get("ignored"),
            notify_on_passage=call.data.get("notify_on_passage"),
            notify_on_speed=call.data.get("notify_on_speed"),
        )

    async def remove_metadata(call: ServiceCall) -> None:
        await manager.async_remove_metadata(call.data["plate"])

    async def lookup_vehicle(call: ServiceCall) -> None:
        try:
            await manager.async_lookup_vehicle_manual(call.data["plate"])
        except ValueError as err:
            raise HomeAssistantError(str(err)) from err

    async def update_observation(call: ServiceCall) -> None:
        timestamp = dt_util.parse_datetime(call.data["timestamp"])
        if timestamp is None:
            raise HomeAssistantError("Invalid passage timestamp")
        if timestamp.tzinfo is None:
            timestamp = timestamp.replace(tzinfo=dt_util.DEFAULT_TIME_ZONE)
        if not await manager.async_update_observation(
            call.data["plate"],
            call.data["event_id"],
            timestamp,
            call.data.get("camera", ""),
            call.data.get("score"),
            call.data.get("speed_kmh"),
        ):
            raise HomeAssistantError("Passage not found")

    async def remove_observation(call: ServiceCall) -> None:
        if not await manager.async_remove_observation(
            call.data["plate"], call.data["event_id"]
        ):
            raise HomeAssistantError("Passage not found")

    async def remove_snapshot(call: ServiceCall) -> None:
        if not await manager.async_remove_snapshot(call.data["plate"]):
            raise HomeAssistantError("Vehicle case not found")

    hass.services.async_register(DOMAIN, SERVICE_SET_PLATE, set_plate, schema=SET_PLATE_SCHEMA)
    hass.services.async_register(DOMAIN, SERVICE_REMOVE_PLATE_METADATA, remove_metadata, schema=REMOVE_SCHEMA)
    hass.services.async_register(DOMAIN, SERVICE_LOOKUP_VEHICLE, lookup_vehicle, schema=REMOVE_SCHEMA)
    hass.services.async_register(
        DOMAIN, SERVICE_UPDATE_OBSERVATION, update_observation, schema=OBSERVATION_SCHEMA
    )
    hass.services.async_register(
        DOMAIN,
        SERVICE_REMOVE_OBSERVATION,
        remove_observation,
        schema=REMOVE_OBSERVATION_SCHEMA,
    )
    hass.services.async_register(
        DOMAIN, SERVICE_REMOVE_SNAPSHOT, remove_snapshot, schema=REMOVE_SCHEMA
    )
    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    entry.async_on_unload(entry.add_update_listener(_async_reload_entry))
    return True


async def async_unload_entry(hass: HomeAssistant, entry: FrigateLPRConfigEntry) -> bool:
    unloaded = await hass.config_entries.async_unload_platforms(entry, PLATFORMS)
    if unloaded:
        await entry.runtime_data.async_unload()
        hass.data.get(DOMAIN, {}).pop("manager", None)
        hass.services.async_remove(DOMAIN, SERVICE_SET_PLATE)
        hass.services.async_remove(DOMAIN, SERVICE_REMOVE_PLATE_METADATA)
        hass.services.async_remove(DOMAIN, SERVICE_LOOKUP_VEHICLE)
        hass.services.async_remove(DOMAIN, SERVICE_UPDATE_OBSERVATION)
        hass.services.async_remove(DOMAIN, SERVICE_REMOVE_OBSERVATION)
        hass.services.async_remove(DOMAIN, SERVICE_REMOVE_SNAPSHOT)
        frontend.remove_extra_js_url(hass, CARD_URL)
    return unloaded


async def _async_reload_entry(hass: HomeAssistant, entry: FrigateLPRConfigEntry) -> None:
    await hass.config_entries.async_reload(entry.entry_id)


class LPRSnapshotView(HomeAssistantView):
    """Serve locally retained vehicle snapshots to authenticated HA users."""

    url = SNAPSHOT_API_PATH
    name = "api:frigate_lpr:snapshot"
    requires_auth = True

    async def get(self, request: web.Request, plate: str) -> web.Response:
        manager: LPRManager | None = request.app[KEY_HASS].data.get(DOMAIN, {}).get("manager")
        if manager is None:
            raise web.HTTPNotFound
        image = await manager.async_snapshot_bytes(plate)
        if image is None:
            raise web.HTTPNotFound
        snapshot = manager.registry.plates.get(plate.upper(), {}).get("snapshot") or {}
        return web.Response(
            body=image,
            content_type=snapshot.get("content_type", "image/jpeg"),
            headers={"Cache-Control": "private, no-cache"},
        )


async def _async_register_card(hass: HomeAssistant) -> None:
    """Serve and register the bundled card as a Lovelace module."""
    card_path = Path(__file__).parent / "frontend" / "frigate-lpr-card.js"
    if not card_path.is_file():
        _LOGGER.warning("Bundled Lovelace card was not found at %s", card_path)
        return

    if not hass.data.get(_FRONTEND_REGISTERED):
        await hass.http.async_register_static_paths(
            [StaticPathConfig(STATIC_URL_PATH, str(card_path.parent), False)]
        )
        hass.data[_FRONTEND_REGISTERED] = True

    lovelace = hass.data.get(LOVELACE_DATA)
    if lovelace is None or lovelace.resource_mode != MODE_STORAGE:
        # YAML resource mode has no writable resource collection. Loading the
        # module globally keeps the card automatic for those installations.
        frontend.add_extra_js_url(hass, CARD_URL)
        return

    resources = lovelace.resources
    if not isinstance(resources, ResourceStorageCollection):
        frontend.add_extra_js_url(hass, CARD_URL)
        return

    # Force the resource store to load before inspecting or changing it. This
    # avoids replacing an as-yet-unloaded list of the user's existing resources.
    await resources.async_get_info()
    existing = next(
        (
            item
            for item in resources.async_items()
            if item.get("url", "").startswith(CARD_RESOURCE_PATH)
        ),
        None,
    )
    resource_data = {"res_type": "module", "url": CARD_URL}
    if existing is None:
        await resources.async_create_item(resource_data)
    elif existing.get("url") != CARD_URL or existing.get("res_type") != "module":
        await resources.async_update_item(existing["id"], resource_data)
