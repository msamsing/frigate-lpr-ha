"""Frigate LPR Registry integration."""

from __future__ import annotations

import logging
from pathlib import Path

import voluptuous as vol

from homeassistant.config_entries import ConfigEntry
from homeassistant.components.http import StaticPathConfig
from homeassistant.const import CONF_NAME
from homeassistant.core import HomeAssistant, ServiceCall
from homeassistant.helpers import config_validation as cv

from .const import (
    CARD_URL,
    CONF_CAMERA,
    CONF_FREQUENT_DAYS,
    CONF_FREQUENT_OBSERVATIONS,
    CONF_TOPIC,
    DEFAULT_FREQUENT_DAYS,
    DEFAULT_FREQUENT_OBSERVATIONS,
    DOMAIN,
    PLATFORMS,
    SERVICE_REMOVE_PLATE_METADATA,
    SERVICE_SET_PLATE,
    STATIC_URL,
)
from .manager import LPRManager

FrigateLPRConfigEntry = ConfigEntry[LPRManager]
_LOGGER = logging.getLogger(__name__)

SET_PLATE_SCHEMA = vol.Schema(
    {
        vol.Required("plate"): cv.string,
        vol.Required(CONF_NAME): cv.string,
        vol.Required("category"): vol.In(["own", "known"]),
    }
)
REMOVE_SCHEMA = vol.Schema({vol.Required("plate"): cv.string})


async def async_setup_entry(hass: HomeAssistant, entry: FrigateLPRConfigEntry) -> bool:
    await _async_setup_lovelace_card(hass)
    manager = LPRManager(
        hass,
        entry.entry_id,
        entry.data[CONF_TOPIC],
        entry.data[CONF_CAMERA],
        entry.options.get(CONF_FREQUENT_OBSERVATIONS, DEFAULT_FREQUENT_OBSERVATIONS),
        entry.options.get(CONF_FREQUENT_DAYS, DEFAULT_FREQUENT_DAYS),
    )
    await manager.async_setup()
    entry.runtime_data = manager

    async def set_plate(call: ServiceCall) -> None:
        await manager.async_set_metadata(call.data["plate"], call.data[CONF_NAME], call.data["category"])

    async def remove_metadata(call: ServiceCall) -> None:
        await manager.async_remove_metadata(call.data["plate"])

    hass.services.async_register(DOMAIN, SERVICE_SET_PLATE, set_plate, schema=SET_PLATE_SCHEMA)
    hass.services.async_register(DOMAIN, SERVICE_REMOVE_PLATE_METADATA, remove_metadata, schema=REMOVE_SCHEMA)
    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    entry.async_on_unload(entry.add_update_listener(_async_reload_entry))
    return True


async def _async_setup_lovelace_card(hass: HomeAssistant) -> None:
    """Serve and register the bundled Lovelace card once per HA process."""
    domain_data = hass.data.setdefault(DOMAIN, {})
    if not domain_data.get("static_path_registered"):
        frontend_dir = Path(__file__).parent / "frontend"
        await hass.http.async_register_static_paths(
            [StaticPathConfig(STATIC_URL, str(frontend_dir), False)]
        )
        domain_data["static_path_registered"] = True

    if domain_data.get("lovelace_resource_registered"):
        return
    lovelace = hass.data.get("lovelace")
    resources = getattr(lovelace, "resources", None)
    if resources is None or not hasattr(resources, "async_create_item"):
        _LOGGER.warning(
            "Could not automatically register the Lovelace card. Add %s as a JavaScript module resource",
            CARD_URL,
        )
        return

    # Force lazy loading before reading/creating resources. This preserves existing
    # user resources on Home Assistant versions where the collection loads lazily.
    await resources.async_get_info()
    if not any(item.get("url", "").split("?", 1)[0] == CARD_URL for item in resources.async_items()):
        await resources.async_create_item({"res_type": "module", "url": CARD_URL})
    domain_data["lovelace_resource_registered"] = True


async def async_unload_entry(hass: HomeAssistant, entry: FrigateLPRConfigEntry) -> bool:
    unloaded = await hass.config_entries.async_unload_platforms(entry, PLATFORMS)
    if unloaded:
        await entry.runtime_data.async_unload()
        hass.services.async_remove(DOMAIN, SERVICE_SET_PLATE)
        hass.services.async_remove(DOMAIN, SERVICE_REMOVE_PLATE_METADATA)
    return unloaded


async def _async_reload_entry(hass: HomeAssistant, entry: FrigateLPRConfigEntry) -> None:
    await hass.config_entries.async_reload(entry.entry_id)
