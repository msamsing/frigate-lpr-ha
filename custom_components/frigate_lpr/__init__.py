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

from .const import (
    CARD_RESOURCE_PATH,
    CARD_URL,
    CONF_CAMERA,
    CONF_FREQUENT_DAYS,
    CONF_FREQUENT_OBSERVATIONS,
    CONF_FRIGATE_TOKEN,
    CONF_FRIGATE_URL,
    CONF_MOTORAPI_ENABLED,
    CONF_MOTORAPI_KEY,
    CONF_SNAPSHOTS_ENABLED,
    CONF_TOPIC,
    CONF_VERIFY_SSL,
    DEFAULT_FREQUENT_DAYS,
    DEFAULT_FREQUENT_OBSERVATIONS,
    DEFAULT_MOTORAPI_ENABLED,
    DEFAULT_SNAPSHOTS_ENABLED,
    DEFAULT_VERIFY_SSL,
    DOMAIN,
    PLATFORMS,
    SERVICE_REMOVE_PLATE_METADATA,
    SERVICE_LOOKUP_VEHICLE,
    SERVICE_SET_PLATE,
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
    }
)
REMOVE_SCHEMA = vol.Schema({vol.Required("plate"): cv.string})


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
        entry.options.get(CONF_FRIGATE_URL, ""),
        entry.options.get(CONF_FRIGATE_TOKEN, ""),
        entry.options.get(CONF_VERIFY_SSL, DEFAULT_VERIFY_SSL),
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
        )

    async def remove_metadata(call: ServiceCall) -> None:
        await manager.async_remove_metadata(call.data["plate"])

    async def lookup_vehicle(call: ServiceCall) -> None:
        try:
            await manager.async_lookup_vehicle_manual(call.data["plate"])
        except ValueError as err:
            raise HomeAssistantError(str(err)) from err

    hass.services.async_register(DOMAIN, SERVICE_SET_PLATE, set_plate, schema=SET_PLATE_SCHEMA)
    hass.services.async_register(DOMAIN, SERVICE_REMOVE_PLATE_METADATA, remove_metadata, schema=REMOVE_SCHEMA)
    hass.services.async_register(DOMAIN, SERVICE_LOOKUP_VEHICLE, lookup_vehicle, schema=REMOVE_SCHEMA)
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
        return web.Response(
            body=image,
            content_type="image/jpeg",
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
