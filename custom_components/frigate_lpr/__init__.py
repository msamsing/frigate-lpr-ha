"""Frigate LPR Registry integration."""

from __future__ import annotations

import logging
from pathlib import Path

import voluptuous as vol

from homeassistant.components import frontend
from homeassistant.components.http import StaticPathConfig
from homeassistant.config_entries import ConfigEntry
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
    STATIC_URL_PATH,
)
from .manager import LPRManager
from .migration import async_remove_legacy_dashboard

_LOGGER = logging.getLogger(__name__)
_FRONTEND_REGISTERED = f"{DOMAIN}_frontend_registered"

FrigateLPRConfigEntry = ConfigEntry[LPRManager]

SET_PLATE_SCHEMA = vol.Schema(
    {
        vol.Required("plate"): cv.string,
        vol.Required(CONF_NAME): cv.string,
        vol.Required("category"): vol.In(["own", "known"]),
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


async def async_unload_entry(hass: HomeAssistant, entry: FrigateLPRConfigEntry) -> bool:
    unloaded = await hass.config_entries.async_unload_platforms(entry, PLATFORMS)
    if unloaded:
        await entry.runtime_data.async_unload()
        hass.services.async_remove(DOMAIN, SERVICE_SET_PLATE)
        hass.services.async_remove(DOMAIN, SERVICE_REMOVE_PLATE_METADATA)
        frontend.remove_extra_js_url(hass, CARD_URL)
    return unloaded


async def _async_reload_entry(hass: HomeAssistant, entry: FrigateLPRConfigEntry) -> None:
    await hass.config_entries.async_reload(entry.entry_id)


async def _async_register_card(hass: HomeAssistant) -> None:
    """Serve and load the bundled Lovelace card without manual resources."""
    card_path = Path(__file__).parent / "frontend" / "frigate-lpr-card.js"
    if not card_path.is_file():
        _LOGGER.warning("Bundled Lovelace card was not found at %s", card_path)
        return

    if not hass.data.get(_FRONTEND_REGISTERED):
        await hass.http.async_register_static_paths(
            [StaticPathConfig(STATIC_URL_PATH, str(card_path.parent), False)]
        )
        hass.data[_FRONTEND_REGISTERED] = True
    frontend.add_extra_js_url(hass, CARD_URL)
