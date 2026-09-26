"""Migrations from earlier Frigate LPR Registry releases."""

from __future__ import annotations

from homeassistant.components import frontend
from homeassistant.components.lovelace import dashboard as lovelace_dashboard
from homeassistant.components.lovelace.const import LOVELACE_DATA
from homeassistant.core import HomeAssistant

_LEGACY_DASHBOARD_PATH = "frigate-lpr"


async def async_remove_legacy_dashboard(hass: HomeAssistant) -> None:
    """Remove the standalone dashboard created only by release 1.3.1."""
    lovelace_data = hass.data.get(LOVELACE_DATA)
    if lovelace_data is None:
        return

    dashboards = lovelace_dashboard.DashboardsCollection(hass)
    await dashboards.async_load()
    item = next(
        (
            existing
            for existing in dashboards.async_items()
            if existing.get("url_path") == _LEGACY_DASHBOARD_PATH
        ),
        None,
    )
    if item is None:
        return

    await dashboards.async_delete_item(item["id"])
    store = lovelace_data.dashboards.pop(_LEGACY_DASHBOARD_PATH, None)
    if store is not None:
        await store.async_delete()
    if frontend.async_panel_exists(hass, _LEGACY_DASHBOARD_PATH):
        frontend.async_remove_panel(hass, _LEGACY_DASHBOARD_PATH)
