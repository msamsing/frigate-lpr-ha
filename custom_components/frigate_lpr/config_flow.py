"""Config flow for Frigate LPR Registry."""

from __future__ import annotations

from typing import Any
import voluptuous as vol

from homeassistant import config_entries
from homeassistant.data_entry_flow import FlowResult

from .const import (
    CONF_CAMERA,
    CONF_FREQUENT_DAYS,
    CONF_FREQUENT_OBSERVATIONS,
    CONF_TOPIC,
    DEFAULT_FREQUENT_DAYS,
    DEFAULT_FREQUENT_OBSERVATIONS,
    DEFAULT_TOPIC,
    DOMAIN,
)
from .manager import LPRManager


class FrigateLPRConfigFlow(config_entries.ConfigFlow, domain=DOMAIN):
    VERSION = 1

    async def async_step_user(self, user_input: dict[str, Any] | None = None) -> FlowResult:
        await self.async_set_unique_id(DOMAIN)
        self._abort_if_unique_id_configured()
        if user_input is not None:
            return self.async_create_entry(title="Frigate LPR Registry", data=user_input)
        return self.async_show_form(
            step_id="user",
            data_schema=vol.Schema(
                {
                    vol.Required(CONF_TOPIC, default=DEFAULT_TOPIC): str,
                    vol.Optional(CONF_CAMERA, default=""): str,
                }
            ),
        )

    async def async_step_reconfigure(self, user_input: dict[str, Any] | None = None) -> FlowResult:
        """Change MQTT source settings from the UI."""
        entry = self._get_reconfigure_entry()
        if user_input is not None:
            return self.async_update_reload_and_abort(entry, data_updates=user_input)
        return self.async_show_form(
            step_id="reconfigure",
            data_schema=vol.Schema(
                {
                    vol.Required(CONF_TOPIC, default=entry.data[CONF_TOPIC]): str,
                    vol.Optional(CONF_CAMERA, default=entry.data.get(CONF_CAMERA, "")): str,
                }
            ),
        )

    @staticmethod
    def async_get_options_flow(config_entry: config_entries.ConfigEntry) -> config_entries.OptionsFlow:
        return FrigateLPROptionsFlow()


class FrigateLPROptionsFlow(config_entries.OptionsFlow):
    async def async_step_init(self, user_input: dict[str, Any] | None = None) -> FlowResult:
        """Show the settings menu."""
        return self.async_show_menu(
            step_id="init",
            menu_options=["classification", "add_plate", "remove_plate"],
        )

    async def async_step_classification(self, user_input: dict[str, Any] | None = None) -> FlowResult:
        """Configure frequency thresholds."""
        if user_input is not None:
            return self.async_create_entry(title="", data=user_input)
        return self.async_show_form(
            step_id="classification",
            data_schema=vol.Schema(
                {
                    vol.Required(CONF_FREQUENT_OBSERVATIONS, default=self.config_entry.options.get(CONF_FREQUENT_OBSERVATIONS, DEFAULT_FREQUENT_OBSERVATIONS)): vol.All(int, vol.Range(min=2)),
                    vol.Required(CONF_FREQUENT_DAYS, default=self.config_entry.options.get(CONF_FREQUENT_DAYS, DEFAULT_FREQUENT_DAYS)): vol.All(int, vol.Range(min=2)),
                }
            ),
        )

    async def async_step_add_plate(self, user_input: dict[str, Any] | None = None) -> FlowResult:
        """Add user-controlled plate metadata."""
        if user_input is not None:
            manager: LPRManager = self.config_entry.runtime_data
            await manager.async_set_metadata(
                user_input["plate"], user_input["name"], user_input["category"]
            )
            return self.async_create_entry(title="", data=dict(self.config_entry.options))
        return self.async_show_form(
            step_id="add_plate",
            data_schema=vol.Schema(
                {
                    vol.Required("plate"): str,
                    vol.Required("name"): str,
                    vol.Required("category", default="known"): vol.In(["own", "known"]),
                }
            ),
        )

    async def async_step_remove_plate(self, user_input: dict[str, Any] | None = None) -> FlowResult:
        """Remove user-controlled metadata without deleting history."""
        manager: LPRManager = self.config_entry.runtime_data
        known_plates = sorted(
            plate
            for plate, record in manager.registry.plates.items()
            if record.get("name") or record.get("category")
        )
        if not known_plates:
            return self.async_abort(reason="no_known_plates")
        if user_input is not None:
            await manager.async_remove_metadata(user_input["plate"])
            return self.async_create_entry(title="", data=dict(self.config_entry.options))
        return self.async_show_form(
            step_id="remove_plate",
            data_schema=vol.Schema({vol.Required("plate"): vol.In(known_plates)}),
        )
