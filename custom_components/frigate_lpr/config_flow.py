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
    DEFAULT_CAMERA,
    DEFAULT_FREQUENT_DAYS,
    DEFAULT_FREQUENT_OBSERVATIONS,
    DEFAULT_TOPIC,
    DOMAIN,
)


class FrigateLPRConfigFlow(config_entries.ConfigFlow, domain=DOMAIN):
    VERSION = 1

    async def async_step_user(self, user_input: dict[str, Any] | None = None) -> FlowResult:
        await self.async_set_unique_id(DOMAIN)
        self._abort_if_unique_id_configured()
        if user_input is not None:
            return self.async_create_entry(title=f"Frigate LPR – {user_input[CONF_CAMERA]}", data=user_input)
        return self.async_show_form(
            step_id="user",
            data_schema=vol.Schema(
                {
                    vol.Required(CONF_TOPIC, default=DEFAULT_TOPIC): str,
                    vol.Required(CONF_CAMERA, default=DEFAULT_CAMERA): str,
                }
            ),
        )

    @staticmethod
    def async_get_options_flow(config_entry: config_entries.ConfigEntry) -> config_entries.OptionsFlow:
        return FrigateLPROptionsFlow()


class FrigateLPROptionsFlow(config_entries.OptionsFlow):
    async def async_step_init(self, user_input: dict[str, Any] | None = None) -> FlowResult:
        if user_input is not None:
            return self.async_create_entry(title="", data=user_input)
        return self.async_show_form(
            step_id="init",
            data_schema=vol.Schema(
                {
                    vol.Required(CONF_FREQUENT_OBSERVATIONS, default=self.config_entry.options.get(CONF_FREQUENT_OBSERVATIONS, DEFAULT_FREQUENT_OBSERVATIONS)): vol.All(int, vol.Range(min=2)),
                    vol.Required(CONF_FREQUENT_DAYS, default=self.config_entry.options.get(CONF_FREQUENT_DAYS, DEFAULT_FREQUENT_DAYS)): vol.All(int, vol.Range(min=2)),
                }
            ),
        )
