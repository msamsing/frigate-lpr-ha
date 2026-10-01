"""Config flow for Frigate LPR Registry."""

from __future__ import annotations

from typing import Any

import voluptuous as vol

from homeassistant import config_entries
from homeassistant.data_entry_flow import FlowResult
from homeassistant.helpers.selector import (
    BooleanSelector,
    TextSelector,
    TextSelectorConfig,
    TextSelectorType,
)

from .const import (
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
    DEFAULT_TOPIC,
    DEFAULT_VERIFY_SSL,
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
            menu_options=["classification", "vehicle_lookup", "snapshots", "add_plate", "remove_plate"],
        )

    async def async_step_classification(self, user_input: dict[str, Any] | None = None) -> FlowResult:
        """Configure frequency thresholds."""
        if user_input is not None:
            return self.async_create_entry(
                title="", data={**self.config_entry.options, **user_input}
            )
        return self.async_show_form(
            step_id="classification",
            data_schema=vol.Schema(
                {
                    vol.Required(
                        CONF_FREQUENT_OBSERVATIONS,
                        default=self.config_entry.options.get(
                            CONF_FREQUENT_OBSERVATIONS,
                            DEFAULT_FREQUENT_OBSERVATIONS,
                        ),
                    ): vol.All(int, vol.Range(min=2)),
                    vol.Required(
                        CONF_FREQUENT_DAYS,
                        default=self.config_entry.options.get(
                            CONF_FREQUENT_DAYS,
                            DEFAULT_FREQUENT_DAYS,
                        ),
                    ): vol.All(int, vol.Range(min=2)),
                }
            ),
        )

    async def async_step_vehicle_lookup(self, user_input: dict[str, Any] | None = None) -> FlowResult:
        """Configure optional lookups for brand-new unknown plates."""
        if user_input is not None:
            return self.async_create_entry(
                title="", data={**self.config_entry.options, **user_input}
            )
        return self.async_show_form(
            step_id="vehicle_lookup",
            data_schema=vol.Schema(
                {
                    vol.Required(
                        CONF_MOTORAPI_ENABLED,
                        default=self.config_entry.options.get(
                            CONF_MOTORAPI_ENABLED, DEFAULT_MOTORAPI_ENABLED
                        ),
                    ): BooleanSelector(),
                    vol.Optional(
                        CONF_MOTORAPI_KEY,
                        default=self.config_entry.options.get(CONF_MOTORAPI_KEY, ""),
                    ): TextSelector(TextSelectorConfig(type=TextSelectorType.PASSWORD)),
                }
            ),
        )

    async def async_step_snapshots(self, user_input: dict[str, Any] | None = None) -> FlowResult:
        """Configure persistent snapshots fetched from Frigate."""
        if user_input is not None:
            return self.async_create_entry(
                title="", data={**self.config_entry.options, **user_input}
            )
        return self.async_show_form(
            step_id="snapshots",
            data_schema=vol.Schema(
                {
                    vol.Required(
                        CONF_SNAPSHOTS_ENABLED,
                        default=self.config_entry.options.get(
                            CONF_SNAPSHOTS_ENABLED, DEFAULT_SNAPSHOTS_ENABLED
                        ),
                    ): BooleanSelector(),
                    vol.Optional(
                        CONF_FRIGATE_URL,
                        default=self.config_entry.options.get(CONF_FRIGATE_URL, ""),
                    ): TextSelector(TextSelectorConfig(type=TextSelectorType.URL)),
                    vol.Optional(
                        CONF_FRIGATE_TOKEN,
                        default=self.config_entry.options.get(CONF_FRIGATE_TOKEN, ""),
                    ): TextSelector(TextSelectorConfig(type=TextSelectorType.PASSWORD)),
                    vol.Required(
                        CONF_VERIFY_SSL,
                        default=self.config_entry.options.get(
                            CONF_VERIFY_SSL, DEFAULT_VERIFY_SSL
                        ),
                    ): BooleanSelector(),
                }
            ),
        )

    async def async_step_add_plate(self, user_input: dict[str, Any] | None = None) -> FlowResult:
        """Add user-controlled plate metadata."""
        if user_input is not None:
            manager: LPRManager = self.config_entry.runtime_data
            await manager.async_set_metadata(
                user_input["plate"],
                user_input["name"],
                user_input["category"],
                notes=user_input.get("notes", ""),
                vehicle={
                    "make": user_input.get("make", ""),
                    "model": user_input.get("model", ""),
                    "variant": user_input.get("variant", ""),
                    "model_type": user_input.get("model_type", ""),
                    "model_year": user_input.get("model_year"),
                    "color": user_input.get("color", ""),
                    "chassis_type": user_input.get("chassis_type", ""),
                    "fuel_type": user_input.get("fuel_type", ""),
                    "type": user_input.get("vehicle_type", ""),
                },
                ignored=user_input.get("ignored", False),
            )
            return self.async_create_entry(title="", data=dict(self.config_entry.options))
        return self.async_show_form(
            step_id="add_plate",
            data_schema=vol.Schema(
                {
                    vol.Required("plate"): str,
                    vol.Required("name"): str,
                    vol.Required("category", default="known"): vol.In(
                        ["own", "known", "unknown", "unwanted"]
                    ),
                    vol.Optional("notes", default=""): str,
                    vol.Optional("make", default=""): str,
                    vol.Optional("model", default=""): str,
                    vol.Optional("variant", default=""): str,
                    vol.Optional("model_type", default=""): str,
                    vol.Optional("model_year"): vol.All(int, vol.Range(min=1900, max=2100)),
                    vol.Optional("color", default=""): str,
                    vol.Optional("chassis_type", default=""): str,
                    vol.Optional("fuel_type", default=""): str,
                    vol.Optional("vehicle_type", default=""): str,
                    vol.Required("ignored", default=False): BooleanSelector(),
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
