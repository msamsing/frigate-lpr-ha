"""Create the bundled native Lovelace dashboard automatically."""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Any

from homeassistant.components import frontend
from homeassistant.components.lovelace import dashboard as lovelace_dashboard
from homeassistant.components.lovelace.const import LOVELACE_DATA
from homeassistant.core import HomeAssistant
from homeassistant.util.yaml import load_yaml_dict

from .const import DASHBOARD_URL_PATH

_LOGGER = logging.getLogger(__name__)


async def async_setup_dashboard(hass: HomeAssistant) -> None:
    """Persist and register the integration-owned native dashboard."""
    lovelace_data = hass.data.get(LOVELACE_DATA)
    if lovelace_data is None or hass.config.recovery_mode:
        _LOGGER.warning("Lovelace is unavailable; the LPR dashboard was not created")
        return

    config_path = Path(__file__).with_name("dashboard.yaml")
    dashboard_config: dict[str, Any] = await hass.async_add_executor_job(
        load_yaml_dict, str(config_path)
    )

    store = lovelace_data.dashboards.get(DASHBOARD_URL_PATH)
    if store is None:
        dashboards = lovelace_dashboard.DashboardsCollection(hass)
        await dashboards.async_load()
        item = next(
            (
                existing
                for existing in dashboards.async_items()
                if existing.get("url_path") == DASHBOARD_URL_PATH
            ),
            None,
        )
        if item is None:
            item = await dashboards.async_create_item(
                {
                    "icon": "mdi:car-search",
                    "require_admin": False,
                    "show_in_sidebar": True,
                    "title": "Nummerplader",
                    "url_path": DASHBOARD_URL_PATH,
                }
            )
        store = lovelace_dashboard.LovelaceStorage(hass, item)
        lovelace_data.dashboards[DASHBOARD_URL_PATH] = store

    if not frontend.async_panel_exists(hass, DASHBOARD_URL_PATH):
        frontend.async_register_built_in_panel(
            hass,
            "lovelace",
            frontend_url_path=DASHBOARD_URL_PATH,
            require_admin=False,
            show_in_sidebar=True,
            sidebar_icon="mdi:car-search",
            sidebar_title="Nummerplader",
            config={"mode": "storage"},
        )

    # This dashboard is owned by the integration and refreshed on setup so new
    # releases can improve the layout without touching any user-owned dashboard.
    await store.async_save(dashboard_config)


async def async_remove_dashboard(hass: HomeAssistant) -> None:
    """Remove only the dashboard owned by this integration."""
    lovelace_data = hass.data.get(LOVELACE_DATA)
    if lovelace_data is None:
        return

    dashboards = lovelace_dashboard.DashboardsCollection(hass)
    await dashboards.async_load()
    item = next(
        (
            existing
            for existing in dashboards.async_items()
            if existing.get("url_path") == DASHBOARD_URL_PATH
        ),
        None,
    )
    if item is not None:
        await dashboards.async_delete_item(item["id"])

    store = lovelace_data.dashboards.pop(DASHBOARD_URL_PATH, None)
    if store is not None:
        await store.async_delete()
    if frontend.async_panel_exists(hass, DASHBOARD_URL_PATH):
        frontend.async_remove_panel(hass, DASHBOARD_URL_PATH)
